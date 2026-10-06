"""Phase 7: Notion sync against a fake Notion API (httpx.MockTransport), no network."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlmodel import Session

from apps.api import notion_sync as ns
from apps.api.config import NotionConfig
from apps.api.db.migrate import migrate_path
from apps.api.db.models import Story, StorySource
from apps.api.db.session import make_engine
from apps.api.events import EventBus

DB_ID = "db-123"
DS_ID = "ds-456"


class FakeNotion:
    """Just enough of the Notion API: database → data source → pages."""

    def __init__(self) -> None:
        self.pages: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, str]] = []
        self.headers: list[httpx.Headers] = []
        self.schema = dict(ns.SCHEMA)
        self.fail_next: list[httpx.Response] = []
        self.clock = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)

    def stamp(self) -> str:
        # Notion's last_edited_time has minute precision.
        return self.clock.replace(second=0, microsecond=0).isoformat().replace("+00:00", "Z")

    def edit(self, page_id: str, **props: Any) -> None:
        """Simulate the owner editing a page in Notion."""
        page = self.pages[page_id]
        for name, value in props.items():
            kind = ns.SCHEMA[name]
            if kind == "select":
                page["properties"][name] = {"type": "select", "select": {"name": value}}
            else:
                page["properties"][name] = {
                    "type": kind,
                    kind: [{"type": "text", "text": {"content": value}, "plain_text": value}],
                }
        page["last_edited_time"] = self.stamp()

    def _store(self, props: dict[str, Any]) -> dict[str, Any]:
        return {name: {"type": ns.SCHEMA[name], **value} for name, value in props.items()}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        self.headers.append(request.headers)
        if self.fail_next:
            return self.fail_next.pop(0)
        path = request.url.path.removeprefix("/v1")
        body = json.loads(request.content) if request.content else {}
        if request.method == "GET" and path == f"/databases/{DB_ID}":
            return httpx.Response(200, json={"id": DB_ID, "data_sources": [{"id": DS_ID}]})
        if request.method == "GET" and path == f"/data_sources/{DS_ID}":
            props = {name: {"type": kind} for name, kind in self.schema.items()}
            return httpx.Response(200, json={"id": DS_ID, "properties": props})
        if request.method == "POST" and path == f"/data_sources/{DS_ID}/query":
            return httpx.Response(
                200, json={"results": list(self.pages.values()), "has_more": False}
            )
        if request.method == "POST" and path == "/pages":
            assert body["parent"] == {"type": "data_source_id", "data_source_id": DS_ID}
            pid = str(uuid.uuid4())
            self.pages[pid] = {
                "id": pid,
                "in_trash": False,
                "properties": self._store(body["properties"]),
                "last_edited_time": self.stamp(),
            }
            return httpx.Response(200, json=self.pages[pid])
        if request.method == "PATCH" and path.startswith("/pages/"):
            pid = path.removeprefix("/pages/")
            if pid not in self.pages:
                return httpx.Response(404, json={"code": "object_not_found", "message": "gone"})
            self.pages[pid]["properties"].update(self._store(body["properties"]))
            self.pages[pid]["last_edited_time"] = self.stamp()
            return httpx.Response(200, json=self.pages[pid])
        return httpx.Response(400, json={"message": f"unexpected {request.method} {path}"})


@pytest.fixture
def env(env: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    env.setenv("NOTION_TOKEN", "secret_test_token")
    env.setenv("NOTION_DATABASE_ID", DB_ID)
    migrate_path(tmp_path / "n.db")
    engine = make_engine(tmp_path / "n.db")
    with Session(engine) as s:
        s.add(
            Story(
                slug="circuit-city",
                title="Circuit City",
                status="Inbox",
                series="Tech Graveyard",
                format="Long",
                hook="A retailer fired its best salespeople",
                scores={"total": 8.2, "drama": 9, "twist": 8},
                gap_score=7.5,
                notes="check the 10-K",
            )
        )
        s.add(Story(slug="theranos", title="Theranos", status="Shortlisted"))
        s.commit()
        s.add(StorySource(story_id=1, url="https://www.sec.gov/x", source_type="primary"))
        s.add(StorySource(story_id=1, url="https://en.wikipedia.org/wiki/Circuit_City"))
        s.commit()
    fake = FakeNotion()
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    env.setattr(ns.asyncio, "sleep", fake_sleep)
    bus = EventBus(history=200)
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
    sync = ns.NotionSync(engine, bus, http=http, cfg=NotionConfig(min_interval_s=0.4))
    return {"engine": engine, "fake": fake, "sync": sync, "bus": bus, "sleeps": sleeps}


def story(engine: Any, story_id: int) -> Story:
    with Session(engine) as s:
        row = s.get(Story, story_id)
        assert row is not None
        return row


def touch(engine: Any, story_id: int, **fields: Any) -> None:
    """A local edit (like PATCH /api/stories/{id})."""
    with Session(engine) as s:
        row = s.get(Story, story_id)
        assert row is not None
        for k, v in fields.items():
            setattr(row, k, v)
        row.updated_at = datetime.now(UTC) + timedelta(seconds=1)
        s.add(row)
        s.commit()


async def test_push_creates_pages_with_every_field(env: Any) -> None:
    fake, sync = env["fake"], env["sync"]
    report = await sync.sync()
    assert report.ok and (report.created, report.updated) == (2, 0)
    assert all(h["Notion-Version"] == "2026-03-11" for h in fake.headers)
    assert fake.headers[0]["Authorization"] == "Bearer secret_test_token"
    cc = next(p for p in fake.pages.values() if p["properties"]["Engine ID"]["number"] == 1)
    props = cc["properties"]
    assert ns.plain(props["Title"]) == "Circuit City"
    assert (
        ns.select_name(props["Status"]) == "Inbox"
        and ns.select_name(props["Series"]) == "Tech Graveyard"
    )
    assert ns.plain(props["Hook"]) == "UNVERIFIED LEAD: A retailer fired its best salespeople"
    assert ns.plain(props["Scores"]) == "total 8.2 · drama 9 · twist 8"
    assert props["Gap Score"]["number"] == 7.5
    assert ns.plain(props["Sources"]).startswith("2 sources (1 primary): https://www.sec.gov/x")
    assert props["Updated"]["date"]["start"].startswith(
        story(env["engine"], 1).updated_at.date().isoformat()
    )
    assert story(env["engine"], 1).notion_page_id == cc["id"]
    # Paced: ≥ 0.4 s between requests (≈ 3 requests/s at most).
    assert env["sleeps"] and min(env["sleeps"]) > 0

    fake.calls.clear()
    again = await sync.sync()
    assert (again.created, again.updated, again.unchanged) == (0, 0, 2)
    assert [m for m, _ in fake.calls if m in ("PATCH",)] == []  # nothing re-pushed


async def test_local_change_is_pushed(env: Any) -> None:
    sync, fake, engine = env["sync"], env["fake"], env["engine"]
    await sync.sync()
    touch(engine, 2, status="Researching")
    report = await sync.sync(push_only=True)
    assert (report.created, report.updated) == (0, 1)
    page = fake.pages[story(engine, 2).notion_page_id]
    assert ns.select_name(page["properties"]["Status"]) == "Researching"


async def test_status_changed_in_notion_comes_back(env: Any) -> None:
    sync, fake, engine, bus = env["sync"], env["fake"], env["engine"], env["bus"]
    await sync.sync()
    fake.clock += timedelta(minutes=5)
    fake.edit(story(engine, 1).notion_page_id, Status="Shortlisted", Notes="great for a Short")
    report = await sync.sync()
    row = story(engine, 1)
    assert (row.status, row.notes) == ("Shortlisted", "great for a Short")
    assert report.pulled[0]["to"] == {"status": "Shortlisted", "notes": "great for a Short"}
    assert report.updated == 0  # the pulled story isn't pushed straight back
    events = [e for e in bus.recent() if e.type == "story.changed"]
    assert events[-1].data == {"story_id": 1, "source": "notion"}


async def test_conflict_newest_wins(env: Any) -> None:
    sync, fake, engine = env["sync"], env["fake"], env["engine"]
    await sync.sync()
    page_id = story(engine, 1).notion_page_id
    # Notion edited first, then a newer local edit: local wins and overwrites Notion.
    fake.edit(page_id, Status="Archived")
    touch(engine, 1, status="Scripting")
    report = await sync.sync()
    assert report.conflicts_local_won == 1 and story(engine, 1).status == "Scripting"
    assert ns.select_name(fake.pages[page_id]["properties"]["Status"]) == "Scripting"
    # Local edit first, then a newer Notion edit: Notion wins.
    touch(engine, 1, notes="local note")
    fake.clock = datetime.now(UTC) + timedelta(minutes=10)
    fake.edit(page_id, Notes="notion note")
    await sync.sync()
    assert story(engine, 1).notes == "notion note"


async def test_unknown_status_is_ignored(env: Any) -> None:
    sync, fake, engine = env["sync"], env["fake"], env["engine"]
    await sync.sync()
    fake.clock += timedelta(minutes=5)
    fake.edit(story(engine, 2).notion_page_id, Status="Maybe later")
    report = await sync.sync()
    assert story(engine, 2).status == "Shortlisted"
    assert any("Maybe later" in e for e in report.errors)


async def test_schema_mismatch_is_explained(env: Any) -> None:
    env["fake"].schema["Status"] = "status"
    del env["fake"].schema["Engine ID"]
    report = await env["sync"].sync()
    assert not report.ok and report.created == 0
    assert "“Status” should be select (is status)" in report.errors[0]
    assert "“Engine ID” should be number (missing)" in report.errors[0]


async def test_rate_limit_is_respected(env: Any) -> None:
    fake = env["fake"]
    fake.fail_next = [
        httpx.Response(429, headers={"Retry-After": "3"}, json={"code": "rate_limited"}),
        httpx.Response(502, json={}),
    ]
    report = await env["sync"].sync()
    assert report.ok and report.created == 2
    assert any(s >= 3 for s in env["sleeps"])  # waited at least Retry-After


async def test_deleted_page_is_recreated_and_bad_token_explained(env: Any) -> None:
    sync, fake, engine = env["sync"], env["fake"], env["engine"]
    await sync.sync()
    fake.pages.pop(story(engine, 1).notion_page_id)
    touch(engine, 1, notes="changed")
    report = await sync.sync(push_only=True)
    assert report.created == 1 and story(engine, 1).notion_page_id in fake.pages

    fake.fail_next = [httpx.Response(401, json={"code": "unauthorized", "message": "bad"})]
    sync._data_source = None
    failed = await sync.sync()
    assert not failed.ok and any("NOTION_TOKEN was rejected" in e for e in failed.errors)


async def test_without_token_everything_is_off(env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.settings import get_settings

    monkeypatch.setenv("NOTION_TOKEN", "")
    get_settings.cache_clear()
    sync = env["sync"]
    assert sync.configured() is False and sync.status()["configured"] is False
    report = await sync.sync()
    assert not report.ok and env["fake"].calls == []


def test_api_endpoints_without_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from apps.api import main
    from apps.api.db import session
    from apps.api.settings import get_settings
    from apps.api.system import ClaudeStatus

    monkeypatch.setenv("DB_PATH", str(tmp_path / "api.db"))
    monkeypatch.setenv("NOTION_TOKEN", "")
    monkeypatch.setenv("NOTION_DATABASE_ID", "")
    get_settings.cache_clear()
    session.get_engine.cache_clear()

    async def fake_claude() -> ClaudeStatus:
        return ClaudeStatus(installed=True, logged_in=True, detail="ready")

    monkeypatch.setattr(main, "check_claude_cli", fake_claude)
    with TestClient(main.app) as client:
        status = client.get("/api/notion").json()
        assert status["configured"] is False and status["version"] == "2026-03-11"
        assert client.post("/api/notion/sync").status_code == 409
        assert client.put("/api/notion/auto-sync", json={"auto_sync": True}).json()["auto_sync"]
        assert client.get("/api/health").json()["ok"] is True  # the app works without Notion
    get_settings.cache_clear()
