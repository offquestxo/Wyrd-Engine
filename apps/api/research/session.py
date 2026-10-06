"""Per-run research state shared between the researcher runner and the MCP tools.

The runner opens a session for its run id; MCP calls from that run's Claude process carry the
run id in a header, so tools can record what they served (for the excerpt check), log into the
run, and enforce per-run rules (second opinion before saving, YouTube search cap).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

LogFn = Callable[[str, str], None]


@dataclass
class ResearchSession:
    run_id: int
    story_id: int
    depth: str
    log: LogFn = lambda level, message: None
    texts: dict[str, str] = field(default_factory=dict)  # URL → text served to the researcher
    second_opinions: list[dict[str, Any]] = field(default_factory=list)
    youtube_searches: int = 0
    tool_calls: dict[str, int] = field(default_factory=dict)
    source_notes: list[str] = field(default_factory=list)  # known source limits hit this run
    saved: list[dict[str, Any]] = field(default_factory=list)  # save_dossier results

    def note(self, message: str) -> None:
        """A source limit or failure: logged once and listed in the run summary."""
        if message not in self.source_notes:
            self.source_notes.append(message)
            self.log("warn", message)


SESSIONS: dict[int, ResearchSession] = {}


def open_session(session: ResearchSession) -> ResearchSession:
    SESSIONS[session.run_id] = session
    return session


def close_session(run_id: int) -> ResearchSession | None:
    return SESSIONS.pop(run_id, None)


def get_session(run_id: int | None) -> ResearchSession | None:
    return SESSIONS.get(run_id) if run_id is not None else None
