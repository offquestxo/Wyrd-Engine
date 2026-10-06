"""FastAPI app. Run with `make dev` (binds 127.0.0.1:8000 only)."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel
from sqlmodel import Session, col, select

from apps.api import mcp_server, memory, outliers, sources, stories
from apps.api.agents.registry import AGENTS
from apps.api.chat import ChatError, ChatService
from apps.api.config import load_engine, load_providers
from apps.api.config_files import ConfigError, ConfigFile, read_config, write_config
from apps.api.db.models import AgentRun, RunLog
from apps.api.db.session import get_engine
from apps.api.events import bus
from apps.api.jobs import JobRunner
from apps.api.plans import PlanError, PlanIn, PlanService
from apps.api.providers.base import ConnectionTest
from apps.api.providers.router import gemini_uses_oauth, get_router
from apps.api.research import dossier as dossier_mod
from apps.api.settings import get_settings, mask_secret
from apps.api.settings_store import auto_approve_key, get_setting, set_setting
from apps.api.sources import youtube
from apps.api.system import ClaudeStatus, check_claude_cli
from apps.api.usage_report import CLAUDE_CAP_KEY, build_report, claude_soft_cap

state: dict[str, Any] = {"tests": {}}

# Every secret/identity the app reads from .env, in display order.
KEYS: list[dict[str, Any]] = [
    {"env": "GROQ_API_KEY", "provider": "groq", "purpose": "Fast scoring, @mention parsing"},
    {"env": "GEMINI_API_KEY", "provider": "gemini", "purpose": "Long documents, outlier analysis"},
    {"env": "NVIDIA_API_KEY", "provider": "nvidia", "purpose": "Second opinions, embeddings"},
    {
        "env": "MISTRAL_API_KEY",
        "provider": "mistral",
        "purpose": "Scoring, long documents, outliers",
    },
    {"env": "OPENROUTER_API_KEY", "provider": "openrouter", "purpose": "Free-model fallback"},
    {"env": "YOUTUBE_API_KEY", "provider": "youtube", "purpose": "@outlier stats, gap finder"},
    {"env": "COURTLISTENER_TOKEN", "provider": None, "purpose": "Court records (optional)"},
    {"env": "NOTION_TOKEN", "provider": None, "purpose": "Notion sync (optional, Phase 7)"},
    {"env": "NOTION_DATABASE_ID", "provider": None, "purpose": "Notion sync target"},
    {"env": "SEC_USER_AGENT", "provider": None, "purpose": "Required contact for SEC EDGAR"},
]


CLAUDE_CHECK_TTL_S = 60.0
mcp_apps = {group: server.http_app(path="/") for group, server in mcp_server.SERVERS.items()}


async def cached_claude_status() -> ClaudeStatus:
    """Claude CLI status, re-checked at most once a minute (and on /api/system/claude)."""
    checked = state.get("claude_checked_at", 0.0)
    if state.get("claude") is None or time.monotonic() - checked > CLAUDE_CHECK_TTL_S:
        state["claude"] = await check_claude_cli()
        state["claude_checked_at"] = time.monotonic()
    status: ClaudeStatus = state["claude"]
    return status


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    engine = get_engine()  # creates / migrates data/wyrd.db
    state["claude"] = None
    await cached_claude_status()
    jobs_cfg = load_engine().jobs
    runner = JobRunner(
        engine,
        bus,
        max_concurrent=jobs_cfg.max_concurrent_runs,
        poll_interval_s=jobs_cfg.poll_interval_s,
    )
    state["runner"] = runner
    plans = PlanService(engine, bus, runner)
    state["plans"] = plans
    state["chats"] = ChatService(
        engine, bus, plans, load_engine().orchestrator, cached_claude_status
    )
    mcp_server.bind(plans)
    await runner.start()
    backfill = asyncio.create_task(memory.backfill(engine), name="memory-backfill")
    try:
        async with contextlib.AsyncExitStack() as stack:
            for mcp_app in mcp_apps.values():
                await stack.enter_async_context(mcp_app.lifespan(_app))
            yield
    finally:
        backfill.cancel()
        await state["chats"].stop()
        await runner.stop()
        mcp_server.bind(None)
        for key in ("runner", "plans", "chats"):
            state.pop(key, None)


app = FastAPI(title="wyrd.exe story engine", version="0.1.0", lifespan=lifespan)
# MCP for Claude sessions (/mcp chat, /mcp-research @researcher). Not under /api, so the web
# proxy never exposes them.
for _group, _mcp_app in mcp_apps.items():
    app.mount(mcp_server.MOUNTS[_group], mcp_server.TokenGuard(_mcp_app))
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------- system
@app.get("/api/health")
async def health() -> dict[str, Any]:
    claude: ClaudeStatus | None = state.get("claude")
    return {"ok": True, "claude": claude.model_dump() if claude else None}


@app.get("/api/system/claude")
async def claude_status() -> ClaudeStatus:
    state["claude"] = None  # force a fresh check
    return await cached_claude_status()


@app.post("/api/system/reload")
async def reload_settings() -> dict[str, bool]:
    """Re-read .env and config files without restarting (after adding or changing keys)."""
    get_settings.cache_clear()
    get_router.cache_clear()
    sources._http.reset_pacer()
    state["tests"] = {}
    bus.publish("system", message="Reloaded .env and config")
    return {"ok": True}


@app.get("/api/events", response_class=EventSourceResponse)
async def events(
    last_event_id: int | None = Header(default=None),
) -> AsyncIterator[ServerSentEvent]:
    """Live event stream (SSE). Reconnecting clients resume after Last-Event-ID."""
    async for event in bus.subscribe(after_id=last_event_id or 0):
        yield ServerSentEvent(
            id=str(event.id), event=event.type, data=event.model_dump(mode="json")
        )


# ---------------------------------------------------------------------------- keys
def _key_status(env: str, value: str, provider: str | None) -> str:
    if env == "SEC_USER_AGENT":
        return "set" if "@" in value and "your@email.com" not in value else "missing"
    if not value:
        return "missing"
    last: ConnectionTest | None = state["tests"].get(provider) if provider else None
    blocked = (
        provider is not None
        and provider in get_router().providers
        and get_router().auth_blocked(provider)
    )
    if blocked or (last is not None and not last.ok):
        return "failing"
    return "set"


def _gemini_oauth_status(item: dict[str, Any]) -> dict[str, Any]:
    """In OAuth mode the Gemini row describes the ADC login, not an API key."""
    router = get_router()
    provider = router.providers.get("gemini")
    last: ConnectionTest | None = state["tests"].get("gemini")
    configured = provider is not None and provider.configured
    error = router.auth_error("gemini")
    if not configured:
        status, note = "missing", getattr(provider, "unconfigured_detail", None)
    elif error or (last is not None and not last.ok):
        status, note = "failing", error or (last.detail if last else None)
    else:
        status, note = "set", None
    project = getattr(provider, "quota_project", "") if provider else ""
    return {
        **item,
        "env": "GEMINI_AUTH=oauth",
        "status": status,
        "preview": f"ADC · {project}" if project else "ADC",
        "testable": True,
        "last_test": last.model_dump() if last else None,
        "note": note,
    }


@app.get("/api/keys")
async def keys_status() -> list[dict[str, Any]]:
    """Status of every .env value. Secrets are only ever shown masked."""
    settings = get_settings()
    out = []
    for item in KEYS:
        if item["env"] == "GEMINI_API_KEY" and gemini_uses_oauth():
            out.append(_gemini_oauth_status(item))
            continue
        value = settings.key_for(item["env"]).strip().strip('"')
        provider = item["provider"]
        last: ConnectionTest | None = state["tests"].get(provider) if provider else None
        out.append(
            {
                **item,
                "status": _key_status(item["env"], value, provider),
                "preview": "" if item["env"] == "SEC_USER_AGENT" else mask_secret(value),
                "testable": provider is not None,
                "last_test": last.model_dump() if last else None,
            }
        )
    return out


@app.get("/api/providers")
async def providers_status() -> list[dict[str, Any]]:
    """Provider config summary for Settings: models and limits per provider."""
    settings = get_settings()
    out = []
    for name, pc in load_providers().providers.items():
        key = settings.key_for(pc.api_key_env) if pc.api_key_env else ""
        out.append(
            {
                "provider": name,
                "key_env": pc.api_key_env,
                "status": "set" if key else ("n/a" if not pc.api_key_env else "missing"),
                "key_preview": mask_secret(key),
                "models": {alias: m.id for alias, m in pc.models.items()},
                "model_limits": {alias: m.limits.model_dump() for alias, m in pc.models.items()},
                "limits": pc.limits,
            }
        )
    return out


@app.post("/api/providers/{name}/test")
async def test_provider(name: str) -> ConnectionTest:
    if name == "youtube":
        start = time.monotonic()
        ok, detail = await youtube.test_connection()
        result = ConnectionTest(
            provider=name, ok=ok, detail=detail, latency_ms=int((time.monotonic() - start) * 1000)
        )
    else:
        router = get_router()
        if name not in router.providers:
            raise HTTPException(404, f"no testable provider named {name!r}")
        result = await router.test_connection(name)
    state["tests"][name] = result
    bus.publish("provider.tested", provider=name, ok=result.ok, detail=result.detail)
    return result


# ---------------------------------------------------------------------------- agents
class AutoApproveUpdate(BaseModel):
    auto_approve: bool


def _agent_view(name: str) -> dict[str, Any]:
    return AGENTS[name].public() | {
        "auto_approve": bool(get_setting(get_engine(), auto_approve_key(name), False))
    }


@app.get("/api/agents")
async def list_agents() -> list[dict[str, Any]]:
    return [_agent_view(name) for name in AGENTS]


@app.put("/api/agents/{name}/auto-approve")
async def set_auto_approve(name: str, body: AutoApproveUpdate) -> dict[str, Any]:
    info = AGENTS.get(name)
    if info is None or not info.available:
        raise HTTPException(404, f"no available agent named {name!r}")
    set_setting(get_engine(), auto_approve_key(name), body.auto_approve)
    bus.publish("settings.changed", agent=name, auto_approve=body.auto_approve)
    return _agent_view(name)


# ---------------------------------------------------------------------------- plans
def _plans() -> PlanService:
    service: PlanService | None = state.get("plans")
    if service is None:
        raise HTTPException(503, "job runner is not running")
    return service


class ApproveIn(BaseModel):
    # step order → replacement params (from the plan card's Edit form)
    edits: dict[int, dict[str, Any]] | None = None


@app.get("/api/plans")
async def list_plans(status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    return _plans().list(status=status, limit=min(limit, 100))


@app.get("/api/plans/{plan_id}")
async def get_plan(plan_id: int) -> dict[str, Any]:
    plan = _plans().get(plan_id)
    if plan is None:
        raise HTTPException(404, f"no plan {plan_id}")
    return plan


@app.post("/api/plans")
async def create_plan(body: PlanIn) -> dict[str, Any]:
    try:
        return await _plans().create(body)
    except PlanError as e:
        raise HTTPException(422, str(e)) from e


@app.post("/api/plans/{plan_id}/approve")
async def approve_plan(plan_id: int, body: ApproveIn | None = None) -> dict[str, Any]:
    try:
        return await _plans().approve(plan_id, edits=body.edits if body else None)
    except PlanError as e:
        raise HTTPException(409, str(e)) from e


@app.post("/api/plans/{plan_id}/cancel")
async def cancel_plan(plan_id: int) -> dict[str, Any]:
    try:
        return await _plans().cancel(plan_id)
    except PlanError as e:
        raise HTTPException(404, str(e)) from e


# ---------------------------------------------------------------------------- runs
LOG_TAIL = 3


@app.get("/api/runs")
async def list_runs(status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    with Session(get_engine()) as s:
        stmt = select(AgentRun).order_by(col(AgentRun.id).desc()).limit(min(limit, 100))
        if status:
            stmt = stmt.where(col(AgentRun.status).in_(status.split(",")))
        runs = s.exec(stmt).all()
        out = []
        for run in runs:
            tail = s.exec(
                select(RunLog)
                .where(RunLog.run_id == run.id)
                .order_by(col(RunLog.id).desc())
                .limit(LOG_TAIL)
            ).all()
            out.append(
                run.model_dump(mode="json")
                | {"log_tail": [t.model_dump(mode="json") for t in reversed(tail)]}
            )
        return out


@app.get("/api/runs/{run_id}")
async def get_run(run_id: int) -> dict[str, Any]:
    with Session(get_engine()) as s:
        run = s.get(AgentRun, run_id)
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        logs = s.exec(select(RunLog).where(RunLog.run_id == run_id).order_by(col(RunLog.id))).all()
        return run.model_dump(mode="json") | {
            "logs": [entry.model_dump(mode="json") for entry in logs]
        }


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: int) -> dict[str, Any]:
    runner: JobRunner | None = state.get("runner")
    if runner is None:
        raise HTTPException(503, "job runner is not running")
    run = await runner.cancel(run_id)
    if run is None:
        raise HTTPException(404, f"no run {run_id}")
    return run.model_dump(mode="json")


# ---------------------------------------------------------------------------- stories
@app.get("/api/stories")
async def list_stories_endpoint(
    status: str | None = None,
    series: str | None = None,
    format: str | None = None,
    q: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    return stories.list_stories(
        get_engine(), status=status, series=series, format=format, q=q, limit=min(limit, 1000)
    )


@app.get("/api/stories/{story_id}")
async def get_story_endpoint(story_id: int) -> dict[str, Any]:
    story = stories.get_story(get_engine(), story_id)
    if story is None:
        raise HTTPException(404, f"no story {story_id}")
    return story


@app.patch("/api/stories/{story_id}")
async def update_story_endpoint(story_id: int, patch: stories.StoryPatch) -> dict[str, Any]:
    story = stories.update_story(get_engine(), story_id, patch)
    if story is None:
        raise HTTPException(404, f"no story {story_id}")
    bus.publish("story.changed", story_id=story_id, status=story["status"])
    return story


# ---------------------------------------------------------------------------- dossiers
@app.get("/api/dossiers")
async def list_dossiers_endpoint() -> list[dict[str, Any]]:
    return dossier_mod.list_dossiers(get_engine())


@app.get("/api/dossiers/{story_id}")
async def get_dossier_endpoint(story_id: int, version: int | None = None) -> dict[str, Any]:
    dossier = dossier_mod.get_dossier(get_engine(), story_id, version)
    if dossier is None:
        raise HTTPException(404, f"no dossier for story {story_id}")
    return dossier


@app.post("/api/dossiers/{story_id}/open")
async def open_dossier_file(story_id: int) -> dict[str, Any]:
    """Reveal the exported dossier.md on this machine (Finder on macOS)."""
    dossier = dossier_mod.get_dossier(get_engine(), story_id)
    path = Path(dossier["export_path"]) if dossier and dossier.get("export_path") else None
    if path is None or not path.exists():
        raise HTTPException(404, "no exported file for this dossier")
    opener = shutil.which("open") or shutil.which("xdg-open")
    if opener is None:
        raise HTTPException(501, f"can't open files on this system; the file is at {path}")
    args = [opener, "-R", str(path)] if opener.endswith("/open") else [opener, str(path.parent)]
    await asyncio.create_subprocess_exec(*args)
    return {"ok": True, "path": str(path)}


# ---------------------------------------------------------------------------- outliers
@app.get("/api/outliers")
async def list_outliers_endpoint(
    channel: str | None = None,
    format: str | None = None,
    min_score: float | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    return outliers.list_outliers(
        get_engine(), channel=channel, format=format, min_score=min_score, limit=min(limit, 1000)
    )


@app.get("/api/channels")
async def list_channels_endpoint() -> list[dict[str, Any]]:
    return outliers.list_channels(get_engine())


@app.post("/api/outliers/{video_id}/story")
async def story_from_outlier(video_id: str) -> dict[str, Any]:
    result = outliers.create_story_from_outlier(get_engine(), video_id)
    if result is None:
        raise HTTPException(404, f"no scanned video {video_id}")
    bus.publish("story.changed", story_id=result["story_id"], status="Inbox")
    return result


# ---------------------------------------------------------------------------- chats
def _chats() -> ChatService:
    service: ChatService | None = state.get("chats")
    if service is None:
        raise HTTPException(503, "chat service is not running")
    return service


class ChatIn(BaseModel):
    title: str | None = None


class ChatPatch(BaseModel):
    title: str


class MessageIn(BaseModel):
    content: str


@app.get("/api/chats")
async def list_chats() -> list[dict[str, Any]]:
    return _chats().list()


@app.post("/api/chats")
async def create_chat(body: ChatIn | None = None) -> dict[str, Any]:
    return _chats().create(body.title if body else None)


@app.get("/api/chats/{chat_id}")
async def get_chat(chat_id: int) -> dict[str, Any]:
    chat = _chats().get(chat_id)
    if chat is None:
        raise HTTPException(404, f"no chat {chat_id}")
    return chat


@app.patch("/api/chats/{chat_id}")
async def rename_chat(chat_id: int, body: ChatPatch) -> dict[str, Any]:
    chat = _chats().rename(chat_id, body.title)
    if chat is None:
        raise HTTPException(404, f"no chat {chat_id}")
    return chat


@app.delete("/api/chats/{chat_id}")
async def delete_chat(chat_id: int) -> dict[str, bool]:
    try:
        if not _chats().delete(chat_id):
            raise HTTPException(404, f"no chat {chat_id}")
    except ChatError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True}


@app.post("/api/chats/{chat_id}/messages", status_code=202)
async def send_message(chat_id: int, body: MessageIn) -> dict[str, Any]:
    """Store the message and start handling it (fast path or orchestrator) in the background.
    Replies arrive over SSE (`chat.message`, `chat.delta`, `chat.status`)."""
    try:
        return await _chats().send(chat_id, body.content)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except ChatError as e:
        raise HTTPException(422, str(e)) from e


@app.get("/api/memory/search")
async def search_memory_endpoint(q: str, limit: int = 8) -> dict[str, Any]:
    return await memory.search(get_engine(), q, limit=min(limit, 30))


# ---------------------------------------------------------------------------- claude settings
class ClaudeSettingsIn(BaseModel):
    soft_cap: int


@app.get("/api/settings/claude")
async def get_claude_settings() -> dict[str, Any]:
    cfg = load_engine()
    return {
        "soft_cap": claude_soft_cap(get_engine(), cfg),
        "default_soft_cap": cfg.orchestrator.daily_soft_cap,
        "model": cfg.orchestrator.model,
        "effort": cfg.orchestrator.effort,
        "tools": mcp_server.allowed_tools(),
    }


@app.put("/api/settings/claude")
async def put_claude_settings(body: ClaudeSettingsIn) -> dict[str, Any]:
    if not 1 <= body.soft_cap <= 1000:
        raise HTTPException(422, "soft cap must be between 1 and 1000")
    set_setting(get_engine(), CLAUDE_CAP_KEY, body.soft_cap)
    bus.publish("settings.changed", claude_soft_cap=body.soft_cap)
    return await get_claude_settings()


# ---------------------------------------------------------------------------- usage
@app.get("/api/usage")
async def usage_today() -> dict[str, Any]:
    statuses = {k["provider"]: k["status"] for k in await keys_status() if k["provider"]}
    return build_report(get_engine(), load_providers(), load_engine(), statuses)


# ---------------------------------------------------------------------------- config files
class ConfigUpdate(BaseModel):
    raw: str


@app.get("/api/config/{name}")
async def get_config(name: str) -> ConfigFile:
    try:
        return read_config(name)
    except ConfigError as e:
        raise HTTPException(404, str(e)) from e


@app.put("/api/config/{name}")
async def put_config(name: str, body: ConfigUpdate) -> ConfigFile:
    try:
        saved = write_config(name, body.raw)
    except ConfigError as e:
        raise HTTPException(422, str(e)) from e
    get_router.cache_clear()
    sources._http.reset_pacer()
    bus.publish("config.saved", file=saved.path)
    return saved
