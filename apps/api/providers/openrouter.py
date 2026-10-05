"""OpenRouter (OpenAI-compatible router; free models end in ":free").

Docs: https://openrouter.ai/docs ; free models: 20 req/min and 50 req/day
(1,000/day after buying $10 of credits). GET /api/v1/key reports remaining quota.
"""

from __future__ import annotations

from typing import Any

from apps.api.providers.openai_compat import OpenAICompatProvider


class OpenRouterProvider(OpenAICompatProvider):
    name = "openrouter"
    supports_embeddings = False

    def _headers(self) -> dict[str, str]:
        # Optional attribution headers OpenRouter uses for app rankings.
        return {**super()._headers(), "X-Title": "wyrd.exe story engine"}

    async def _probe(self) -> None:
        # /models is public; /key needs a valid key, so it actually tests the credential.
        await self._request("GET", "/key")

    async def key_info(self) -> dict[str, Any]:
        data = await self._request("GET", "/key")
        return dict(data.get("data") or {})
