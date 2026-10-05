"""Groq (OpenAI-compatible). Fast, high-volume tasks. Docs: https://console.groq.com/docs"""

from __future__ import annotations

from apps.api.providers.openai_compat import OpenAICompatProvider


class GroqProvider(OpenAICompatProvider):
    name = "groq"
    supports_embeddings = False
