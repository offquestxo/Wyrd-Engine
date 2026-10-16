"""Claude CLI status check (apps/api/system.py): parse what the installed CLI prints."""

from __future__ import annotations

from typing import Any

import pytest

from apps.api import system
from apps.api.system import ClaudeStatus, check_claude_cli, parse_auth_status, redact

# Captured from Claude Code 2.1.196 (`claude auth status --json`), 2026-10-16. The logged-in
# sample has the real key set; the account values are placeholders.
LOGGED_OUT_2_1 = (
    '{\n  "loggedIn": false,\n  "authMethod": "none",\n  "apiProvider": "firstParty"\n}'
)
LOGGED_IN_2_1 = (
    '{\n  "loggedIn": true,\n  "authMethod": "claude.ai",\n  "apiProvider": "firstParty",\n'
    '  "email": "owner@example.com",\n  "orgId": "00000000-1111-2222-3333-444444444444",\n'
    '  "orgName": "Owner Org",\n  "subscriptionType": "pro"\n}'
)


def test_current_cli_logged_out() -> None:
    assert parse_auth_status(1, LOGGED_OUT_2_1) == ("logged_out", "none")


def test_current_cli_logged_in() -> None:
    assert parse_auth_status(0, LOGGED_IN_2_1) == ("ready", "claude.ai")


def test_logged_in_even_with_a_warning_on_stderr() -> None:
    out = LOGGED_IN_2_1 + "\nWarning: a newer version of Claude Code is available"
    assert parse_auth_status(0, out)[0] == "ready"


@pytest.mark.parametrize(
    "out",
    [
        "",
        "timed out",
        '{"authenticated": "yes"}',  # renamed key
        "error: unknown option '--json'",
        "Some brand new status format",
    ],
)
def test_unknown_format_is_unknown_not_logged_out(out: str) -> None:
    assert parse_auth_status(1, out)[0] == "unknown"


def test_plain_text_status() -> None:
    assert parse_auth_status(1, "You are not logged in. Run claude auth login.")[0] == "logged_out"
    assert parse_auth_status(0, "Logged in as owner@example.com")[0] == "ready"


def test_redact_hides_emails_and_tokens() -> None:
    out = redact(LOGGED_IN_2_1 + "\nsk-ant-oat01-abcdefghijklmnop " + "x" * 40)
    assert "owner@example.com" not in out and "sk-ant" not in out and "x" * 40 not in out
    assert "00000000-1111-2222-3333-444444444444" not in out  # orgId
    assert '"loggedIn": true' in out
    assert len(redact("a " * 500)) <= system.MAX_OUTPUT + 2


def test_usable_only_blocks_a_definite_no() -> None:
    assert ClaudeStatus(installed=True, logged_in=False, state="unknown", detail="?").usable
    assert not ClaudeStatus(installed=True, logged_in=False, detail="no").usable  # derived
    assert ClaudeStatus(installed=True, logged_in=False, detail="no").state == "logged_out"
    assert not ClaudeStatus(installed=False, logged_in=False, detail="no").usable


async def test_check_reports_output_and_retries_without_json(monkeypatch: Any) -> None:
    calls: list[tuple[str, ...]] = []

    async def fake_run(*args: str, timeout_s: float = 20.0) -> tuple[int, str]:
        calls.append(args[1:])
        if args[1:] == ("--version",):
            return 0, "9.0.0 (Claude Code)"
        if "--json" in args:
            return 1, "error: unknown option '--json'"
        return 0, "Logged in as owner@example.com (claude.ai)"

    monkeypatch.setattr(system.shutil, "which", lambda _: "/usr/local/bin/claude")
    monkeypatch.setattr(system, "_run", fake_run)
    status = await check_claude_cli()
    assert calls[-1] == ("auth", "status")
    assert status.state == "ready" and status.logged_in and status.version == "9.0.0 (Claude Code)"
    assert status.output and "owner@example.com" not in status.output


async def test_check_logged_out_shows_cli_output(monkeypatch: Any) -> None:
    async def fake_run(*args: str, timeout_s: float = 20.0) -> tuple[int, str]:
        return (0, "2.1.196 (Claude Code)") if args[1:] == ("--version",) else (1, LOGGED_OUT_2_1)

    monkeypatch.setattr(system.shutil, "which", lambda _: "/opt/homebrew/bin/claude")
    monkeypatch.setattr(system, "_run", fake_run)
    status = await check_claude_cli()
    assert status.state == "logged_out" and not status.usable
    assert "claude auth login" in status.detail and '"loggedIn": false' in (status.output or "")
