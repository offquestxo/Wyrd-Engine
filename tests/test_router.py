"""Router behaviour: retries, fallback on simulated provider failure, JSON repair, usage logging."""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlmodel import Session, select

from apps.api.config import ProvidersConfig, RouteStep
from apps.api.db.migrate import migrate_path
from apps.api.db.models import ProviderUsage
from apps.api.db.session import make_engine
from apps.api.providers.base import ChatResult, ConnectionTest, EmbedResult, ProviderError
from apps.api.providers.router import AllProvidersFailed, Router
from apps.api.providers.schemas import ItemToScore
from apps.api.providers.usage import UsageLog

GOOD_SCORE = {
    "id": "a",
    "drama": 8,
    "twist": 7,
    "relatability": 9,
    "visual_potential": 6,
    "hook_number": 7,
    "freshness": 5,
    "hook": "The store everyone knew vanished overnight.",
    "series": "Recent Collapses",
    "format": "Long",
}


class FakeProvider:
    """Replays a script of responses: str → ChatResult text, Exception → raised."""

    def __init__(self, name: str, script: list[Any], configured: bool = True) -> None:
        self.name = name
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []
        self._configured = configured

    @property
    def configured(self) -> bool:
        return self._configured

    def _next(self) -> Any:
        item = self.script.pop(0) if self.script else ProviderError(self.name, "script exhausted")
        if isinstance(item, Exception):
            raise item
        return item

    async def chat(self, **kwargs: Any) -> ChatResult:
        self.calls.append(kwargs)
        return ChatResult(text=self._next(), tokens_in=10, tokens_out=5)

    async def embed(self, **kwargs: Any) -> EmbedResult:
        self.calls.append(kwargs)
        vectors = self._next()
        return EmbedResult(vectors=vectors, model=kwargs["model"], tokens_in=3)

    async def test_connection(self) -> ConnectionTest:
        return ConnectionTest(provider=self.name, ok=True, detail="fake")


def make_config() -> ProvidersConfig:
    limits = {"rpm": 30, "rpd": 1000, "tpm": None, "tpd": None}
    return ProvidersConfig.model_validate(
        {
            "providers": {
                "groq": {
                    "kind": "openai_compat",
                    "api_key_env": "GROQ_API_KEY",
                    "json_mode": True,
                    "models": {"fast": {"id": "groq-model", "limits": limits}},
                },
                "gemini": {
                    "kind": "gemini",
                    "api_key_env": "GEMINI_API_KEY",
                    "json_mode": True,
                    "models": {
                        "lite": {"id": "gemini-model", "limits": limits},
                        "embed": {"id": "gemini-embed", "dimensions": 4},
                    },
                },
                "nvidia": {
                    "kind": "openai_compat",
                    "api_key_env": "NVIDIA_API_KEY",
                    "models": {
                        "chat": {"id": "nvidia-model", "limits": limits},
                        "embed": {"id": "nvidia-embed"},
                    },
                },
            },
            "retry": {"max_attempts": 3, "base_delay_s": 1.0, "max_delay_s": 8.0},
            "near_limit_ratio": 0.9,
            "tasks": {
                "score_items": [
                    {"provider": "groq", "model": "fast"},
                    {"provider": "gemini", "model": "lite"},
                    {"provider": "nvidia", "model": "chat"},
                ],
                "embed": [
                    {"provider": "nvidia", "model": "embed"},
                    {"provider": "gemini", "model": "embed"},
                ],
            },
        }
    )


@pytest.fixture
def engine(tmp_path: Any) -> Any:
    db = tmp_path / "test.db"
    migrate_path(db)
    return make_engine(db)


def make_router(engine: Any, **providers: FakeProvider) -> tuple[Router, list[float]]:
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    return Router(make_config(), dict(providers), UsageLog(engine), sleep=fake_sleep), sleeps


def usage_rows(engine: Any) -> list[ProviderUsage]:
    with Session(engine) as s:
        return list(s.exec(select(ProviderUsage).order_by(ProviderUsage.id)))  # type: ignore[arg-type]


ITEMS = [ItemToScore(id="a", title="Circuit City liquidates all stores")]


async def test_primary_success_logs_usage(engine: Any) -> None:
    groq = FakeProvider("groq", [json.dumps({"scores": [GOOD_SCORE]})])
    router, _ = make_router(
        engine, groq=groq, gemini=FakeProvider("gemini", []), nvidia=FakeProvider("nvidia", [])
    )
    scores = await router.score_items(ITEMS)
    assert scores[0].drama == 8
    rows = usage_rows(engine)
    assert [(r.provider, r.ok, r.task, r.tokens_in) for r in rows] == [
        ("groq", True, "score_items", 10)
    ]
    # The fetched content is wrapped as data, and the prompt came from prompts/scout_scoring.md.
    assert "<data>" in groq.calls[0]["user"]
    assert "wyrd.exe" in groq.calls[0]["system"]


async def test_fallback_when_primary_fails(engine: Any) -> None:
    """Simulated outage: Groq returns 503 on every attempt → router falls back to Gemini."""
    outage = ProviderError("groq", "HTTP 503", status=503, retryable=True)
    groq = FakeProvider("groq", [outage, outage, outage])
    gemini = FakeProvider("gemini", [json.dumps({"scores": [GOOD_SCORE]})])
    router, sleeps = make_router(
        engine, groq=groq, gemini=gemini, nvidia=FakeProvider("nvidia", [])
    )

    scores = await router.score_items(ITEMS)

    assert scores[0].id == "a"
    assert len(groq.calls) == 3  # retried up to max_attempts
    assert sleeps == [1.0, 2.0]  # exponential backoff between attempts
    rows = usage_rows(engine)
    assert [(r.provider, r.ok) for r in rows] == [("groq", False)] * 3 + [("gemini", True)]
    kinds = [e.kind for e in router.events]
    assert kinds.count("retry") == 2 and "fallback" in kinds


async def test_non_retryable_error_falls_back_immediately(engine: Any) -> None:
    groq = FakeProvider("groq", [ProviderError("groq", "HTTP 401", status=401, retryable=False)])
    gemini = FakeProvider("gemini", [json.dumps({"scores": [GOOD_SCORE]})])
    router, sleeps = make_router(
        engine, groq=groq, gemini=gemini, nvidia=FakeProvider("nvidia", [])
    )
    await router.score_items(ITEMS)
    assert len(groq.calls) == 1 and sleeps == []


async def test_retry_after_header_respected(engine: Any) -> None:
    limited = ProviderError("groq", "HTTP 429", status=429, retryable=True, retry_after_s=5)
    groq = FakeProvider("groq", [limited, json.dumps({"scores": [GOOD_SCORE]})])
    router, sleeps = make_router(
        engine, groq=groq, gemini=FakeProvider("gemini", []), nvidia=FakeProvider("nvidia", [])
    )
    await router.score_items(ITEMS)
    assert sleeps == [5.0]


async def test_invalid_json_gets_one_repair_then_succeeds(engine: Any) -> None:
    bad = json.dumps({"scores": [{**GOOD_SCORE, "drama": 42}]})  # out of 1–10 range
    groq = FakeProvider("groq", [bad, "```json\n" + json.dumps({"scores": [GOOD_SCORE]}) + "\n```"])
    router, _ = make_router(
        engine, groq=groq, gemini=FakeProvider("gemini", []), nvidia=FakeProvider("nvidia", [])
    )
    scores = await router.score_items(ITEMS)
    assert scores[0].drama == 8
    assert len(groq.calls) == 2
    assert "failed validation" in groq.calls[1]["system"]  # prompts/json_repair.md


async def test_invalid_json_after_repair_falls_back(engine: Any) -> None:
    groq = FakeProvider("groq", ["not json", "still not json"])
    nvidia_ok = json.dumps({"scores": [GOOD_SCORE]})
    gemini = FakeProvider("gemini", ["{}", "{}"])  # valid JSON, wrong shape, twice
    nvidia = FakeProvider("nvidia", [f"Sure! Here you go: {nvidia_ok}"])
    router, _ = make_router(engine, groq=groq, gemini=gemini, nvidia=nvidia)
    scores = await router.score_items(ITEMS)
    assert scores[0].id == "a"
    assert (len(groq.calls), len(gemini.calls), len(nvidia.calls)) == (2, 2, 1)


async def test_unconfigured_provider_is_skipped(engine: Any) -> None:
    groq = FakeProvider("groq", [], configured=False)
    gemini = FakeProvider("gemini", [json.dumps({"scores": [GOOD_SCORE]})])
    router, _ = make_router(engine, groq=groq, gemini=gemini, nvidia=FakeProvider("nvidia", []))
    await router.score_items(ITEMS)
    assert groq.calls == []
    assert any(e.kind == "skip" and e.provider == "groq" for e in router.events)


async def test_near_limit_provider_tried_last(engine: Any) -> None:
    usage = UsageLog(engine)
    for _ in range(28):  # 28/30 rpm ≥ 0.9
        usage.record(provider="groq", model="groq-model", task="score_items", ok=True)
    groq = FakeProvider("groq", [json.dumps({"scores": [GOOD_SCORE]})])
    gemini = FakeProvider("gemini", [json.dumps({"scores": [GOOD_SCORE]})])
    router, _ = make_router(engine, groq=groq, gemini=gemini, nvidia=FakeProvider("nvidia", []))
    await router.score_items(ITEMS)
    assert groq.calls == [] and len(gemini.calls) == 1


async def test_all_providers_failing_raises_cleanly(engine: Any) -> None:
    down = ProviderError("x", "HTTP 401", status=401)
    router, _ = make_router(
        engine,
        groq=FakeProvider("groq", [down]),
        gemini=FakeProvider("gemini", [down]),
        nvidia=FakeProvider("nvidia", [down]),
    )
    with pytest.raises(AllProvidersFailed) as exc:
        await router.score_items(ITEMS)
    assert len(exc.value.errors) == 3


async def test_embed_falls_back_and_records_model(engine: Any) -> None:
    nvidia = FakeProvider(
        "nvidia", [ProviderError("nvidia", "HTTP 500", status=500, retryable=True)] * 3
    )
    gemini = FakeProvider("gemini", [[[0.1, 0.2, 0.3, 0.4]]])
    router, _ = make_router(engine, groq=FakeProvider("groq", []), gemini=gemini, nvidia=nvidia)
    result = await router.embed(["Circuit City"])
    assert result.model == "gemini-embed" and len(result.vectors[0]) == 4
    assert gemini.calls[0]["dimensions"] == 4


async def test_extract_drops_quotes_not_in_document(engine: Any) -> None:
    config = make_config()
    config.tasks["extract_from_document"] = config.tasks["score_items"]
    doc = "Circuit City Stores, Inc. filed for Chapter 11 on November 10, 2008."
    answer = {
        "answer": "It filed in Nov 2008.",
        "found": True,
        "extracts": [
            {"quote": "filed for Chapter 11 on November 10, 2008"},
            {"quote": "Circuit City had 1,500 stores"},  # fabricated → must be dropped
        ],
    }
    groq = FakeProvider("groq", [json.dumps(answer)])
    router = Router(config, {"groq": groq}, UsageLog(engine))
    result = await router.extract_from_document(doc, "When did it file?")
    assert [x.quote for x in result.extracts] == ["filed for Chapter 11 on November 10, 2008"]


# ---------------------------------------------------------------- batching / chunking
def budget_config(cap: int) -> ProvidersConfig:
    config = make_config()
    gemma = {"id": "gemma-model", "json_mode": False, "max_request_tokens": cap}
    config.providers["gemini"].models["gemma"] = type(config.model("gemini", "lite"))(**gemma)
    route = [{"provider": "groq", "model": "fast"}, {"provider": "gemini", "model": "gemma"}]
    config.tasks["score_items"] = [type(config.tasks["embed"][0])(**s) for s in route]
    config.tasks["extract_from_document"] = config.tasks["score_items"]
    return config


async def test_per_model_json_mode_override_and_groq_skip(engine: Any) -> None:
    groq = FakeProvider("groq", [], configured=False)  # no key → Gemma leads
    gemini = FakeProvider("gemini", [json.dumps({"scores": [GOOD_SCORE]})])
    router = Router(budget_config(100_000), {"groq": groq, "gemini": gemini}, UsageLog(engine))
    await router.score_items(ITEMS)
    assert gemini.calls[0]["model"] == "gemma-model"
    assert gemini.calls[0]["json_mode"] is False


async def test_score_items_batches_under_token_budget(engine: Any) -> None:
    items = [ItemToScore(id=str(i), title="x" * 400) for i in range(12)]
    gemini = FakeProvider("gemini", [])
    router = Router(budget_config(2500), {"gemini": gemini}, UsageLog(engine))
    batches = router._score_batches(items)
    assert len(batches) > 1 and sum(len(b) for b in batches) == 12
    gemini.script = [
        json.dumps({"scores": [{**GOOD_SCORE, "id": i.id} for i in b]}) for b in batches
    ]
    scores = await router.score_items(items)
    assert sorted(int(s.id) for s in scores) == list(range(12))
    assert len(gemini.calls) == len(batches)


def test_split_text_respects_max_chars() -> None:
    from apps.api.providers.router import split_text

    text = "\n\n".join(f"Paragraph {i}. " + "word " * 50 for i in range(40))
    chunks = split_text(text, 1000)
    assert len(chunks) > 1 and all(len(c) <= 1000 for c in chunks)
    assert "".join(chunks) == text
    assert split_text("short", 1000) == ["short"]


async def test_extract_chunks_long_documents_and_merges(engine: Any) -> None:
    doc = "\n\n".join(
        [f"Filler paragraph {i}. " + "lorem " * 200 for i in range(30)]
        + ["Circuit City filed for Chapter 11 on November 10, 2008."]
    )
    gemini = FakeProvider("gemini", [])
    router = Router(budget_config(12_000), {"gemini": gemini}, UsageLog(engine))
    not_found = json.dumps({"answer": "Not in this part.", "found": False, "extracts": []})
    hit = json.dumps(
        {
            "answer": "November 10, 2008.",
            "found": True,
            "extracts": [{"quote": "filed for Chapter 11 on November 10, 2008"}],
        }
    )

    # Only the chunk containing the filing date "finds" the answer.
    async def chat(**kwargs: Any) -> Any:
        gemini.calls.append(kwargs)
        text = hit if "November 10, 2008" in kwargs["user"] else not_found
        return ChatResult(text=text, tokens_in=1, tokens_out=1)

    gemini.chat = chat  # type: ignore[method-assign]
    result = await router.extract_from_document(doc, "When did it file?")
    assert len(gemini.calls) > 1
    assert all(len(c["user"]) // 4 < 12_000 for c in gemini.calls)
    assert result.found and result.answer == "November 10, 2008."
    assert [x.quote for x in result.extracts] == ["filed for Chapter 11 on November 10, 2008"]


async def test_extract_deep_uses_deep_route(engine: Any) -> None:
    config = make_config()
    config.tasks["extract_from_document_deep"] = config.tasks["score_items"][1:2]  # gemini
    config.tasks["extract_from_document"] = config.tasks["score_items"][:1]  # groq
    answer = json.dumps({"answer": "a", "found": False, "extracts": []})
    groq, gemini = FakeProvider("groq", [answer]), FakeProvider("gemini", [answer])
    router = Router(config, {"groq": groq, "gemini": gemini}, UsageLog(engine))
    await router.extract_from_document("doc", "q", deep=True)
    assert len(gemini.calls) == 1 and groq.calls == []


async def test_gemini_aq_key_gets_actionable_error() -> None:
    from google.genai import errors

    from apps.api.providers.gemini import GeminiProvider

    provider = GeminiProvider(api_key="AQ.fake")
    err = provider._wrap(errors.ClientError(401, {"error": {"message": "Expected OAuth 2"}}))
    assert "AIza" in str(err) and not err.retryable


async def test_auth_failure_skips_provider_until_cooldown(engine: Any) -> None:
    now = [1000.0]
    rejected = ProviderError("gemini", "HTTP 401", status=401)
    ok = json.dumps({"scores": [GOOD_SCORE]})
    gemini = FakeProvider("gemini", [rejected, ok])
    nvidia = FakeProvider("nvidia", [ok, ok])
    config = make_config()
    config.tasks["score_items"] = config.tasks["score_items"][1:]  # gemini → nvidia
    router = Router(
        config, {"gemini": gemini, "nvidia": nvidia}, UsageLog(engine), clock=lambda: now[0]
    )

    await router.score_items(ITEMS)  # gemini 401 → nvidia
    await router.score_items(ITEMS)  # gemini skipped entirely
    assert len(gemini.calls) == 1 and len(nvidia.calls) == 2

    now[0] += config.auth_failure_cooldown_s
    await router.score_items(ITEMS)  # cooldown over → gemini tried again and works
    assert len(gemini.calls) == 2 and len(nvidia.calls) == 2


async def test_headroom_route_prefers_model_with_most_daily_requests_left(engine: Any) -> None:
    config = make_config()
    config.providers["gemini"].models["flash"] = (
        config.providers["gemini"]
        .models["lite"]
        .model_copy(
            update={
                "id": "gemini-flash",
                "limits": config.providers["gemini"]
                .models["lite"]
                .limits.model_copy(update={"rpd": 20, "rpm": None}),
            }
        )
    )
    config.tasks["extract_from_document"] = [
        RouteStep(provider="gemini", model="flash"),  # 20/day
        RouteStep(provider="gemini", model="lite"),  # 1000/day
        RouteStep(provider="nvidia", model="chat"),
    ]
    nv = config.providers["nvidia"].models["chat"]
    config.providers["nvidia"].models["chat"] = nv.model_copy(
        update={"limits": nv.limits.model_copy(update={"rpd": None})}  # no daily limit: last
    )
    config.headroom_tasks = ["extract_from_document"]
    providers = {"gemini": FakeProvider("gemini", []), "nvidia": FakeProvider("nvidia", [])}
    router = Router(config, providers, UsageLog(engine))  # type: ignore[arg-type]
    order = lambda: [s.model for s in router._route("extract_from_document")]  # noqa: E731
    assert order() == ["flash", "lite", "chat"]  # all fresh: config order
    usage = UsageLog(engine)
    for _ in range(5):  # flash: 15/20 left (75%) < lite 100%
        usage.record(provider="gemini", model="gemini-flash", task="x", ok=True)
    assert order() == ["lite", "flash", "chat"]


async def test_check_support_falls_back_and_returns_verdicts(engine: Any) -> None:
    from apps.api.providers.schemas import SupportItem

    config = make_config()
    config.tasks["check_support"] = [
        RouteStep(provider="groq", model="fast"),
        RouteStep(provider="nvidia", model="chat"),
    ]
    reply = {
        "verdicts": [
            {"id": "0", "supported": True},
            {
                "id": "1",
                "supported": False,
                "unsupported_parts": ["to save money"],
                "trimmed_claim": "Fired 3,400 workers",
            },
        ]
    }
    groq = FakeProvider("groq", [ProviderError("groq", "HTTP 401", status=401)])
    nvidia = FakeProvider("nvidia", [json.dumps(reply)])
    router = Router(config, {"groq": groq, "nvidia": nvidia}, UsageLog(engine))  # type: ignore[arg-type]
    items = [
        SupportItem(
            id="0", claim="Filed Chapter 11 on 2008-11-10", excerpt="filed ... November 10, 2008"
        ),
        SupportItem(
            id="1", claim="Fired 3,400 workers to save money", excerpt="laid off approximately 3400"
        ),
    ]
    result = await router.check_support(items)
    verdicts = result.verdicts
    assert [v.supported for v in verdicts] == [True, False]
    assert result.fallback is True and result.served_by == ["nvidia/nvidia-model"]
    assert verdicts[1].trimmed_claim == "Fired 3,400 workers"
    assert (
        "excerpt" in nvidia.calls[0]["user"] and "every factual part" in nvidia.calls[0]["system"]
    )


async def test_check_support_near_limit_groq_counts_as_fallback(engine: Any) -> None:
    """The router moves a near-limit Groq to the back, so NVIDIA answers first; that's still a
    fallback for the support check. primary_only pins Groq."""
    from apps.api.providers.schemas import SupportItem

    config = make_config()
    config.tasks["check_support"] = [
        RouteStep(provider="groq", model="fast"),
        RouteStep(provider="nvidia", model="chat"),
    ]
    usage = UsageLog(engine)
    for _ in range(28):  # 28/30 rpm ≥ near_limit_ratio
        usage.record(provider="groq", model="groq-model", task="x", ok=True)
    reply = json.dumps({"verdicts": [{"id": "0", "supported": True}]})
    groq = FakeProvider("groq", [reply])
    nvidia = FakeProvider("nvidia", [reply])
    router = Router(config, {"groq": groq, "nvidia": nvidia}, UsageLog(engine))  # type: ignore[arg-type]
    items = [SupportItem(id="0", claim="c", excerpt="e")]
    lenient = await router.check_support(items)
    assert lenient.served_by == ["nvidia/nvidia-model"] and lenient.fallback is True
    assert lenient.primary == "groq/groq-model" and groq.calls == []
    strict = await router.check_support(items, primary_only=True)
    assert strict.served_by == ["groq/groq-model"] and strict.fallback is False


def test_provider_timeout_comes_from_config() -> None:
    from apps.api.config import load_providers
    from apps.api.providers.router import build_providers

    config = load_providers()
    built = build_providers(config)
    assert config.providers["nvidia"].timeout_s == 150
    assert built["nvidia"]._timeout == 150  # type: ignore[attr-defined]
    assert built["groq"]._timeout == 60.0  # type: ignore[attr-defined]  # adapter default


def test_disabled_provider_is_skipped_and_reported(monkeypatch: Any) -> None:
    from apps.api.config import load_providers
    from apps.api.providers.router import Router

    config = load_providers()
    assert config.providers["mistral"].enabled is False
    assert any(s.provider == "mistral" for s in config.tasks["extract_from_document"])  # kept
    router = Router(config, {}, None)  # type: ignore[arg-type]
    assert router.disabled("mistral") and not router.disabled("nvidia")
    assert all(s.provider != "mistral" for s in router._route("extract_from_document"))


def test_openrouter_long_context_fallback() -> None:
    from apps.api.config import load_providers

    config = load_providers()
    long = config.model("openrouter", "long")
    assert long.id.endswith(":free") and long.max_request_tokens == 200000
    for task in ("extract_from_document", "extract_from_document_deep", "analyze_outliers"):
        assert config.tasks[task][-1].provider == "openrouter"
        assert config.tasks[task][-1].model == "long"
