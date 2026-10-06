"""Provider request shapes against mocked HTTP (no network)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from apps.api.providers.base import ProviderError
from apps.api.providers.gemini_oauth import GeminiOAuthProvider, camelize
from apps.api.providers.mistral import MistralProvider
from apps.api.providers.openrouter import OpenRouterProvider


@respx.mock
async def test_mistral_chat_and_embeddings_shape() -> None:
    chat = respx.post("https://api.mistral.ai/v1/chat/completions").respond(
        json={
            "choices": [{"message": {"content": '{"ok": true}'}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
        }
    )
    emb = respx.post("https://api.mistral.ai/v1/embeddings").respond(
        json={"data": [{"index": 1, "embedding": [0.2]}, {"index": 0, "embedding": [0.1]}]}
    )
    p = MistralProvider(
        base_url="https://api.mistral.ai/v1", api_key="k", api_key_env="MISTRAL_API_KEY"
    )

    result = await p.chat(model="mistral-small-latest", system="s", user="u", json_mode=True)
    body = json.loads(chat.calls[0].request.content)
    assert body["response_format"] == {"type": "json_object"}
    assert chat.calls[0].request.headers["Authorization"] == "Bearer k"
    assert (result.text, result.tokens_in) == ('{"ok": true}', 12)

    vectors = await p.embed(model="mistral-embed", texts=["a", "b"])
    assert vectors.vectors == [[0.1], [0.2]]  # re-ordered by index
    assert "encoding_format" not in json.loads(emb.calls[0].request.content)


@respx.mock
async def test_openrouter_probe_uses_key_endpoint_and_title_header() -> None:
    route = respx.get("https://openrouter.ai/api/v1/key").respond(401, json={"error": "bad key"})
    p = OpenRouterProvider(
        base_url="https://openrouter.ai/api/v1", api_key="k", api_key_env="OPENROUTER_API_KEY"
    )
    result = await p.test_connection()
    assert result.ok is False and "401" in result.detail
    assert route.calls[0].request.headers["X-Title"] == "wyrd.exe story engine"


class FakeCreds:
    def __init__(self) -> None:
        self.valid = False
        self.token: str | None = None
        self.quota_project_id = "adc-project"
        self.refreshes = 0

    def refresh(self, _request: Any) -> None:
        self.refreshes += 1
        self.valid, self.token = True, "ya29.fake"


@respx.mock
async def test_gemini_oauth_sends_bearer_token_and_quota_project() -> None:
    creds = FakeCreds()
    route = respx.post(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"
    ).respond(
        json={
            "candidates": [
                {"content": {"parts": [{"text": "thinking", "thought": True}, {"text": "{}"}]}}
            ],
            "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 1},
        }
    )
    p = GeminiOAuthProvider(loader=lambda: (creds, "proj"))  # type: ignore[arg-type,return-value]
    assert p.configured

    result = await p.chat(
        model="gemini-3.5-flash-lite",
        system="s",
        user="u",
        json_mode=True,
        json_schema={"type": "object"},
        extra={"thinking_config": {"thinking_level": "MINIMAL"}},
    )
    req = route.calls[0].request
    body = json.loads(req.content)
    assert req.headers["Authorization"] == "Bearer ya29.fake"
    assert req.headers["x-goog-user-project"] == "adc-project"
    assert body["generationConfig"]["responseJsonSchema"] == {"type": "object"}
    assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "MINIMAL"}
    assert result.text == "{}" and result.tokens_in == 5  # thought parts dropped
    await p.chat(model="gemini-3.5-flash-lite", system="s", user="u", json_mode=False)
    assert creds.refreshes == 1  # token reused while valid


def test_gemini_oauth_without_adc_is_unconfigured() -> None:
    from google.auth.exceptions import DefaultCredentialsError

    def missing() -> Any:
        raise DefaultCredentialsError("none")

    assert GeminiOAuthProvider(loader=missing).configured is False


@respx.mock
async def test_gemini_oauth_401_is_not_retryable() -> None:
    respx.get(url__startswith="https://generativelanguage.googleapis.com/v1beta/models").mock(
        return_value=httpx.Response(403, text="PERMISSION_DENIED")
    )
    p = GeminiOAuthProvider(loader=lambda: (FakeCreds(), None))  # type: ignore[arg-type,return-value]
    with pytest.raises(ProviderError) as exc:
        await p.list_models()
    assert exc.value.status == 403 and not exc.value.retryable


def test_camelize() -> None:
    assert camelize({"thinking_config": {"thinking_level": "x"}, "a": [{"b_c": 1}]}) == {
        "thinkingConfig": {"thinkingLevel": "x"},
        "a": [{"bC": 1}],
    }


def test_gemini_auth_oauth_takes_priority_over_api_key(env: pytest.MonkeyPatch) -> None:
    from google.auth.exceptions import DefaultCredentialsError

    from apps.api.config import load_providers
    from apps.api.providers import gemini_oauth
    from apps.api.providers.gemini import GeminiProvider
    from apps.api.providers.router import build_providers

    def no_adc(*_a: Any, **_k: Any) -> Any:
        raise DefaultCredentialsError("none")

    env.setattr(gemini_oauth.google.auth, "default", no_adc)
    env.setenv("GEMINI_API_KEY", "AQ.some-key")
    env.setenv("GEMINI_AUTH", "oauth")
    built = build_providers(load_providers())
    assert isinstance(built["gemini"], GeminiOAuthProvider)
    assert built["gemini"].configured is False  # no ADC on this machine → skipped, not API key

    env.setenv("GEMINI_AUTH", "api_key")
    from apps.api.settings import get_settings

    get_settings.cache_clear()
    assert isinstance(build_providers(load_providers())["gemini"], GeminiProvider)


async def test_connection_test_reports_auth_mode_and_oauth_setup_hint() -> None:
    from google.auth.exceptions import DefaultCredentialsError

    from apps.api.config import load_providers
    from apps.api.providers.router import Router

    def missing() -> Any:
        raise DefaultCredentialsError("none")

    router = Router(load_providers(), {"gemini": GeminiOAuthProvider(loader=missing)}, None)
    result = await router.test_connection("gemini")
    assert result.auth == "oauth (ADC)" and not result.ok
    assert "Application Default Credentials" in result.detail
