"""Optional Notion mirror of the stories table (SPEC §8).

SQLite is the source of truth. **Push** writes Title, Status, Series, Format, Hook, Scores,
Gap Score, Sources, Updated (plus Notes and an `Engine ID` used to map pages back to stories).
**Pull** brings back only Status and Notes. With no NOTION_TOKEN/NOTION_DATABASE_ID everything
here is disabled and the app is unaffected.

Notion API (checked 2026-10-06): `Notion-Version: 2026-03-11`. A database has data sources;
pages are created under `{"parent": {"type": "data_source_id", ...}}` and listed with
`POST /v1/data_sources/{id}/query`. Rate limit ≈ 3 requests/s per connection (non-Enterprise);
429 responses carry `Retry-After`. Rich text values are capped at 2000 characters.

**Conflicts:** Notion's `last_edited_time` only has minute precision, so changes are detected
by value, not just by time. After a push, Notion holds exactly what we pushed, so a Status/Notes
value that differs from the story means someone edited it in Notion. If the story also changed
locally since the last sync (`updated_at > notion_synced_at`), the newer timestamp wins.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import Engine
from sqlmodel import Session, col, select

from apps.api.config import NotionConfig, load_engine
from apps.api.db.models import Story, StorySource, StoryStatus, utcnow
from apps.api.events import EventBus
from apps.api.settings import get_settings
from apps.api.settings_store import get_setting, set_setting

log = logging.getLogger(__name__)

API = "https://api.notion.com/v1"
TEXT_LIMIT = 2000
UNVERIFIED = "UNVERIFIED LEAD: "
AUTO_SYNC_KEY = "notion.auto_sync"
LAST_SYNC_KEY = "notion.last_sync"
STATUSES = {s.value for s in StoryStatus}

# Property name → Notion type the database must have.
SCHEMA: dict[str, str] = {
    "Title": "title",
    "Status": "select",
    "Series": "select",
    "Format": "select",
    "Hook": "rich_text",
    "Scores": "rich_text",
    "Gap Score": "number",
    "Sources": "rich_text",
    "Updated": "date",
    "Notes": "rich_text",
    "Engine ID": "number",
}


class NotionError(RuntimeError):
    def __init__(self, status: int, message: str, code: str | None = None) -> None:
        super().__init__(f"Notion {status}{f' {code}' if code else ''}: {message}")
        self.status, self.code = status, code


# ---------------------------------------------------------------------------- client
class NotionClient:
    """Minimal REST client: version header, ≤ N requests/s, 429/5xx retries with backoff."""

    def __init__(
        self,
        token: str,
        cfg: NotionConfig,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.cfg = cfg
        self._http = http or httpx.AsyncClient(timeout=30.0)
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": cfg.version,
            "Content-Type": "application/json",
        }
        self._lock = asyncio.Lock()
        self._last = 0.0
        self.requests = 0

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _pace(self) -> None:
        async with self._lock:
            gap = self.cfg.min_interval_s - (time.monotonic() - self._last)
            if gap > 0:
                await asyncio.sleep(gap)
            self._last = time.monotonic()

    async def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        for attempt in range(self.cfg.max_retries + 1):
            await self._pace()
            self.requests += 1
            try:
                resp = await self._http.request(
                    method, f"{API}{path}", headers=self._headers, json=body
                )
            except httpx.HTTPError as e:
                if attempt >= self.cfg.max_retries:
                    raise NotionError(0, f"network error: {type(e).__name__}") from e
                await asyncio.sleep(min(30.0, 2**attempt))
                continue
            if resp.status_code < 400:
                return resp.json()
            data: dict[str, Any] = {}
            with contextlib.suppress(ValueError):
                data = resp.json()
            retryable = resp.status_code == 429 or resp.status_code >= 500
            if not retryable or attempt >= self.cfg.max_retries:
                raise NotionError(
                    resp.status_code, str(data.get("message", resp.text[:200])), data.get("code")
                )
            retry_after = resp.headers.get("Retry-After")
            delay = float(retry_after) if retry_after else 2**attempt
            # Exponential backoff with jitter on repeated 429s (Notion's guidance).
            delay = min(60.0, max(delay, 2**attempt) + random.uniform(0, 0.5))
            log.info("Notion %s on %s %s; retrying in %.1fs", resp.status_code, method, path, delay)
            await asyncio.sleep(delay)
        raise NotionError(0, "retries exhausted")  # pragma: no cover


# ---------------------------------------------------------------------------- mapping
def _text(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    return [{"type": "text", "text": {"content": value[:TEXT_LIMIT]}}]


def plain(prop: dict[str, Any] | None) -> str:
    if not prop:
        return ""
    kind = prop.get("type", "")
    parts = prop.get(kind) or []
    if kind in ("rich_text", "title"):
        return "".join(p.get("plain_text") or p.get("text", {}).get("content", "") for p in parts)
    return ""


def select_name(prop: dict[str, Any] | None) -> str | None:
    value = (prop or {}).get("select")
    return value.get("name") if isinstance(value, dict) else None


def hook_text(story: Story) -> str | None:
    # Scout hooks are LLM-written leads; facts only come from dossiers (same rule as the UI badge).
    return f"{UNVERIFIED}{story.hook}" if story.hook else None


SCORE_ORDER = ("drama", "twist", "relatability", "visual_potential", "hook_number", "freshness")


def scores_text(scores: dict[str, Any] | None) -> str | None:
    if not scores:
        return None
    parts = [f"total {scores['total']}"] if scores.get("total") is not None else []
    parts += [
        f"{k.replace('_', ' ')} {scores[k]}" for k in SCORE_ORDER if scores.get(k) is not None
    ]
    return " · ".join(parts) or None


def sources_text(sources: list[StorySource]) -> str | None:
    if not sources:
        return None
    primary = sum(1 for s in sources if s.source_type == "primary")
    head = f"{len(sources)} sources ({primary} primary): "
    return (head + " · ".join(s.url for s in sources))[:TEXT_LIMIT]


def pushed_notes(story: Story) -> str:
    """Notes exactly as they land in Notion (truncated), for change detection."""
    return (story.notes or "")[:TEXT_LIMIT]


def page_properties(story: Story, sources: list[StorySource]) -> dict[str, Any]:
    def select(value: str | None) -> dict[str, Any]:
        return {"select": {"name": value} if value else None}

    return {
        "Title": {"title": _text(story.title)},
        "Status": select(story.status),
        "Series": select(story.series),
        "Format": select(story.format),
        "Hook": {"rich_text": _text(hook_text(story))},
        "Scores": {"rich_text": _text(scores_text(story.scores))},
        "Gap Score": {"number": story.gap_score},
        "Sources": {"rich_text": _text(sources_text(sources))},
        "Updated": {"date": {"start": story.updated_at.isoformat()}},
        "Notes": {"rich_text": _text(story.notes)},
        "Engine ID": {"number": story.id},
    }


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------- service
class SyncReport(BaseModel):
    ok: bool = True
    mode: str = "full"
    started_at: str
    finished_at: str | None = None
    pulled: list[dict[str, Any]] = Field(default_factory=list)  # story changes from Notion
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    conflicts_local_won: int = 0
    ignored_pages: int = 0  # pages without an Engine ID (added by hand in Notion)
    requests: int = 0
    errors: list[str] = Field(default_factory=list)


class NotionSync:
    def __init__(
        self,
        engine: Engine,
        bus: EventBus,
        http: httpx.AsyncClient | None = None,
        cfg: NotionConfig | None = None,
    ) -> None:
        self.engine = engine
        self.bus = bus
        self._http = http
        self._cfg = cfg
        self._lock = asyncio.Lock()
        self._data_source: tuple[str, str] | None = None  # (database_id, data_source_id)
        self._watch: asyncio.Task[None] | None = None
        self._pending: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------ config/status
    @property
    def cfg(self) -> NotionConfig:
        return self._cfg or load_engine().notion

    @staticmethod
    def credentials() -> tuple[str, str]:
        s = get_settings()
        return s.notion_token.strip().strip('"'), s.notion_database_id.strip().strip('"')

    def configured(self) -> bool:
        token, database = self.credentials()
        return bool(token and database)

    def auto_sync(self) -> bool:
        return bool(get_setting(self.engine, AUTO_SYNC_KEY, False))

    def set_auto_sync(self, on: bool) -> None:
        set_setting(self.engine, AUTO_SYNC_KEY, on)

    def status(self) -> dict[str, Any]:
        token, database = self.credentials()
        with Session(self.engine) as s:
            stories = s.exec(select(Story)).all()
        return {
            "configured": bool(token and database),
            "token_set": bool(token),
            "database_set": bool(database),
            "auto_sync": self.auto_sync(),
            "syncing": self._lock.locked(),
            "stories": len(stories),
            "linked": sum(1 for st in stories if st.notion_page_id),
            "pending": sum(
                1
                for st in stories
                if st.notion_synced_at is None or st.updated_at > st.notion_synced_at
            ),
            "last_sync": get_setting(self.engine, LAST_SYNC_KEY),
            "version": self.cfg.version,
        }

    # ------------------------------------------------------------------ sync
    async def sync(self, push_only: bool = False) -> SyncReport:
        report = SyncReport(
            mode="push" if push_only else "full", started_at=datetime.now(UTC).isoformat()
        )
        token, database = self.credentials()
        if not (token and database):
            report.ok = False
            report.errors.append("Notion isn't configured: set NOTION_TOKEN and NOTION_DATABASE_ID")
            return report
        async with self._lock:
            self.bus.publish("notion.sync", status="running", mode=report.mode)
            client = NotionClient(token, self.cfg, self._http)
            try:
                ds = await self._resolve(client, database)
                if not push_only:
                    await self._pull(client, ds, report)
                await self._push(client, ds, report)
            except NotionError as e:
                report.ok = False
                report.errors.append(str(e))
                if e.status in (401, 403, 404):
                    self._data_source = None
                    report.errors.append(_hint(e))
            finally:
                report.requests = client.requests
                if self._http is None:
                    await client.aclose()
            report.finished_at = datetime.now(UTC).isoformat()
            set_setting(
                self.engine,
                LAST_SYNC_KEY,
                report.model_dump(exclude={"pulled"}) | {"pulled": report.pulled[:20]},
            )
            self.bus.publish(
                "notion.sync",
                status="done" if report.ok else "failed",
                mode=report.mode,
                created=report.created,
                updated=report.updated,
                pulled=len(report.pulled),
                errors=report.errors[:3],
            )
            return report

    async def _resolve(self, client: NotionClient, database: str) -> str:
        """Data source id of the configured database, after checking its properties."""
        if self._data_source and self._data_source[0] == database:
            return self._data_source[1]
        db = await client.request("GET", f"/databases/{database}")
        sources = db.get("data_sources") or []
        if not sources:
            raise NotionError(400, "the database has no data sources")
        ds_id = sources[0]["id"]
        ds = await client.request("GET", f"/data_sources/{ds_id}")
        props = {name: p.get("type") for name, p in (ds.get("properties") or {}).items()}
        problems = [
            f"“{name}” should be {kind}"
            + (f" (is {props[name]})" if name in props else " (missing)")
            for name, kind in SCHEMA.items()
            if props.get(name) != kind
        ]
        if problems:
            raise NotionError(400, "database properties don't match: " + "; ".join(problems))
        self._data_source = (database, ds_id)
        return ds_id

    async def _pages(self, client: NotionClient, ds: str) -> list[dict[str, Any]]:
        pages: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            body: dict[str, Any] = {"page_size": 100}
            if cursor:
                body["start_cursor"] = cursor
            data = await client.request("POST", f"/data_sources/{ds}/query", body)
            pages += data.get("results") or []
            if not data.get("has_more"):
                return pages
            cursor = data.get("next_cursor")

    async def _pull(self, client: NotionClient, ds: str, report: SyncReport) -> None:
        pages = await self._pages(client, ds)
        changed: list[int] = []
        with Session(self.engine) as s:
            stories = {st.id: st for st in s.exec(select(Story)).all()}
            for page in pages:
                if page.get("in_trash"):
                    continue
                props = page.get("properties") or {}
                engine_id = (props.get("Engine ID") or {}).get("number")
                story = stories.get(int(engine_id)) if engine_id is not None else None
                if story is None:
                    report.ignored_pages += 1
                    continue
                if story.notion_page_id is None:
                    story.notion_page_id = page["id"]
                status = select_name(props.get("Status"))
                notes = plain(props.get("Notes"))
                fields: dict[str, Any] = {}
                if status and status != story.status:
                    if status in STATUSES:
                        fields["status"] = status
                    else:
                        report.errors.append(
                            f"story #{story.id}: Notion status “{status}” isn't a story "
                            "status; ignored"
                        )
                if notes != pushed_notes(story):
                    fields["notes"] = notes or None
                if not fields:
                    s.add(story)
                    continue
                edited = parse_time(page.get("last_edited_time")) or utcnow()
                local_changed = (
                    story.notion_synced_at is None or story.updated_at > story.notion_synced_at
                )
                if local_changed and story.updated_at >= edited:
                    report.conflicts_local_won += 1  # the push below overwrites Notion
                    continue
                before = {k: getattr(story, k) for k in fields}
                for k, v in fields.items():
                    setattr(story, k, v)
                now = utcnow()
                story.updated_at = now
                story.notion_synced_at = now  # Notion already holds these values
                s.add(story)
                assert story.id is not None
                changed.append(story.id)
                report.pulled.append(
                    {"story_id": story.id, "title": story.title, "from": before, "to": fields}
                )
            s.commit()
        for story_id in changed:
            self.bus.publish("story.changed", story_id=story_id, source="notion")

    async def _push(self, client: NotionClient, ds: str, report: SyncReport) -> None:
        with Session(self.engine) as s:
            stories = s.exec(select(Story).order_by(col(Story.id))).all()
            todo = [
                st
                for st in stories
                if st.notion_page_id is None
                or st.notion_synced_at is None
                or st.updated_at > st.notion_synced_at
            ]
            report.unchanged = len(stories) - len(todo)
            sources = {
                st.id: list(s.exec(select(StorySource).where(StorySource.story_id == st.id)).all())
                for st in todo
            }
        for story in todo:
            props = page_properties(story, sources.get(story.id, []))
            try:
                if story.notion_page_id:
                    try:
                        await client.request(
                            "PATCH", f"/pages/{story.notion_page_id}", {"properties": props}
                        )
                        report.updated += 1
                        page_id = story.notion_page_id
                    except NotionError as e:
                        if e.status != 404:
                            raise
                        page_id = None  # deleted in Notion: recreate below
                else:
                    page_id = None
                if page_id is None:
                    page = await client.request(
                        "POST",
                        "/pages",
                        {
                            "parent": {"type": "data_source_id", "data_source_id": ds},
                            "properties": props,
                        },
                    )
                    page_id = page["id"]
                    report.created += 1
            except NotionError as e:
                if e.status in (401, 403):
                    raise
                report.ok = False
                report.errors.append(f"story #{story.id}: {e}")
                continue
            with Session(self.engine) as s:
                row = s.get(Story, story.id)
                if row is not None:
                    row.notion_page_id = page_id
                    # Only mark synced if nothing changed locally while we were pushing.
                    row.notion_synced_at = (
                        max(utcnow(), row.updated_at)
                        if row.updated_at == story.updated_at
                        else row.notion_synced_at
                    )
                    s.add(row)
                    s.commit()

    # ------------------------------------------------------------------ auto-sync
    def start(self) -> None:
        if self._watch is None:
            self._watch = asyncio.create_task(self._watcher(), name="notion-auto-sync")

    async def stop(self) -> None:
        for task in (self._watch, self._pending):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(t for t in (self._watch, self._pending) if t is not None), return_exceptions=True
        )
        self._watch = self._pending = None

    async def _watcher(self) -> None:
        """While auto-sync is on: push shortly after story changes, and pull periodically."""
        last_full = time.monotonic()
        async for event in _merge(self.bus, self.cfg.pull_interval_min * 60):
            if not (self.auto_sync() and self.configured()):
                continue
            if event is None:  # periodic tick
                if time.monotonic() - last_full >= self.cfg.pull_interval_min * 60:
                    last_full = time.monotonic()
                    await self._safe_sync(push_only=False)
                continue
            idle = self._pending is None or self._pending.done()
            if event.type == "story.changed" and event.data.get("source") != "notion" and idle:
                self._pending = asyncio.create_task(self._debounced_push())

    async def _debounced_push(self) -> None:
        await asyncio.sleep(self.cfg.push_debounce_s)
        await self._safe_sync(push_only=True)

    async def _safe_sync(self, push_only: bool) -> None:
        try:
            await self.sync(push_only=push_only)
        except Exception:  # auto-sync must never take the app down
            log.exception("Notion auto-sync failed")


async def _merge(bus: EventBus, tick_s: float) -> Any:
    """Bus events, plus a None every tick_s seconds."""
    queue: asyncio.Queue[Any] = asyncio.Queue()

    async def forward() -> None:
        async for event in bus.subscribe(after_id=bus.recent()[-1].id if bus.recent() else 0):
            await queue.put(event)

    async def ticks() -> None:
        while True:
            await asyncio.sleep(min(tick_s, 60.0))
            await queue.put(None)

    tasks = [asyncio.create_task(forward()), asyncio.create_task(ticks())]
    try:
        while True:
            yield await queue.get()
    finally:
        for task in tasks:
            task.cancel()


def _hint(e: NotionError) -> str:
    if e.status == 401:
        return (
            "NOTION_TOKEN was rejected: create an internal integration token and click Reload .env."
        )
    if e.status in (403, 404):
        return (
            "The integration can't see the database: in Notion open the database → ••• → "
            "Connections → add your integration, and check NOTION_DATABASE_ID."
        )
    return ""
