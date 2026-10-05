from __future__ import annotations

from collections.abc import Iterator

import pytest

from apps.api.settings import get_settings


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[pytest.MonkeyPatch]:
    """Set env vars for a test; settings cache is reset before and after."""
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _isolate_settings(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Offline tests never read the developer's real .env keys (live tests do)."""
    if request.node.get_closest_marker("live"):
        get_settings.cache_clear()
        yield
        return
    for name in (
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
        "NVIDIA_API_KEY",
        "YOUTUBE_API_KEY",
        "COURTLISTENER_TOKEN",
        "SEC_USER_AGENT",
    ):
        monkeypatch.setenv(name, "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
