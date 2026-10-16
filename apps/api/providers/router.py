"""Task-level provider router (SPEC §4.1).

Agents call task functions (score_items, parse_mention, ...). The router picks providers
from config/providers.yaml, retries 429/5xx with exponential backoff, falls back to the next
provider, validates JSON output with Pydantic (one repair retry), and logs every call to
provider_usage.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic import BaseModel, ValidationError

from apps.api import prompts
from apps.api.config import ModelConfig, ProvidersConfig, RouteStep, load_providers
from apps.api.providers.base import (
    ChatResult,
    ConnectionTest,
    EmbedResult,
    LLMProvider,
    MissingKeyError,
    ProviderError,
)
from apps.api.providers.schemas import (
    DocExtraction,
    ItemScore,
    ItemToScore,
    MentionParse,
    OutlierAnalysis,
    OutlierBatch,
    ScoreBatch,
    SecondOpinion,
    SupportBatch,
    SupportItem,
    SupportResult,
    SupportVerdict,
    VideoForAnalysis,
)
from apps.api.providers.usage import UsageLog
from apps.api.runctx import log_once_to_current_run, log_to_current_run

if TYPE_CHECKING:
    from apps.api.providers.parallel import ParallelScorer

log = logging.getLogger("wyrd.router")

# True while a call runs on a fallback provider (not the route's first usable one).
_on_fallback: ContextVar[bool] = ContextVar("_on_fallback", default=False)
# When set, _run appends "provider/model" for every successful call (who actually served it).
_served_by: ContextVar[list[str] | None] = ContextVar("_served_by", default=None)

# Token estimates used for batching/chunking (see estimate_tokens).
SCORE_OUTPUT_TOKENS_PER_ITEM = 120
EXTRACTION_OUTPUT_RESERVE_TOKENS = 8000

T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)


class InvalidOutputError(ProviderError):
    """Output still failed validation after the repair retry. Triggers fallback, not retry."""


class AllProvidersFailed(ProviderError):
    def __init__(self, task: str, errors: list[str], block: bool = False) -> None:
        super().__init__(
            "router",
            f"all providers failed for {task}: {'; '.join(errors) or 'none configured'}",
            block=block,
        )
        self.task = task
        self.errors = errors


@dataclass
class RouterEvent:
    """Retries, fallbacks, and skips — surfaced in run summaries and the dashboard."""

    task: str
    kind: str  # "retry" | "fallback" | "skip" | "failed"
    provider: str
    detail: str
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))


def _extract_json(text: str) -> Any:
    """Parse JSON from model text, tolerating ```json fences and leading prose."""
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL)
    if fence:
        stripped = fence.group(1).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = min((i for i in (stripped.find("{"), stripped.find("[")) if i >= 0), default=-1)
        if start < 0:
            raise
        return json.loads(stripped[start:])


def estimate_tokens(text: str) -> int:
    """Rough token count (~4 characters per token). Good enough for staying under limits."""
    return len(text) // 4 + 1


def split_text(text: str, max_chars: int) -> list[str]:
    """Split on paragraph, then line, then hard boundaries so each piece fits max_chars."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    current = ""
    for para in re.split(r"(\n\s*\n)", text):
        if len(current) + len(para) <= max_chars:
            current += para
            continue
        if current:
            chunks.append(current)
        while len(para) > max_chars:
            cut = para.rfind("\n", 0, max_chars)
            cut = cut if cut > max_chars // 2 else max_chars
            chunks.append(para[:cut])
            para = para[cut:]
        current = para
    if current.strip():
        chunks.append(current)
    return chunks


def _data_block(payload: Any) -> str:
    body = (
        payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=1)
    )
    return f"<data>\n{body}\n</data>"


class Router:
    def __init__(
        self,
        config: ProvidersConfig,
        providers: dict[str, LLMProvider],
        usage: UsageLog | None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.providers = providers
        self.usage = usage
        self._sleep = sleep
        self.events: deque[RouterEvent] = deque(maxlen=500)
        self._clock = clock
        self._auth_failed_at: dict[str, float] = {}  # provider → time of last 401/403
        self._auth_errors: dict[str, str] = {}  # provider → that error's message

    # ------------------------------------------------------------------ plumbing
    def _event(self, task: str, kind: str, provider: str, detail: str) -> None:
        self.events.append(RouterEvent(task, kind, provider, detail))
        log.warning("router %s %s via %s: %s", task, kind, provider, detail)
        if kind != "skip":  # skips repeat every call; retries/fallbacks/failures matter per run
            level = "error" if kind == "failed" else "warn"
            log_to_current_run(
                level,
                f"{task}: {kind} via {provider}: {detail}",
                {"task": task, "kind": kind, "provider": provider},
            )

    def _record(
        self,
        *,
        provider: str,
        model: str,
        task: str,
        ok: bool,
        start: float,
        tokens_in: int = 0,
        tokens_out: int = 0,
        error: str | None = None,
    ) -> None:
        if self.usage is None:
            return
        try:
            self.usage.record(
                provider=provider,
                model=model,
                task=task,
                ok=ok,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                error=error,
                fallback=ok and _on_fallback.get(),
                latency_ms=int((time.monotonic() - start) * 1000),
            )
        except Exception:  # usage logging must never break a call
            log.exception("failed to record provider usage")

    def _route(self, task: str) -> list[RouteStep]:
        """Configured route minus unusable providers; near-limit providers move last."""
        usable: list[tuple[bool, RouteStep]] = []
        for step in self.config.tasks.get(task, []):
            provider = self.providers.get(step.provider)
            if provider is None or not provider.configured:
                detail = getattr(
                    provider, "unconfigured_detail", "not configured (missing API key)"
                )
                self._event(task, "skip", step.provider, detail)
                if provider is not None and hasattr(provider, "unconfigured_detail"):
                    # Credentials the owner set up but that went missing: say so in the run log.
                    log_once_to_current_run(
                        f"skip:{step.provider}", "warn", f"{step.provider} skipped: {detail}"
                    )
                continue
            if self.auth_blocked(step.provider):
                self._event(task, "skip", step.provider, "credentials rejected recently (401/403)")
                log_once_to_current_run(
                    f"blocked:{step.provider}",
                    "warn",
                    f"{step.provider} skipped for now: "
                    f"{self._auth_errors.get(step.provider, '401/403')}",
                )
                continue
            near = False
            if self.usage is not None:
                model = self.config.model(step.provider, step.model)
                try:
                    near = (
                        self.usage.usage_ratio(step.provider, model.id, model.limits)
                        >= self.config.near_limit_ratio
                    )
                except Exception:
                    log.exception("usage check failed")
            if near:
                self._event(
                    task, "skip", step.provider, "near free-tier limit; trying others first"
                )
            usable.append((near, step))
        if task in self.config.headroom_tasks:
            # Most headroom first; no daily limit sorts last; sort() is stable (ties keep
            # config order).
            def headroom(pair: tuple[bool, RouteStep]) -> tuple[bool, float]:
                left = self._daily_left(pair[1])
                return pair[0], -(left if left is not None else -1.0)

            usable.sort(key=headroom)
            return [step for _, step in usable]
        return [step for _, step in sorted(usable, key=lambda pair: pair[0])]

    def _daily_left(self, step: RouteStep) -> float | None:
        """Share of the model's daily request limit still unused (None = no daily limit)."""
        model = self.config.model(step.provider, step.model)
        if self.usage is None or not model.limits.rpd:
            return None
        try:
            reqs, _, _ = self.usage.totals(
                step.provider, model.id, datetime.now(UTC) - timedelta(days=1)
            )
        except Exception:
            log.exception("usage check failed")
            return None
        return max(0.0, 1 - reqs / model.limits.rpd)

    def auth_error(self, provider: str) -> str | None:
        return self._auth_errors.get(provider) if self.auth_blocked(provider) else None

    def auth_blocked(self, provider: str) -> bool:
        failed_at = self._auth_failed_at.get(provider)
        if failed_at is None:
            return False
        if self._clock() - failed_at >= self.config.auth_failure_cooldown_s:
            del self._auth_failed_at[provider]
            return False
        return True

    def request_budget(self, task: str) -> int | None:
        """Smallest max_request_tokens among usable models in a task's route (None = no cap)."""
        caps = [
            self.config.model(step.provider, step.model).max_request_tokens
            for step in self.config.tasks.get(task, [])
            if (p := self.providers.get(step.provider)) is not None
            and p.configured
            and not self.auth_blocked(step.provider)
        ]
        known = [cap for cap in caps if cap]
        return min(known) if known else None

    def _backoff(self, attempt: int, err: ProviderError) -> float:
        retry = self.config.retry
        delay = min(retry.max_delay_s, retry.base_delay_s * (2**attempt))
        if err.retry_after_s is not None:
            delay = min(retry.max_delay_s, max(delay, err.retry_after_s))
        return delay

    async def _run(
        self,
        task: str,
        call: Callable[[str, LLMProvider, ModelConfig, bool], Awaitable[T]],
        route: list[RouteStep] | None = None,
    ) -> T:
        """Try each provider in the route with retries; return the first success.

        `route` overrides the configured route (the parallel scorer pins one provider)."""
        errors: list[str] = []
        blocks: list[bool] = []  # per failed provider: was it a block (bad key / zero quota)?
        steps = route if route is not None else self._route(task)
        for index, step in enumerate(steps):
            provider = self.providers[step.provider]
            model = self.config.model(step.provider, step.model)
            json_mode = (
                model.json_mode
                if model.json_mode is not None
                else self.config.providers[step.provider].json_mode
            )
            for attempt in range(self.config.retry.max_attempts):
                token = _on_fallback.set(index > 0)
                try:
                    result = await call(step.provider, provider, model, json_mode)
                except MissingKeyError as e:
                    errors.append(str(e))
                    blocks.append(True)
                    break
                except InvalidOutputError as e:
                    errors.append(str(e))
                    blocks.append(False)
                    break
                except ProviderError as e:
                    errors.append(str(e))
                    blocks.append(e.block)
                    if e.block:
                        self._auth_failed_at[step.provider] = self._clock()
                        self._auth_errors[step.provider] = str(e)
                    if e.retryable and attempt + 1 < self.config.retry.max_attempts:
                        delay = self._backoff(attempt, e)
                        self._event(task, "retry", step.provider, f"{e} (waiting {delay:.1f}s)")
                        await self._sleep(delay)
                        continue
                    break
                finally:
                    _on_fallback.reset(token)
                if index > 0:
                    self._event(
                        task,
                        "fallback",
                        step.provider,
                        f"succeeded after {', '.join(s.provider for s in steps[:index])} failed",
                    )
                served = _served_by.get()
                if served is not None:
                    served.append(f"{step.provider}/{model.id}")
                return result
        self._event(task, "failed", "router", "; ".join(errors) or "no providers configured")
        raise AllProvidersFailed(task, errors, block=bool(blocks) and all(blocks))

    async def _chat_logged(
        self,
        task: str,
        name: str,
        provider: LLMProvider,
        model: ModelConfig,
        *,
        system: str,
        user: str,
        json_mode: bool,
        schema: dict[str, Any] | None,
    ) -> ChatResult:
        start = time.monotonic()
        try:
            result = await provider.chat(
                model=model.id,
                system=system,
                user=user,
                json_mode=json_mode,
                json_schema=schema,
                extra=model.extra,
            )
        except ProviderError as e:
            self._record(
                provider=name, model=model.id, task=task, ok=False, start=start, error=str(e)
            )
            raise
        self._record(
            provider=name,
            model=model.id,
            task=task,
            ok=True,
            start=start,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
        )
        return result

    async def _json_task(
        self,
        task: str,
        prompt: str,
        payload: Any,
        out: type[M],
        prompt_vars: dict[str, str] | None = None,
        route: list[RouteStep] | None = None,
    ) -> M:
        schema = out.model_json_schema()
        schema_text = json.dumps(schema)
        system = prompts.render(prompt, output_schema=schema_text, **(prompt_vars or {}))
        user = _data_block(payload)

        async def call(name: str, provider: LLMProvider, model: ModelConfig, json_mode: bool) -> M:
            result = await self._chat_logged(
                task,
                name,
                provider,
                model,
                system=system,
                user=user,
                json_mode=json_mode,
                schema=schema,
            )
            try:
                return out.model_validate(_extract_json(result.text))
            except (ValueError, ValidationError) as first_error:
                error_text = str(first_error)[:1000]
            # One repair retry on the same provider.
            repair_system = prompts.render(
                "json_repair", output_schema=schema_text, error=error_text
            )
            repaired = await self._chat_logged(
                task,
                name,
                provider,
                model,
                system=repair_system,
                user=result.text,
                json_mode=json_mode,
                schema=schema,
            )
            try:
                return out.model_validate(_extract_json(repaired.text))
            except (ValueError, ValidationError) as e:
                raise InvalidOutputError(name, f"invalid JSON after repair: {str(e)[:200]}") from e

        return await self._run(task, call, route=route)

    # ------------------------------------------------------------------ tasks
    def _score_batches(self, items: Sequence[ItemToScore]) -> list[list[ItemToScore]]:
        budget = self.request_budget("score_items")
        if not budget:
            return [list(items)] if items else []
        overhead = estimate_tokens(
            prompts.render(
                "scout_scoring",
                output_schema=json.dumps(ScoreBatch.model_json_schema()),
                series_hint="",
            )
        )
        batches: list[list[ItemToScore]] = []
        current: list[ItemToScore] = []
        used = overhead
        for item in items:
            # input JSON for the item + ~120 tokens of score output per item
            cost = estimate_tokens(item.model_dump_json()) + SCORE_OUTPUT_TOKENS_PER_ITEM
            if current and used + cost > budget:
                batches.append(current)
                current, used = [], overhead
            current.append(item)
            used += cost
        if current:
            batches.append(current)
        return batches

    async def score_items(
        self, items: Sequence[ItemToScore], series_hint: str = ""
    ) -> list[ItemScore]:
        """Scores items in batches sized to the route's max_request_tokens.

        `series_hint` is optional extra guidance inserted into the prompt (e.g. the series the
        owner asked for); it is filled into prompts/scout_scoring.md, not written here."""
        scores: list[ItemScore] = []
        for batch_items in self._score_batches(items):
            payload = [item.model_dump() for item in batch_items]
            batch = await self._json_task(
                "score_items",
                "scout_scoring",
                payload,
                ScoreBatch,
                prompt_vars={"series_hint": series_hint},
            )
            wanted = {item.id for item in batch_items}
            scores += [score for score in batch.scores if score.id in wanted]
        return scores

    async def parse_mention(self, text: str) -> MentionParse:
        return await self._json_task("parse_mention", "parse_mention", text, MentionParse)

    async def extract_from_document(
        self, document: str, question: str, deep: bool = False
    ) -> DocExtraction:
        """Long-document extraction. `deep` uses the stronger (low-quota) model route.

        Documents larger than the route's max_request_tokens are split into chunks; each
        chunk is queried separately and the results merged.
        """
        task = "extract_from_document_deep" if deep else "extract_from_document"
        budget = self.request_budget(task)
        chunks = [document]
        if budget:
            overhead = estimate_tokens(
                prompts.render(
                    "doc_extraction", output_schema=json.dumps(DocExtraction.model_json_schema())
                )
                + question
            )
            room = budget - overhead - EXTRACTION_OUTPUT_RESERVE_TOKENS
            chunks = split_text(document, max(room, 1000) * 4)

        results: list[DocExtraction] = []
        for chunk in chunks:
            payload = f"QUESTION: {question}\n\nDOCUMENT:\n{chunk}"
            results.append(await self._json_task(task, "doc_extraction", payload, DocExtraction))

        found = [r for r in results if r.found]
        merged = DocExtraction(
            answer=" ".join(r.answer for r in found) if found else results[0].answer,
            extracts=[x for r in results for x in r.extracts],
            found=bool(found),
        )
        # Drop any "quote" that isn't actually in the document (research integrity).
        normalized_doc = " ".join(document.split())
        merged.extracts = [
            x for x in merged.extracts if " ".join(x.quote.split()) in normalized_doc
        ]
        return merged

    async def analyze_outliers(self, videos: Sequence[VideoForAnalysis]) -> list[OutlierAnalysis]:
        payload = [video.model_dump() for video in videos]
        batch = await self._json_task("analyze_outliers", "outlier_analysis", payload, OutlierBatch)
        return batch.analyses

    def primary_step(self, task: str) -> RouteStep | None:
        steps = self.config.tasks.get(task) or []
        return steps[0] if steps else None

    async def check_support(
        self, items: Sequence[SupportItem], primary_only: bool = False
    ) -> SupportResult:
        """Per claim: does its excerpt support every factual part? Batched to the route's
        request budget. The result says which providers served it: anything other than the
        configured primary (Groq) counts as a fallback, including when the router moved a
        near-limit Groq to the back of the route. `primary_only` pins the primary (no
        fallback), for "Re-check with Groq"."""
        primary = self.primary_step("check_support")
        route = [primary] if primary_only and primary is not None else None
        budget = self.request_budget("check_support") or 6000
        verdicts: list[SupportVerdict] = []
        batch: list[SupportItem] = []
        used = 1500  # prompt overhead
        served: list[str] = []
        token = _served_by.set(served)
        try:
            for item in [*items, None]:
                size = estimate_tokens(item.model_dump_json()) + 80 if item else 0
                if batch and (item is None or used + size > budget):
                    out = await self._json_task(
                        "check_support",
                        "claim_support",
                        [b.model_dump() for b in batch],
                        SupportBatch,
                        route=route,
                    )
                    verdicts += out.verdicts
                    batch, used = [], 1500
                if item is not None:
                    batch.append(item)
                    used += size
        finally:
            _served_by.reset(token)
        primary_label = (
            f"{primary.provider}/{self.config.model(primary.provider, primary.model).id}"
            if primary
            else None
        )
        return SupportResult(
            verdicts=verdicts,
            served_by=sorted(set(served)),
            primary=primary_label,
            fallback=any(s != primary_label for s in served),
        )

    async def second_opinion(self, dossier_markdown: str) -> SecondOpinion:
        return await self._json_task(
            "second_opinion", "second_opinion", dossier_markdown, SecondOpinion
        )

    async def embed(self, texts: Sequence[str]) -> EmbedResult:
        texts = list(texts)

        async def call(
            name: str, provider: LLMProvider, model: ModelConfig, _json: bool
        ) -> EmbedResult:
            start = time.monotonic()
            try:
                result = await provider.embed(
                    model=model.id, texts=texts, dimensions=model.dimensions, extra=model.extra
                )
            except ProviderError as e:
                self._record(
                    provider=name, model=model.id, task="embed", ok=False, start=start, error=str(e)
                )
                raise
            self._record(
                provider=name,
                model=model.id,
                task="embed",
                ok=True,
                start=start,
                tokens_in=result.tokens_in,
            )
            return result

        return await self._run("embed", call)

    # ------------------------------------------------------------------ status
    async def test_connection(self, provider_name: str) -> ConnectionTest:
        provider = self.providers.get(provider_name)
        if provider is None:
            return ConnectionTest(provider=provider_name, ok=False, detail="unknown provider")
        auth = getattr(provider, "auth_mode", None)
        if not provider.configured:
            env = self.config.providers[provider_name].api_key_env
            detail = getattr(provider, "unconfigured_detail", f"{env} is not set")
            return ConnectionTest(provider=provider_name, ok=False, detail=detail, auth=auth)
        result = await provider.test_connection()
        result.auth = auth
        if result.ok:
            self._auth_failed_at.pop(provider_name, None)
        return result


# ---------------------------------------------------------------------- default instance
def gemini_uses_oauth() -> bool:
    from apps.api.settings import get_settings

    mode = get_settings().gemini_auth.strip().strip("'\"").lower()
    if mode not in ("", "api_key", "oauth"):
        log.warning("GEMINI_AUTH=%r is not 'api_key' or 'oauth'; using api_key", mode)
    return mode == "oauth"


def build_providers(config: ProvidersConfig) -> dict[str, LLMProvider]:
    from apps.api.providers.gemini import GeminiProvider
    from apps.api.providers.gemini_oauth import GeminiOAuthProvider
    from apps.api.providers.groq import GroqProvider
    from apps.api.providers.mistral import MistralProvider
    from apps.api.providers.nvidia import NvidiaProvider
    from apps.api.providers.openai_compat import OpenAICompatProvider
    from apps.api.providers.openrouter import OpenRouterProvider
    from apps.api.settings import get_settings

    simple: dict[str, type[OpenAICompatProvider]] = {
        "groq": GroqProvider,
        "openrouter": OpenRouterProvider,
    }
    settings = get_settings()
    built: dict[str, LLMProvider] = {}
    for name, pc in config.providers.items():
        key = settings.key_for(pc.api_key_env) if pc.api_key_env else ""
        timeout: dict[str, Any] = {"timeout_s": pc.timeout_s} if pc.timeout_s else {}
        if name in simple:
            built[name] = simple[name](
                base_url=pc.base_url or "",
                api_key=key,
                api_key_env=pc.api_key_env or "",
                **timeout,
            )
        elif name == "mistral":
            small = pc.models.get("small")
            built[name] = MistralProvider(
                base_url=pc.base_url or "",
                api_key=key,
                api_key_env=pc.api_key_env or "",
                probe_model=small.id if small else "",
                **timeout,
            )
        elif name == "nvidia":
            embed = pc.models.get("embed")
            built[name] = NvidiaProvider(
                base_url=pc.base_url or "",
                api_key=key,
                api_key_env=pc.api_key_env or "",
                probe_model=embed.id if embed else "",
                probe_extra=embed.extra if embed else None,
                **timeout,
            )
        elif name == "gemini" and gemini_uses_oauth():
            # OAuth takes priority over GEMINI_API_KEY whenever GEMINI_AUTH=oauth.
            built[name] = GeminiOAuthProvider(quota_project=settings.google_cloud_quota_project)
        elif name == "gemini":
            built[name] = GeminiProvider(api_key=key, api_key_env=pc.api_key_env or "")
    return built


@lru_cache
def get_router() -> Router:
    from apps.api.db.session import get_engine

    config = load_providers()
    return Router(config, build_providers(config), UsageLog(get_engine()))


# Module-level task functions — the API agents use.
async def score_items(items: Sequence[ItemToScore], series_hint: str = "") -> list[ItemScore]:
    return await get_router().score_items(items, series_hint)


async def parse_mention(text: str) -> MentionParse:
    return await get_router().parse_mention(text)


async def extract_from_document(document: str, question: str, deep: bool = False) -> DocExtraction:
    return await get_router().extract_from_document(document, question, deep)


async def analyze_outliers(videos: Sequence[VideoForAnalysis]) -> list[OutlierAnalysis]:
    return await get_router().analyze_outliers(videos)


async def second_opinion(dossier_markdown: str) -> SecondOpinion:
    return await get_router().second_opinion(dossier_markdown)


async def embed(texts: Sequence[str]) -> EmbedResult:
    return await get_router().embed(texts)


def parallel_scorer(router: Router | None = None) -> ParallelScorer:
    from apps.api.config import ParallelConfig
    from apps.api.providers.parallel import ParallelScorer

    r = router or get_router()
    return ParallelScorer(r, r.config.parallel.get("score_items", ParallelConfig()))
