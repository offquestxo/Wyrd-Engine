"""Google Gemini via the google-genai SDK. Long documents and analysis.

Docs: https://ai.google.dev/gemini-api/docs (models, structured-output, embeddings)
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from google import genai
from google.genai import errors, types

from apps.api.providers.base import (
    ChatResult,
    ConnectionTest,
    EmbedResult,
    MissingKeyError,
    ProviderError,
    classify_status,
)

# Google-side issue (2026): new "AQ."-format keys from AI Studio are rejected by the Gemini
# API with 401 ACCESS_TOKEN_TYPE_UNSUPPORTED, even via plain curl. Standard "AIza" keys work.
AQ_KEY_HINT = (
    "HTTP 401: this GEMINI_API_KEY is a new 'AQ.'-format key, which the Gemini API currently "
    "rejects (known Google issue). Create a standard 'AIza' key in Google Cloud Console "
    "(APIs & Services > Credentials > Create credentials > API key, restricted to the "
    "Generative Language API) in your AI Studio project, and put it in .env."
)


class GeminiProvider:
    name = "gemini"

    def __init__(self, *, api_key: str, api_key_env: str = "GEMINI_API_KEY") -> None:
        self._api_key = api_key
        self._api_key_env = api_key_env
        # The SDK's async transport is bound to the event loop it was created on, so keep
        # one client per loop (the app has one; tests and CLIs create several).
        self._clients: dict[int, genai.Client] = {}

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> genai.Client:
        if not self._api_key:
            raise MissingKeyError(self.name, self._api_key_env)
        try:
            loop_id = id(asyncio.get_running_loop())
        except RuntimeError:
            loop_id = 0
        if loop_id not in self._clients:
            self._clients = {loop_id: genai.Client(api_key=self._api_key)}
        return self._clients[loop_id]

    def _wrap(self, e: Exception) -> ProviderError:
        if isinstance(e, ProviderError):
            return e
        if isinstance(e, errors.APIError):
            code = int(e.code or 0)
            if code == 401 and self._api_key.startswith("AQ."):
                return ProviderError(self.name, AQ_KEY_HINT, status=code, retryable=False)
            return ProviderError(
                self.name,
                f"HTTP {code}: {str(e.message or '')[:200]}",
                status=code,
                retryable=classify_status(code),
            )
        return ProviderError(self.name, f"{type(e).__name__}: {str(e)[:200]}", retryable=True)

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
        config: dict[str, Any] = {
            "system_instruction": system,
            "temperature": 0.2,
            # no tools are passed; also silences the SDK's AFC warning
            "automatic_function_calling": {"disable": True},
        }
        if json_mode:
            config["response_mime_type"] = "application/json"
            if json_schema:
                config["response_json_schema"] = json_schema
        config.update(extra or {})
        try:
            resp = await self._get_client().aio.models.generate_content(
                model=model, contents=user, config=types.GenerateContentConfig(**config)
            )
        except Exception as e:
            raise self._wrap(e) from e
        usage = resp.usage_metadata
        return ChatResult(
            text=resp.text or "",
            tokens_in=int((usage.prompt_token_count if usage else 0) or 0),
            tokens_out=int((usage.candidates_token_count if usage else 0) or 0),
        )

    async def embed(
        self,
        *,
        model: str,
        texts: list[str],
        dimensions: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> EmbedResult:
        config: dict[str, Any] = dict(extra or {})
        if dimensions:
            config["output_dimensionality"] = dimensions
        try:
            resp = await self._get_client().aio.models.embed_content(
                model=model,
                contents=list(texts),
                config=types.EmbedContentConfig(**config) if config else None,
            )
        except Exception as e:
            raise self._wrap(e) from e
        vectors = [list(map(float, emb.values or [])) for emb in (resp.embeddings or [])]
        if len(vectors) != len(texts) and len(texts) > 1:
            # Multimodal embedding models may merge a list into one vector; go one by one.
            vectors = []
            for text in texts:
                single = await self.embed(
                    model=model, texts=[text], dimensions=dimensions, extra=extra
                )
                vectors.extend(single.vectors)
        if len(vectors) != len(texts):
            raise ProviderError(self.name, "embedding count mismatch", retryable=True)
        return EmbedResult(vectors=vectors, model=model)

    async def list_models(self) -> list[str]:
        try:
            pager = await self._get_client().aio.models.list(config={"page_size": 200})
            return [(m.name or "").removeprefix("models/") async for m in pager]
        except Exception as e:
            raise self._wrap(e) from e

    async def test_connection(self) -> ConnectionTest:
        start = time.monotonic()
        try:
            pager = await self._get_client().aio.models.list(config={"page_size": 1})
            async for _ in pager:
                break
        except Exception as e:
            return ConnectionTest(
                provider=self.name,
                ok=False,
                detail=str(self._wrap(e)),
                latency_ms=int((time.monotonic() - start) * 1000),
            )
        return ConnectionTest(
            provider=self.name,
            ok=True,
            detail="connected",
            latency_ms=int((time.monotonic() - start) * 1000),
        )
