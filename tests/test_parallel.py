"""Parallel scoring lanes: spread, rate windows, failures, blocks, last resort."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from apps.api.config import ProvidersConfig
from apps.api.db.migrate import migrate_path
from apps.api.db.session import make_engine
from apps.api.providers.base import ChatResult, ProviderError
from apps.api.providers.parallel import ParallelScorer, RateWindow
from apps.api.providers.router import Router
from apps.api.providers.schemas import ItemToScore
from apps.api.providers.usage import UsageLog


def score_json(user: str) -> str:
    items = json.loads(user.split("<data>")[1].split("</data>")[0])
    return json.dumps(
        {
            "scores": [
                {
                    "id": i["id"],
                    "drama": 7,
                    "twist": 7,
                    "relatability": 7,
                    "visual_potential": 7,
                    "hook_number": 7,
                    "freshness": 7,
                    "hook": "h",
                    "series": "Fraud Files",
                    "format": "Long",
                }
                for i in items
            ]
        }
    )


class Lane:
    def __init__(
        self, name: str, delay: float = 0.0, fail: Exception | None = None, configured: bool = True
    ) -> None:
        self.name, self.delay, self.fail, self.configured = name, delay, fail, configured
        self.calls = 0
        self.items = 0

    async def chat(self, **kw: Any) -> ChatResult:
        self.calls += 1
        await asyncio.sleep(self.delay)
        if self.fail:
            raise self.fail
        self.items += kw["user"].count('"id"')
        return ChatResult(text=score_json(kw["user"]), tokens_in=100, tokens_out=50)

    async def test_connection(self) -> Any:  # pragma: no cover
        return None


def config(
    order: list[str],
    limits: dict[str, dict[str, Any]] | None = None,
    cfg: dict[str, Any] | None = None,
) -> ProvidersConfig:
    limits = limits or {}
    return ProvidersConfig.model_validate(
        {
            "providers": {
                n: {
                    "kind": "openai_compat",
                    "api_key_env": f"{n.upper()}_KEY",
                    "json_mode": True,
                    "models": {
                        "m": {
                            "id": f"{n}-model",
                            "max_request_tokens": 1500,
                            "limits": limits.get(n, {}),
                        }
                    },
                }
                for n in order
            },
            "retry": {"max_attempts": 1},
            "parallel": {"score_items": {"last_resort": ["or"], **(cfg or {})}},
            "tasks": {"score_items": [{"provider": n, "model": "m"} for n in order]},
        }
    )


@pytest.fixture
def engine(tmp_path: Path) -> Any:
    migrate_path(tmp_path / "p.db")
    return make_engine(tmp_path / "p.db")


def items(n: int) -> list[ItemToScore]:
    return [
        ItemToScore(id=str(i), title=f"Company number {i} files for bankruptcy", snippet="x" * 200)
        for i in range(n)
    ]


def scorer(engine: Any, lanes: dict[str, Lane], **kw: Any) -> ParallelScorer:
    cfg = config(list(lanes), **kw)
    router = Router(cfg, lanes, UsageLog(engine))  # type: ignore[arg-type]
    return ParallelScorer(router, cfg.parallel["score_items"])


async def test_batches_spread_across_providers_in_parallel(engine: Any) -> None:
    lanes = {
        "groq": Lane("groq", 0.05),
        "nvidia": Lane("nvidia", 0.05),
        "gemini": Lane("gemini", 0.05),
    }
    seen: list[str] = []
    out = await scorer(engine, lanes).score(items(40), on_batch=lambda b: seen.append(b.provider))
    assert len(out.scores) == 40 and not out.unscored
    assert {lane.name for lane in lanes.values() if lane.items} == {"groq", "nvidia", "gemini"}
    assert set(out.scored_by.values()) == {
        "groq/groq-model",
        "nvidia/nvidia-model",
        "gemini/gemini-model",
    }
    assert sum(lane.items for lane in lanes.values()) == 40


async def test_failed_batches_requeue_to_other_lanes(engine: Any) -> None:
    lanes = {
        "groq": Lane("groq", fail=ProviderError("groq", "HTTP 500", status=500, retryable=True)),
        "nvidia": Lane("nvidia", 0.01),
    }
    drops: list[str] = []
    out = await scorer(engine, lanes).score(
        items(12), on_lane_drop=lambda lane, r: drops.append(lane)
    )
    assert len(out.scores) == 12 and lanes["nvidia"].items == 12
    assert drops == ["groq/groq-model"]  # dropped after max_failures_per_lane


async def test_blocked_provider_drops_out_immediately(engine: Any) -> None:
    lanes = {
        "mistral": Lane(
            "mistral", fail=ProviderError("mistral", "limit 0", status=429, block=True)
        ),
        "nvidia": Lane("nvidia", 0.01),
    }
    out = await scorer(engine, lanes).score(items(6))
    assert lanes["mistral"].calls == 1 and len(out.scores) == 6
    assert any("blocked" in e for e in out.lane_errors)


async def test_last_resort_only_after_others_drop(engine: Any) -> None:
    lanes = {"groq": Lane("groq", 0.02), "or": Lane("or", 0.0)}
    out = await scorer(engine, lanes).score(items(10))
    assert lanes["or"].calls == 0 and len(out.scores) == 10

    lanes = {
        "groq": Lane("groq", fail=ProviderError("groq", "HTTP 401", status=401)),
        "or": Lane("or"),
    }
    out = await scorer(engine, lanes).score(items(5))
    assert lanes["or"].items == 5 and len(out.scores) == 5


async def test_unscorable_items_are_reported_not_lost(engine: Any) -> None:
    lanes = {
        "groq": Lane("groq", fail=ProviderError("groq", "HTTP 500", status=500, retryable=True))
    }
    out = await scorer(engine, lanes, cfg={"max_failures_per_lane": 5}).score(items(3))
    assert not out.scores and {i.id for i in out.unscored} == {"0", "1", "2"}


async def test_unconfigured_lanes_are_skipped(engine: Any) -> None:
    lanes = {"groq": Lane("groq", configured=False), "nvidia": Lane("nvidia")}
    out = await scorer(engine, lanes).score(items(4))
    assert lanes["groq"].calls == 0 and len(out.scores) == 4


def test_rate_window_respects_rpm_and_tpm() -> None:
    now = [100.0]
    w = RateWindow(rpm=2, tpm=1000, safety=1.0, clock=lambda: now[0])
    assert w.wait_for(400) == 0
    w.add(400)
    w.add(400)
    assert w.wait_for(10) == pytest.approx(60)  # rpm=2 used up until the first ages out
    now[0] += 30
    assert w.wait_for(300) == pytest.approx(30)
    now[0] += 31
    assert w.wait_for(300) == 0  # first call aged out: 400 + 300 ≤ 1000
    w2 = RateWindow(rpm=None, tpm=1000, safety=1.0, clock=lambda: now[0])
    w2.seed([(50.0, 900)])  # a 900-token call 50 s ago
    assert w2.wait_for(200) == pytest.approx(10)


async def test_idle_lane_hedges_a_slow_batch(engine: Any) -> None:
    import time

    lanes = {"gemini": Lane("gemini", delay=5.0), "groq": Lane("groq", delay=0.01)}
    s = scorer(engine, lanes, cfg={"hedge_after_s": 0.2})
    t0 = time.monotonic()
    out = await s.score(items(30))
    assert time.monotonic() - t0 < 2.0  # didn't wait for the 5 s straggler
    assert len(out.scores) == 30 and not out.unscored
    assert any(b.hedge for b in out.batches)  # groq re-ran gemini's slow batch and won
