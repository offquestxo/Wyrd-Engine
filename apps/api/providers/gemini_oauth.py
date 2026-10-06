"""Gemini via OAuth (gcloud Application Default Credentials) instead of an API key.

Used when GEMINI_AUTH=oauth. The google-genai SDK only accepts API keys for the Gemini
Developer API (OAuth credentials are only used in its Vertex AI mode), so this calls the
REST API directly with a bearer token. Setup: README "Gemini via OAuth" and
https://ai.google.dev/gemini-api/docs/oauth
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Callable
from typing import Any

import google.auth
import google.auth.transport.requests
import httpx
from google.auth.credentials import Credentials
from google.auth.exceptions import DefaultCredentialsError, RefreshError

from apps.api.providers.base import (
    ChatResult,
    ConnectionTest,
    EmbedResult,
    ProviderError,
    classify_status,
)

BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/generative-language.retriever",
]
NOT_SET_UP = (
    "GEMINI_AUTH=oauth, but no Application Default Credentials were found "
    "(`gcloud auth application-default print-access-token` fails). Run the "
    "`gcloud auth application-default login --client-id-file=... --scopes=...` step in the README."
)


def _camel(key: str) -> str:
    return re.sub(r"_([a-z])", lambda m: m.group(1).upper(), key)


def camelize(value: Any) -> Any:
    """REST field names are camelCase; config extras are written snake_case like the SDK."""
    if isinstance(value, dict):
        return {_camel(k): camelize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [camelize(v) for v in value]
    return value


CredentialsLoader = Callable[[], tuple[Credentials, str | None]]


def _default_loader() -> tuple[Credentials, str | None]:
    return google.auth.default(scopes=SCOPES)


class GeminiOAuthProvider:
    name = "gemini"
    auth_mode = "oauth (ADC)"

    def __init__(
        self,
        *,
        quota_project: str = "",
        timeout_s: float = 120.0,
        loader: CredentialsLoader = _default_loader,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._timeout = timeout_s
        self._client = client
        self._lock = asyncio.Lock()
        try:
            self._creds: Credentials | None
            self._creds, project = loader()
        except DefaultCredentialsError:
            self._creds, project = None, None
        quota = getattr(self._creds, "quota_project_id", None) if self._creds else None
        self._quota_project = quota_project or quota or project or ""

    @property
    def configured(self) -> bool:
        return self._creds is not None

    @property
    def unconfigured_detail(self) -> str:
        return NOT_SET_UP

    async def _headers(self) -> dict[str, str]:
        if self._creds is None:
            raise ProviderError(self.name, NOT_SET_UP)
        async with self._lock:
            if not self._creds.valid:
                try:
                    request = google.auth.transport.requests.Request()
                    await asyncio.to_thread(self._creds.refresh, request)
                except RefreshError as e:
                    raise ProviderError(
                        self.name, f"OAuth token refresh failed: {e}", status=401
                    ) from e
        headers = {"Authorization": f"Bearer {self._creds.token}"}
        if self._quota_project:
            headers["x-goog-user-project"] = self._quota_project
        return headers

    async def _request(self, method: str, path: str, json: dict[str, Any] | None = None) -> Any:
        headers = await self._headers()
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            resp = await client.request(method, f"{BASE_URL}/{path}", json=json, headers=headers)
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
            raise ProviderError(
                self.name,
                f"HTTP {resp.status_code}: {resp.text[:200]}",
                status=resp.status_code,
                retryable=classify_status(resp.status_code),
            )
        return resp.json()

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
        generation: dict[str, Any] = {"temperature": 0.2}
        if json_mode:
            generation["responseMimeType"] = "application/json"
            if json_schema:
                generation["responseJsonSchema"] = json_schema
        generation.update(camelize(extra or {}))
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": generation,
        }
        data = await self._request("POST", f"models/{model}:generateContent", body)
        candidates = data.get("candidates") or []
        parts = (candidates[0].get("content") or {}).get("parts", []) if candidates else []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        usage = data.get("usageMetadata") or {}
        return ChatResult(
            text=text,
            tokens_in=int(usage.get("promptTokenCount") or 0),
            tokens_out=int(usage.get("candidatesTokenCount") or 0),
        )

    async def embed(
        self,
        *,
        model: str,
        texts: list[str],
        dimensions: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> EmbedResult:
        requests: list[dict[str, Any]] = []
        for text in texts:
            req: dict[str, Any] = {
                "model": f"models/{model}",
                "content": {"parts": [{"text": text}]},
            }
            if dimensions:
                req["outputDimensionality"] = dimensions
            req.update(camelize(extra or {}))
            requests.append(req)
        data = await self._request(
            "POST", f"models/{model}:batchEmbedContents", {"requests": requests}
        )
        vectors = [list(map(float, e.get("values") or [])) for e in data.get("embeddings") or []]
        if len(vectors) != len(texts):
            raise ProviderError(self.name, "embedding count mismatch", retryable=True)
        return EmbedResult(vectors=vectors, model=model)

    async def list_models(self) -> list[str]:
        data = await self._request("GET", "models?pageSize=1000")
        return [str(m.get("name", "")).removeprefix("models/") for m in data.get("models") or []]

    async def test_connection(self) -> ConnectionTest:
        start = time.monotonic()
        try:
            await self._request("GET", "models?pageSize=1")
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
            detail="connected via OAuth",
            latency_ms=int((time.monotonic() - start) * 1000),
        )
