from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api import main
from apps.api.db import session
from apps.api.system import ClaudeStatus


@pytest.fixture
def client(env: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    env.setenv("DB_PATH", str(tmp_path / "api.db"))
    env.setenv("GROQ_API_KEY", "gsk_supersecretvalue1234")
    session.get_engine.cache_clear()

    async def fake_claude() -> ClaudeStatus:
        return ClaudeStatus(installed=True, logged_in=True, detail="ready")

    env.setattr(main, "check_claude_cli", fake_claude)
    return TestClient(main.app)


def test_health_reports_claude_status(client: TestClient) -> None:
    with client:
        body = client.get("/api/health").json()
    assert body["ok"] is True and body["claude"]["logged_in"] is True


def test_provider_status_masks_keys(client: TestClient) -> None:
    with client:
        rows = {r["provider"]: r for r in client.get("/api/providers").json()}
    assert rows["groq"]["status"] == "set"
    assert rows["groq"]["key_preview"] == "gsk_…1234"
    assert "supersecret" not in str(rows)
    assert rows["gemini"]["status"] == "missing"


def test_unknown_provider_test_is_404(client: TestClient) -> None:
    with client:
        assert client.post("/api/providers/nope/test").status_code == 404
