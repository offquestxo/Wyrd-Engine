"""Google Gemini via the google-genai SDK. Long documents and analysis.

Docs: https://ai.google.dev/gemini-api/docs (models, structured-output, embeddings)
"""

from __future__ import annotations

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


class GeminiProvider:
    name = "gemini"

    def __init__(self, *, api_key: str, api_key_env: str = "GEMINI_API_KEY") -> None:
        self._api_key = api_key
        self._api_key_env = api_key_env
        self._client: genai.Client | None = None

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _get_client(self) -> genai.Client:
        if not self._api_key:
            raise MissingKeyError(self.name, self._api_key_env)
        if self._client is None:
            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def _wrap(self, e: Exception) -> ProviderError:
        if isinstance(e, ProviderError):
            return e
        if isinstance(e, errors.APIError):
            code = int(e.code or 0)
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
        config: dict[str, Any] = {"system_instruction": system, "temperature": 0.2}
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
