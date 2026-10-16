"""Startup checks: is the Claude Code CLI installed and logged in? (SPEC §10)"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from typing import Any, Literal

from pydantic import BaseModel, model_validator

ClaudeState = Literal["ready", "logged_out", "unknown", "not_installed"]

LOGIN_HINT = "Run `claude auth login` in a terminal, then Re-check."
MAX_OUTPUT = 400
_REDACT = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "<email>"),
    (re.compile(r"sk-ant-[\w-]+"), "<token>"),
    (re.compile(r"[A-Za-z0-9_\-]{32,}"), "<redacted>"),  # long opaque ids/tokens
]


class ClaudeStatus(BaseModel):
    installed: bool
    logged_in: bool
    state: ClaudeState | None = None  # None → derived from installed/logged_in
    version: str | None = None
    auth_method: str | None = None
    detail: str
    output: str | None = None  # what `claude auth status` printed: trimmed, redacted
    path: str | None = None  # which `claude` the API process found (PATH differs under make dev?)

    @model_validator(mode="after")
    def _derive_state(self) -> ClaudeStatus:
        if self.state is None:
            self.state = (
                "ready" if self.logged_in else "logged_out" if self.installed else "not_installed"
            )
        return self

    @property
    def usable(self) -> bool:
        """Block Claude work only on a definite "no"; when unsure, try the real call."""
        return self.state in ("ready", "unknown")


def redact(text: str) -> str:
    for pattern, repl in _REDACT:
        text = pattern.sub(repl, text)
    text = text.strip()
    return text if len(text) <= MAX_OUTPUT else text[:MAX_OUTPUT] + " …"


def _json_object(text: str) -> dict[str, Any] | None:
    """The JSON object in the CLI output, tolerating warnings printed around it."""
    for candidate in (text, text[text.find("{") : text.rfind("}") + 1]):
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


_LOGGED_OUT_TEXT = re.compile(r"not (logged|signed) in|logged out|please (run|use).*login", re.I)
_LOGGED_IN_TEXT = re.compile(r"\b(logged|signed) in (as|with|to|using)\b", re.I)


def parse_auth_status(code: int, out: str) -> tuple[ClaudeState, str | None]:
    """Map `claude auth status [--json]` output to a state.

    Current CLI (2.1.x): JSON with `loggedIn` (bool) and `authMethod`; exit 0 when logged in,
    1 when not. Anything we can't read is "unknown", never "logged out".
    """
    obj = _json_object(out)
    if obj is not None:
        logged_in = obj.get("loggedIn", obj.get("logged_in"))
        method = obj.get("authMethod") or obj.get("auth_method")
        if isinstance(logged_in, bool):
            return ("ready" if logged_in else "logged_out"), method
        return "unknown", method
    if _LOGGED_OUT_TEXT.search(out):
        return "logged_out", None
    if code == 0 and _LOGGED_IN_TEXT.search(out):
        return "ready", None
    return "unknown", None


async def _run(*args: str, timeout_s: float = 20.0) -> tuple[int, str]:
    """Exit code and output; stdout first, then any stderr (warnings, keychain errors)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
    except OSError as e:
        return -1, f"could not run {args[0]}: {e}"
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout_s)
    except TimeoutError:
        proc.kill()
        return -1, "timed out"
    text = out.decode(errors="replace").strip()
    extra = err.decode(errors="replace").strip()
    return proc.returncode or 0, f"{text}\n{extra}".strip() if extra else text


async def check_claude_cli() -> ClaudeStatus:
    exe = shutil.which("claude")
    if not exe:
        return ClaudeStatus(
            installed=False,
            logged_in=False,
            state="not_installed",
            detail="Claude Code CLI not found on PATH. Install it from https://claude.com/claude-code",
        )
    _, version_out = await _run(exe, "--version")
    version = version_out.splitlines()[0] if version_out else None
    code, out = await _run(exe, "auth", "status", "--json")
    state, method = parse_auth_status(code, out)
    if state == "unknown" and _json_object(out) is None:
        # Maybe `--json` went away: ask again in plain text.
        code, out = await _run(exe, "auth", "status")
        state, method = parse_auth_status(code, out)
    detail = {
        "ready": "ready",
        "logged_out": f"Claude Code is installed but not logged in. {LOGIN_HINT}",
        "unknown": "Couldn't tell whether Claude Code is logged in; Claude calls will be tried "
        "anyway and show their own error.",
    }[state]
    return ClaudeStatus(
        installed=True,
        logged_in=state == "ready",
        state=state,
        version=version,
        auth_method=method,
        detail=detail,
        output=redact(out) if out else None,
        path=exe,
    )
