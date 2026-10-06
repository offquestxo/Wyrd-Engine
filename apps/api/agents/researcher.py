"""@researcher: deep research → sourced dossier (SPEC §6.3).

Runs Claude Code headless as the `researcher` agent. The definition comes from
`.claude/agents/researcher.md` (name, description, tools, model), and its prompt is the
rendered `prompts/researcher.md`. Both are passed inline with `--agents`/`--agent`, so the
working directory can stay outside the repo and the project's CLAUDE.md isn't loaded.

- Tools: the researcher MCP endpoint (`/mcp-research`: source_*, extract_from_document,
  second_opinion, save_dossier, get_story, search_memory) plus WebSearch/WebFetch. No shell,
  no file access.
- **Turn budget per depth** (`scoring.yaml` research.depths): passed as the agent's
  `maxTurns` and enforced here too. The process is stopped once it exceeds the budget.
- Claude usage (turns, duration, tokens) is logged as one `provider_usage` row
  (provider `claude`, task `researcher`) and reported in the run summary.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from sqlmodel import Session, col, select

from apps.api import prompts
from apps.api.agents.orchestrator import (
    API_URL,
    OrchestratorError,
    TurnEvent,
    TurnResult,
    stream_claude,
)
from apps.api.agents.params import ResearcherParams
from apps.api.config import load_scoring
from apps.api.db.models import Story, StoryStatus, utcnow
from apps.api.db.session import get_engine
from apps.api.events import bus
from apps.api.mcp_server import (
    MOUNTS,
    RESEARCHER,
    RUN_HEADER,
    SERVER_NAME,
    TOKEN,
    TOKEN_HEADER,
    allowed_tools,
)
from apps.api.providers.usage import UsageLog
from apps.api.research.session import ResearchSession, close_session, open_session
from apps.api.settings import ROOT
from apps.api.stories import unique_slug

if TYPE_CHECKING:
    from apps.api.jobs import RunContext

AGENT_FILE = ROOT / ".claude" / "agents" / "researcher.md"
BUILTIN_TOOLS = ["WebSearch", "WebFetch"]
WRITE_UP_TURNS = 8  # turns kept back for draft → second opinion → fixes → save
EARLY_STATUSES = {StoryStatus.INBOX.value, StoryStatus.SHORTLISTED.value}


def depth_config(depth: str) -> dict[str, Any]:
    depths: dict[str, Any] = load_scoring().research.get("depths", {})
    return dict(depths.get(depth) or depths.get("standard") or {})


def estimate(params: dict[str, Any]) -> dict[str, Any]:
    p = ResearcherParams.model_validate(params)
    cfg = depth_config(p.depth)
    sources = list(cfg.get("sources", []))
    searches = (
        int(load_scoring().research.get("youtube_searches_max", 2)) if "youtube" in sources else 0
    )
    turns = int(cfg.get("claude_turns", 40))
    return {
        "claude_turns": turns,
        "sources": sources,
        "youtube_search_calls": searches,
        "youtube_units": searches * 2,  # search.list + videos.list per search
        "note": f"{p.depth}: up to {turns} Claude turns",
    }


def agent_definition() -> dict[str, Any]:
    """Frontmatter of .claude/agents/researcher.md."""
    raw = AGENT_FILE.read_text()
    _, front, _body = raw.split("---", 2)
    meta: dict[str, Any] = yaml.safe_load(front) or {}
    tools = meta.get("tools", [])
    if isinstance(tools, str):
        tools = [t.strip() for t in tools.split(",") if t.strip()]
    meta["tools"] = tools
    return meta


def resolve_story(p: ResearcherParams) -> Story:
    """The story to research: by id, by matching title, or a new one for a topic."""
    with Session(get_engine()) as s:
        if p.story_id is not None:
            story = s.get(Story, p.story_id)
            if story is None:
                raise ValueError(f"no story {p.story_id}")
        else:
            topic = (p.topic or "").strip()
            story = s.exec(
                select(Story).where(col(Story.title).ilike(topic)).order_by(col(Story.id))
            ).first()
            if story is None:
                story = Story(
                    slug=unique_slug(s, topic),
                    title=topic,
                    status=StoryStatus.RESEARCHING.value,
                    notes="Created by @researcher from a topic.",
                )
        # An approved research plan moves an early-stage story to Researching.
        if story.status in EARLY_STATUSES:
            story.status = StoryStatus.RESEARCHING.value
            story.updated_at = utcnow()
        s.add(story)
        s.commit()
        s.refresh(story)
        return story


def story_brief(story: Story) -> str:
    brief = {
        "id": story.id,
        "title": story.title,
        "company": story.company,
        "series": story.series,
        "format": story.format,
        "scout_hook_UNVERIFIED_LEAD": story.hook,
        "notes": (story.notes or "")[:500] or None,
    }
    return json.dumps({k: v for k, v in brief.items() if v})


def build_command(
    exe: str, run_id: int, agent_prompt: str, turns: int, model: str, effort: str | None
) -> list[str]:
    meta = agent_definition()
    agents = {
        meta.get("name", "researcher"): {
            "description": meta.get("description", "wyrd.exe researcher"),
            "prompt": agent_prompt,
            "tools": meta["tools"],
            "model": model or meta.get("model", "sonnet"),
            "maxTurns": turns,
        }
    }
    mcp = {
        "mcpServers": {
            SERVER_NAME: {
                "type": "http",
                "url": f"{API_URL}{MOUNTS[RESEARCHER]}/",
                "headers": {RUN_HEADER: str(run_id), TOKEN_HEADER: TOKEN},
            }
        }
    }
    cmd = [
        exe,
        "-p",
        "--agents",
        json.dumps(agents),
        "--agent",
        meta.get("name", "researcher"),
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model,
        "--mcp-config",
        json.dumps(mcp),
        "--strict-mcp-config",
        "--tools",
        ",".join(BUILTIN_TOOLS),
        "--allowedTools",
        ",".join([*allowed_tools(RESEARCHER), *BUILTIN_TOOLS]),
        "--permission-mode",
        "dontAsk",
        "--setting-sources",
        "",
        "--disable-slash-commands",
        "--no-session-persistence",
    ]
    if effort:
        cmd += ["--effort", effort]
    return cmd


def workdir() -> Path:
    path = Path("~/.local/share/wyrd/researcher").expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _short(value: Any, limit: int = 140) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def run(ctx: RunContext) -> dict[str, Any]:
    p = ResearcherParams.model_validate(ctx.params)
    research = load_scoring().research
    cfg = depth_config(p.depth)
    turns = int(cfg.get("claude_turns", 40))
    story = resolve_story(p)
    assert story.id is not None
    bus.publish("story.changed", story_id=story.id, status=story.status)
    ctx.log("info", f"Researching story #{story.id} “{story.title}” at depth {p.depth}")

    exe = shutil.which("claude")
    if exe is None:
        raise OrchestratorError("Claude Code CLI not found on PATH")
    session = open_session(
        ResearchSession(run_id=ctx.run_id, story_id=story.id, depth=p.depth, log=ctx.log)
    )
    agent_prompt = prompts.render(
        "researcher",
        story=story_brief(story),
        depth=p.depth,
        focus=p.focus or "none (cover the whole story)",
        sources=", ".join(cfg.get("sources", [])),
        turn_budget=str(turns),
        research_turns=str(max(1, turns - WRITE_UP_TURNS)),
        excerpt_words=str(research.get("excerpt_max_words", 40)),
        today=datetime.now(UTC).date().isoformat(),
    )
    model = str(research.get("model", "sonnet"))
    effort = research.get("effort")
    command = build_command(exe, ctx.run_id, agent_prompt, turns, model, effort)
    result: TurnResult | None = None
    text: list[str] = []
    seen_turns = 0
    try:
        async for ev in stream_claude(
            lambda _attempt: command,
            workdir(),
            f"Research story #{story.id}: {story.title}. Follow your instructions.",
            float(research.get("run_timeout_s", 1800)),
            f"research run {ctx.run_id}",
            max_turns=turns,
        ):
            if isinstance(ev, TurnResult):
                result = ev
            elif isinstance(ev, TurnEvent) and ev.kind == "tool":
                seen_turns += 1
                ctx.log("info", f"Claude → {ev.tool}({_short(ev.data.get('input'))})")
                ctx.step(f"Turn {seen_turns}/{turns}: {ev.tool}", min(0.98, seen_turns / turns))
            elif isinstance(ev, TurnEvent) and ev.kind == "text":
                text.append(ev.text)
    finally:
        close_session(ctx.run_id)
        if result is not None:
            UsageLog(get_engine()).record(
                provider="claude",
                model=result.model,
                task="researcher",
                ok=result.ok,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                latency_ms=result.duration_ms,
                error=result.error,
                turns=result.turns,
            )
    assert result is not None
    claude = {
        "turns": result.turns,
        "turn_budget": turns,
        "duration_s": round(result.duration_ms / 1000),
        "tokens_in": result.tokens_in,
        "tokens_out": result.tokens_out,
        "model": result.model,
        "tool_calls": dict(session.tool_calls),
    }
    ctx.log(
        "info",
        f"Claude: {result.turns}/{turns} turns, {claude['duration_s']}s, "
        f"{result.tokens_in:,} tokens in / {result.tokens_out:,} out ({result.model})",
    )
    if not session.saved:
        reason = result.error or "the researcher finished without calling save_dossier"
        raise RuntimeError(f"No dossier saved: {reason}")
    if not result.ok:
        ctx.log("warn", f"Claude stopped early ({result.error}); the saved dossier is kept")
    saved = session.saved[-1]
    review = session.second_opinions[-1] if session.second_opinions else {}
    check = saved["excerpt_check"]
    flags = review.get("flags", [])
    summary = (
        f"Dossier v{saved['version']} for “{story.title}”: excerpt check {check['passed']} "
        f"passed, {check['failed']} moved to Open Questions; second opinion {len(flags)} flags; "
        f"Claude {result.turns} turns, {claude['duration_s']}s"
    )
    ctx.step("Done", 1.0)
    return {
        "summary": summary,
        "story_id": story.id,
        "dossier_id": saved["dossier_id"],
        "version": saved["version"],
        "export": saved["export"],
        "excerpt_check": check,
        "moved_to_open_questions": saved["moved_to_open_questions"],
        "second_opinion": {
            "flags": flags,
            "resolutions": saved.get("resolutions", []),
            "precheck": review.get("excerpt_precheck"),
        },
        "claude": claude,
        "source_notes": session.source_notes,
        "final_message": "".join(text).strip()[-1500:],
    }
