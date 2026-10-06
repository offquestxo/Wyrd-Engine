"""Client for OpenAI-compatible chat/embedding APIs (Groq, NVIDIA)."""

from __future__ import annotations

import time
from typing import Any

import httpx

from apps.api.providers.base import (
    ChatResult,
    ConnectionTest,
    EmbedResult,
    MissingKeyError,
    ProviderError,
    classify_status,
)


class OpenAICompatProvider:
    name = "openai_compat"
    supports_embeddings = False
    send_encoding_format = True
    auth_mode = "api_key"  # some APIs (Mistral) don't take encoding_format

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        api_key_env: str,
        timeout_s: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._api_key_env = api_key_env
        self._timeout = timeout_s
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            raise MissingKeyError(self.name, self._api_key_env)
        return {"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"}

    async def _request(self, method: str, path: str, json: dict[str, Any] | None = None) -> Any:
        headers = self._headers()
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            resp = await client.request(
                method, f"{self.base_url}{path}", json=json, headers=headers
            )
        except httpx.TimeoutException as e:
            raise ProviderError(self.name, "timeout", retryable=True) from e
        except httpx.HTTPError as e:
            raise ProviderError(
                self.name, f"network error: {type(e).__name__}", retryable=True
            ) from e
        finally:
            if self._client is None:
                await client.aclose()
        if resp.status_code >= 400:
            retry_after = resp.headers.get("retry-after")
            raise ProviderError(
                self.name,
                f"HTTP {resp.status_code}: {resp.text[:200]}",
                status=resp.status_code,
                retryable=classify_status(resp.status_code),
                retry_after_s=float(retry_after) if retry_after and retry_after.isdigit() else None,
            )
        try:
            return resp.json()
        except ValueError as e:
            raise ProviderError(self.name, "invalid JSON response", retryable=True) from e

    async def chat(
        self,
        *,
        model: str,
        system: str,
        user: str,
        json_mode: bool,
        json_schema: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> ChatResult:
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        body.update(extra or {})
        data = await self._request("POST", "/chat/completions", body)
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise ProviderError(self.name, "unexpected chat response shape", retryable=True) from e
        usage = data.get("usage") or {}
        return ChatResult(
            text=text,
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
        )

    async def embed(
        self,
        *,
        model: str,
        texts: list[str],
        dimensions: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> EmbedResult:
        if not self.supports_embeddings:
            raise ProviderError(self.name, "embeddings not supported")
        body: dict[str, Any] = {"model": model, "input": texts}
        if self.send_encoding_format:
            body["encoding_format"] = "float"
        body.update(extra or {})
        if dimensions:
            body["dimensions"] = dimensions
        data = await self._request("POST", "/embeddings", body)
        rows = sorted(data.get("data") or [], key=lambda r: r.get("index", 0))
        vectors = [list(map(float, r["embedding"])) for r in rows]
        if len(vectors) != len(texts):
            raise ProviderError(self.name, "embedding count mismatch", retryable=True)
        usage = data.get("usage") or {}
        return EmbedResult(
            vectors=vectors, model=model, tokens_in=int(usage.get("prompt_tokens") or 0)
        )

    async def list_models(self) -> list[str]:
        data = await self._request("GET", "/models")
        return [str(m.get("id")) for m in data.get("data") or []]

    async def test_connection(self) -> ConnectionTest:
        start = time.monotonic()
        try:
            await self._probe()
        except ProviderError as e:
            return ConnectionTest(
                provider=self.name,
                ok=False,
                detail=str(e),
                latency_ms=int((time.monotonic() - start) * 1000),
            )
        return ConnectionTest(
            provider=self.name,
            ok=True,
            detail="connected",
            latency_ms=int((time.monotonic() - start) * 1000),
        )

    async def _probe(self) -> None:
        await self._request("GET", "/models")
