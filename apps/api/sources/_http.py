"""Shared HTTP plumbing for source modules: polite per-host pacing, retries, CLI output.

Sources raise SourceError on failure; callers (agents) catch it, log, and skip — a failing
source never crashes a run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections.abc import Callable, Coroutine
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from apps.api.config import load_sources
from apps.api.settings import get_settings

DEFAULT_UA = "wyrd-engine/0.1 (local research tool)"


class SourceError(Exception):
    def __init__(self, source: str, message: str, status: int | None = None) -> None:
        super().__init__(f"{source}: {message}")
        self.source = source
        self.status = status


class _HostPacer:
    """Enforces a minimum interval between requests to the same host."""

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}
        self._intervals = load_sources().http.min_interval_s

    def interval(self, host: str) -> float:
        return self._intervals.get(host, self._intervals.get("default", 0.2))

    async def wait(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            gap = self.interval(host) - (time.monotonic() - self._last.get(host, 0.0))
            if gap > 0:
                await asyncio.sleep(gap)
            self._last[host] = time.monotonic()


_pacer: _HostPacer | None = None


def _get_pacer() -> _HostPacer:
    global _pacer
    if _pacer is None:
        _pacer = _HostPacer()
    return _pacer


def contact_user_agent() -> str:
    """UA with a contact address (SEC and Wikimedia both ask for one)."""
    return get_settings().sec_user_agent.strip().strip('"') or DEFAULT_UA


async def request(
    source: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    retries: int = 2,
    timeout_s: float | None = None,
) -> httpx.Response:
    """GET with pacing and retry on 429/5xx. Raises SourceError on failure."""
    host = urlparse(url).netloc
    merged = {"User-Agent": contact_user_agent(), **(headers or {})}
    timeout = timeout_s or load_sources().http.timeout_s
    last_error = "unknown error"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for attempt in range(retries + 1):
            await _get_pacer().wait(host)
            try:
                resp = await client.get(url, params=params, headers=merged)
            except httpx.HTTPError as e:
                last_error = f"network error: {type(e).__name__}"
            else:
                if resp.status_code < 400:
                    return resp
                last_error = f"HTTP {resp.status_code}"
                if resp.status_code != 429 and resp.status_code < 500:
                    raise SourceError(source, f"{last_error}: {resp.text[:200]}", resp.status_code)
            if attempt < retries:
                await asyncio.sleep(min(10.0, 1.5 * (2**attempt)) + _get_pacer().interval(host))
    raise SourceError(source, last_error)


async def get_json(source: str, url: str, **kwargs: Any) -> Any:
    resp = await request(source, url, **kwargs)
    try:
        return resp.json()
    except ValueError as e:
        raise SourceError(source, f"expected JSON, got: {resp.text[:200]}") from e


async def get_text(source: str, url: str, **kwargs: Any) -> str:
    return (await request(source, url, **kwargs)).text


def truncate(text: str | None, limit: int = 300) -> str:
    """Short excerpts only (copyright): collapse whitespace and cut."""
    clean = " ".join((text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


# ---------------------------------------------------------------------------- CLI
def _to_jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_to_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _to_jsonable(v) for k, v in value.items()}
    return value


Command = Callable[[argparse.Namespace], Coroutine[Any, Any, Any]]


def run_cli(source: str, parser: argparse.ArgumentParser, commands: dict[str, Command]) -> None:
    """Dispatch a subcommand and print {"source","command","ok","data"|"error"} as JSON."""
    args = parser.parse_args()
    command = args.command
    try:
        data = asyncio.run(commands[command](args))
        out = {"source": source, "command": command, "ok": True, "data": _to_jsonable(data)}
        code = 0
    except SourceError as e:
        out = {"source": source, "command": command, "ok": False, "error": str(e)}
        code = 1
    print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    sys.exit(code)
