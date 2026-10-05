"""FastAPI app. Run with `make dev` (binds 127.0.0.1:8000 only)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from apps.api.config import load_providers
from apps.api.db.session import get_engine
from apps.api.providers.base import ConnectionTest
from apps.api.providers.router import get_router
from apps.api.settings import get_settings, mask_secret
from apps.api.sources import youtube
from apps.api.system import ClaudeStatus, check_claude_cli

state: dict[str, Any] = {}


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


@app.get("/api/health")
async def health() -> dict[str, Any]:
    claude: ClaudeStatus | None = state.get("claude")
    return {"ok": True, "claude": claude.model_dump() if claude else None}


@app.get("/api/system/claude")
async def claude_status() -> ClaudeStatus:
    state["claude"] = await check_claude_cli()
    return state["claude"]


@app.get("/api/providers")
async def providers_status() -> list[dict[str, Any]]:
    """Key status per provider: set/missing, masked. Keys are never returned in full."""
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
            }
        )
    return out


@app.post("/api/providers/{name}/test")
async def test_provider(name: str) -> ConnectionTest:
    if name == "youtube":
        start = time.monotonic()
        ok, detail = await youtube.test_connection()
        return ConnectionTest(
            provider=name, ok=ok, detail=detail, latency_ms=int((time.monotonic() - start) * 1000)
        )
    router = get_router()
    if name not in router.providers:
        raise HTTPException(404, f"no testable provider named {name!r}")
    return await router.test_connection(name)
