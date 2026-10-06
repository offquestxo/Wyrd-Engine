"""Mistral (OpenAI-compatible chat + embeddings).

Docs: https://docs.mistral.ai/api/ ; limits per workspace at
https://admin.mistral.ai/plateforme/limits (free tier: 1 req/s, 500K tokens/min, 1B tokens/month).
"""

from __future__ import annotations

from typing import Any

from apps.api.providers.openai_compat import OpenAICompatProvider


class MistralProvider(OpenAICompatProvider):
    name = "mistral"
    supports_embeddings = True
    send_encoding_format = False

    def __init__(self, *, probe_model: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._probe_model = probe_model

    async def _probe(self) -> None:
        # /models works even when the workspace has no chat quota (limit 0), so a 1-token
        # chat call is the honest test.
        if not self._probe_model:
            await self._request("GET", "/models")
            return
        await self._request(
            "POST",
            "/chat/completions",
            {
                "model": self._probe_model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 1,
            },
        )
