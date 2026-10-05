"""Startup checks: is the Claude Code CLI installed and logged in? (SPEC §10)"""

from __future__ import annotations

import asyncio
import json
import shutil

from pydantic import BaseModel


class ClaudeStatus(BaseModel):
    installed: bool
    logged_in: bool
    version: str | None = None
    auth_method: str | None = None
    detail: str


async def _run(*args: str, timeout_s: float = 20.0) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout_s)
    except TimeoutError:
        proc.kill()
        return -1, "timed out"
    return proc.returncode or 0, out.decode(errors="replace").strip()


async def check_claude_cli() -> ClaudeStatus:
    exe = shutil.which("claude")
    if not exe:
        return ClaudeStatus(
            installed=False,
            logged_in=False,
            detail="Claude Code CLI not found on PATH. Install it from https://claude.com/claude-code",
        )
    _, version = await _run(exe, "--version")
    code, out = await _run(exe, "auth", "status", "--json")
    try:
        status = json.loads(out)
    except json.JSONDecodeError:
        status = {}
    logged_in = bool(status.get("loggedIn")) and code == 0
    return ClaudeStatus(
        installed=True,
        logged_in=logged_in,
        version=version.splitlines()[0] if version else None,
        auth_method=status.get("authMethod"),
        detail="ready"
        if logged_in
        else "Claude Code is installed but not logged in. Run `claude auth login`.",
    )
