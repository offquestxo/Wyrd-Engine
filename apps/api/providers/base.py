"""Shared provider types. Agents never import providers directly — use providers.router."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel


class ProviderError(Exception):
    """A provider call failed.

    retryable: worth retrying the same provider (429, 5xx, timeouts).
    Non-retryable errors (bad key, bad request) move straight to the next fallback.
    """

    def __init__(
        self,
        provider: str,
        message: str,
        *,
        status: int | None = None,
        retryable: bool = False,
        retry_after_s: float | None = None,
        block: bool = False,
    ) -> None:
        message = " ".join(message.split())  # raw JSON error bodies → one readable line
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.status = status
        self.retryable = retryable
        self.retry_after_s = retry_after_s
        # block: the account can't use this provider right now (bad key, zero quota);
        # the router skips it for auth_failure_cooldown_s instead of retrying.
        self.block = block or status in (401, 403)


class MissingKeyError(ProviderError):
    def __init__(self, provider: str, env_name: str) -> None:
        super().__init__(provider, f"{env_name} is not set")


def classify_status(status: int) -> bool:
    """True if an HTTP status is worth retrying."""
    return status == 429 or status == 408 or status >= 500


class ChatResult(BaseModel):
    text: str
    tokens_in: int = 0
    tokens_out: int = 0


class EmbedResult(BaseModel):
    vectors: list[list[float]]
    model: str
    tokens_in: int = 0


class ConnectionTest(BaseModel):
    provider: str
    ok: bool
    detail: str
    latency_ms: int = 0
    auth: str | None = None  # how the provider authenticated, e.g. "api_key" or "oauth (ADC)"


class LLMProvider(Protocol):
    name: str

    @property
    def configured(self) -> bool: ...

    async def chat(
        self,
        *,
        model: str,
        system: str,
        user: str,
        json_mode: bool,
        json_schema: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> ChatResult: ...

    async def embed(
        self,
        *,
        model: str,
        texts: list[str],
        dimensions: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> EmbedResult: ...

    async def test_connection(self) -> ConnectionTest: ...
