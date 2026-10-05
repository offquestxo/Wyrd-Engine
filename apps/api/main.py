"""FastAPI app. Run with `make dev` (binds 127.0.0.1:8000 only)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel

from apps.api import sources
from apps.api.agents.registry import AGENTS, AgentInfo
from apps.api.config import load_providers
from apps.api.config_files import ConfigError, ConfigFile, read_config, write_config
from apps.api.db.session import get_engine
from apps.api.events import bus
from apps.api.providers.base import ConnectionTest
from apps.api.providers.router import get_router
from apps.api.settings import get_settings, mask_secret
from apps.api.settings_store import auto_approve_key, get_setting, set_setting
from apps.api.sources import youtube
from apps.api.system import ClaudeStatus, check_claude_cli

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


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    get_engine()  # creates / migrates data/wyrd.db
    state["claude"] = await check_claude_cli()
    yield


app = FastAPI(title="wyrd.exe story engine", version="0.1.0", lifespan=lifespan)
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
    state["claude"] = await check_claude_cli()
    return state["claude"]


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


@app.get("/api/keys")
async def keys_status() -> list[dict[str, Any]]:
    """Status of every .env value. Secrets are only ever shown masked."""
    settings = get_settings()
    out = []
    for item in KEYS:
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
class AgentSettings(AgentInfo):
    auto_approve: bool


class AutoApproveUpdate(BaseModel):
    auto_approve: bool


@app.get("/api/agents")
async def list_agents() -> list[AgentSettings]:
    engine = get_engine()
    return [
        AgentSettings(
            **info.model_dump(),
            auto_approve=bool(get_setting(engine, auto_approve_key(name), False)),
        )
        for name, info in AGENTS.items()
    ]


@app.put("/api/agents/{name}/auto-approve")
async def set_auto_approve(name: str, body: AutoApproveUpdate) -> AgentSettings:
    info = AGENTS.get(name)
    if info is None or not info.available:
        raise HTTPException(404, f"no available agent named {name!r}")
    set_setting(get_engine(), auto_approve_key(name), body.auto_approve)
    bus.publish("settings.changed", agent=name, auto_approve=body.auto_approve)
    return AgentSettings(**info.model_dump(), auto_approve=body.auto_approve)


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
