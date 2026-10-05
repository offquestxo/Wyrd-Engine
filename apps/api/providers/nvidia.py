"""NVIDIA build.nvidia.com (OpenAI-compatible). Second opinions and embeddings.

Docs: https://docs.api.nvidia.com/nim/reference/llm-apis and /retrieval-apis
"""

from __future__ import annotations

from typing import Any

from apps.api.providers.openai_compat import OpenAICompatProvider


class NvidiaProvider(OpenAICompatProvider):
    name = "nvidia"
    supports_embeddings = True

    def __init__(
        self, *, probe_model: str = "", probe_extra: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        super().__init__(**kwargs)
        self._probe_model = probe_model
        self._probe_extra = probe_extra or {}

    async def _probe(self) -> None:
        # /v1/models answers without a key on NVIDIA, so it can't validate one.
        # A one-word embedding is the cheapest authenticated call.
        if self._probe_model:
            await self.embed(model=self._probe_model, texts=["ping"], extra=self._probe_extra)
        else:
            await self._request("GET", "/models")
