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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, TypeVar

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
    VideoForAnalysis,
)
from apps.api.providers.usage import UsageLog

log = logging.getLogger("wyrd.router")

T = TypeVar("T")
M = TypeVar("M", bound=BaseModel)


class InvalidOutputError(ProviderError):
    """Output still failed validation after the repair retry. Triggers fallback, not retry."""


class AllProvidersFailed(ProviderError):
    def __init__(self, task: str, errors: list[str]) -> None:
        super().__init__(
            "router", f"all providers failed for {task}: {'; '.join(errors) or 'none configured'}"
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
    ) -> None:
        self.config = config
        self.providers = providers
        self.usage = usage
        self._sleep = sleep
        self.events: deque[RouterEvent] = deque(maxlen=500)

    # ------------------------------------------------------------------ plumbing
    def _event(self, task: str, kind: str, provider: str, detail: str) -> None:
        self.events.append(RouterEvent(task, kind, provider, detail))
        log.warning("router %s %s via %s: %s", task, kind, provider, detail)

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
                self._event(task, "skip", step.provider, "not configured (missing API key)")
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
        return [step for _, step in sorted(usable, key=lambda pair: pair[0])]

    def _backoff(self, attempt: int, err: ProviderError) -> float:
        retry = self.config.retry
        delay = min(retry.max_delay_s, retry.base_delay_s * (2**attempt))
        if err.retry_after_s is not None:
            delay = min(retry.max_delay_s, max(delay, err.retry_after_s))
        return delay

    async def _run(
        self, task: str, call: Callable[[str, LLMProvider, ModelConfig, bool], Awaitable[T]]
    ) -> T:
        """Try each provider in the route with retries; return the first success."""
        errors: list[str] = []
        steps = self._route(task)
        for index, step in enumerate(steps):
            provider = self.providers[step.provider]
            model = self.config.model(step.provider, step.model)
            json_mode = self.config.providers[step.provider].json_mode
            for attempt in range(self.config.retry.max_attempts):
                try:
                    result = await call(step.provider, provider, model, json_mode)
                except MissingKeyError as e:
                    errors.append(str(e))
                    break
                except InvalidOutputError as e:
                    errors.append(str(e))
                    break
                except ProviderError as e:
                    errors.append(str(e))
                    if e.retryable and attempt + 1 < self.config.retry.max_attempts:
                        delay = self._backoff(attempt, e)
                        self._event(task, "retry", step.provider, f"{e} (waiting {delay:.1f}s)")
                        await self._sleep(delay)
                        continue
                    break
                if index > 0:
                    self._event(
                        task,
                        "fallback",
                        step.provider,
                        f"succeeded after {', '.join(s.provider for s in steps[:index])} failed",
                    )
                return result
        self._event(task, "failed", "router", "; ".join(errors) or "no providers configured")
        raise AllProvidersFailed(task, errors)

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

        return await self._run(task, call)

    # ------------------------------------------------------------------ tasks
    async def score_items(self, items: Sequence[ItemToScore]) -> list[ItemScore]:
        payload = [item.model_dump() for item in items]
        batch = await self._json_task("score_items", "scout_scoring", payload, ScoreBatch)
        wanted = {item.id for item in items}
        return [score for score in batch.scores if score.id in wanted]

    async def parse_mention(self, text: str) -> MentionParse:
        return await self._json_task("parse_mention", "parse_mention", text, MentionParse)

    async def extract_from_document(self, document: str, question: str) -> DocExtraction:
        payload = f"QUESTION: {question}\n\nDOCUMENT:\n{document}"
        result = await self._json_task(
            "extract_from_document", "doc_extraction", payload, DocExtraction
        )
        # Drop any "quote" that isn't actually in the document (research integrity).
        normalized_doc = " ".join(document.split())
        result.extracts = [
            x for x in result.extracts if " ".join(x.quote.split()) in normalized_doc
        ]
        return result

    async def analyze_outliers(self, videos: Sequence[VideoForAnalysis]) -> list[OutlierAnalysis]:
        payload = [video.model_dump() for video in videos]
        batch = await self._json_task("analyze_outliers", "outlier_analysis", payload, OutlierBatch)
        return batch.analyses

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
        if not provider.configured:
            env = self.config.providers[provider_name].api_key_env
            return ConnectionTest(provider=provider_name, ok=False, detail=f"{env} is not set")
        return await provider.test_connection()


# ---------------------------------------------------------------------- default instance
def build_providers(config: ProvidersConfig) -> dict[str, LLMProvider]:
    from apps.api.providers.gemini import GeminiProvider
    from apps.api.providers.groq import GroqProvider
    from apps.api.providers.nvidia import NvidiaProvider
    from apps.api.settings import get_settings

    settings = get_settings()
    built: dict[str, LLMProvider] = {}
    for name, pc in config.providers.items():
        key = settings.key_for(pc.api_key_env) if pc.api_key_env else ""
        if name == "groq":
            built[name] = GroqProvider(
                base_url=pc.base_url or "", api_key=key, api_key_env=pc.api_key_env or ""
            )
        elif name == "nvidia":
            embed = pc.models.get("embed")
            built[name] = NvidiaProvider(
                base_url=pc.base_url or "",
                api_key=key,
                api_key_env=pc.api_key_env or "",
                probe_model=embed.id if embed else "",
                probe_extra=embed.extra if embed else None,
            )
        elif name == "gemini":
            built[name] = GeminiProvider(api_key=key, api_key_env=pc.api_key_env or "")
    return built


@lru_cache
def get_router() -> Router:
    from apps.api.db.session import get_engine

    config = load_providers()
    return Router(config, build_providers(config), UsageLog(get_engine()))


# Module-level task functions — the API agents use.
async def score_items(items: Sequence[ItemToScore]) -> list[ItemScore]:
    return await get_router().score_items(items)


async def parse_mention(text: str) -> MentionParse:
    return await get_router().parse_mention(text)


async def extract_from_document(document: str, question: str) -> DocExtraction:
    return await get_router().extract_from_document(document, question)


async def analyze_outliers(videos: Sequence[VideoForAnalysis]) -> list[OutlierAnalysis]:
    return await get_router().analyze_outliers(videos)


async def second_opinion(dossier_markdown: str) -> SecondOpinion:
    return await get_router().second_opinion(dossier_markdown)


async def embed(texts: Sequence[str]) -> EmbedResult:
    return await get_router().embed(texts)
