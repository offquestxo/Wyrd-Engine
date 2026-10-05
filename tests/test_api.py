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


def test_keys_endpoint_never_returns_full_secrets(client: TestClient) -> None:
    with client:
        rows = {r["env"]: r for r in client.get("/api/keys").json()}
    assert rows["GROQ_API_KEY"]["status"] == "set"
    assert rows["GROQ_API_KEY"]["preview"] == "gsk_…1234"
    assert rows["GEMINI_API_KEY"]["status"] == "missing"
    assert rows["SEC_USER_AGENT"]["preview"] == ""
    assert "supersecret" not in str(rows)


def test_failed_connection_test_marks_key_failing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.providers.base import ConnectionTest
    from apps.api.providers.router import Router

    async def rejected(self: Router, name: str) -> ConnectionTest:
        return ConnectionTest(provider=name, ok=False, detail="HTTP 401")

    monkeypatch.setattr(Router, "test_connection", rejected)
    with client:
        assert client.post("/api/providers/groq/test").json()["ok"] is False
        rows = {r["env"]: r for r in client.get("/api/keys").json()}
    assert rows["GROQ_API_KEY"]["status"] == "failing"
    assert rows["GROQ_API_KEY"]["last_test"]["ok"] is False


def test_agents_auto_approve_defaults_off_and_toggles(client: TestClient) -> None:
    with client:
        agents = {a["name"]: a for a in client.get("/api/agents").json()}
        assert all(not a["auto_approve"] for a in agents.values())
        assert agents["factcheck"]["available"] is False
        updated = client.put("/api/agents/scout/auto-approve", json={"auto_approve": True})
        assert updated.json()["auto_approve"] is True
        agents = {a["name"]: a for a in client.get("/api/agents").json()}
        assert agents["scout"]["auto_approve"] is True
        assert (
            client.put(
                "/api/agents/factcheck/auto-approve", json={"auto_approve": True}
            ).status_code
            == 404
        )


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import shutil

    from apps.api import config_files
    from apps.api.settings import CONFIG_DIR

    target = tmp_path / "config"
    shutil.copytree(CONFIG_DIR, target)
    monkeypatch.setattr(config_files, "CONFIG_DIR", target)
    return target


def test_config_read_and_validated_write(client: TestClient, config_dir: Path) -> None:
    with client:
        current = client.get("/api/config/channels").json()
        assert "Company Man" in current["raw"]

        bad = client.put("/api/config/channels", json={"raw": "channels:\n  - {handle: nope}\n"})
        assert bad.status_code == 422
        assert "Company Man" in (config_dir / "channels.yaml").read_text()  # untouched

        new_raw = current["raw"] + '  - { handle: "@Newchannel", name: "New Channel" }\n'
        ok = client.put("/api/config/channels", json={"raw": new_raw})
        assert ok.status_code == 200
        assert (
            "# Competitor channels" in (config_dir / "channels.yaml").read_text()
        )  # comments kept
        assert client.get("/api/config/nope").status_code == 404


def test_providers_config_rejects_routes_to_unknown_models(
    client: TestClient, config_dir: Path
) -> None:
    raw = (
        (config_dir / "providers.yaml")
        .read_text()
        .replace("{ provider: nvidia, model: embed }", "{ provider: nvidia, model: missing }")
    )
    with client:
        resp = client.put("/api/config/providers", json={"raw": raw})
    assert resp.status_code == 422 and "missing" in resp.json()["detail"]


async def test_event_bus_replays_history_and_streams() -> None:
    from apps.api.events import EventBus

    bus = EventBus(history=5)
    bus.publish("system", message="one")
    stream = bus.subscribe()
    first = await stream.__anext__()
    assert first.data == {"message": "one"}
    bus.publish("config.saved", file="config/channels.yaml")
    second = await stream.__anext__()
    assert second.type == "config.saved" and second.id == 2
    assert [e.id for e in bus.recent(after_id=1)] == [2]
    await stream.aclose()
    assert bus.subscriber_count == 0
