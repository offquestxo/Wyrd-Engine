"""Mistral (OpenAI-compatible chat + embeddings).

Docs: https://docs.mistral.ai/api/ ; limits per workspace at
https://admin.mistral.ai/plateforme/limits (free tier: 1 req/s, 500K tokens/min, 1B tokens/month).
"""

from __future__ import annotations

from apps.api.providers.openai_compat import OpenAICompatProvider


class MistralProvider(OpenAICompatProvider):
    name = "mistral"
    supports_embeddings = True
    send_encoding_format = False
