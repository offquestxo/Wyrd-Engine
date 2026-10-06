"""Phase 5: chat service, @mention fast path, results loop, MCP tools, memory, stream parsing.

Claude is never called: the orchestrator's turn runner is replaced with a fake that yields
the same events the real stream-json parser produces.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from sqlmodel import Session, select

from apps.api import chat as chat_mod
from apps.api import mcp_server, memory
from apps.api.agents import orchestrator
from apps.api.config import OrchestratorConfig
from apps.api.db.migrate import migrate_path
from apps.api.db.models import ProviderUsage, Story
from apps.api.db.session import make_engine
from apps.api.events import EventBus
from apps.api.jobs import JobRunner
from apps.api.plans import PlanService
from apps.api.providers.base import EmbedResult, ProviderError
from apps.api.providers.schemas import MentionParse
from apps.api.system import ClaudeStatus

READY = ClaudeStatus(installed=True, logged_in=True, detail="ready")


async def wait_for(check: Callable[[], bool], limit_s: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + limit_s
    while not check():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


# ---------------------------------------------------------------------------- fakes
class FakeRouter:
    """parse_mention + embed. Embeddings are bag-of-keywords vectors, so similar texts match."""

    VOCAB = ("fraud", "scout", "outlier", "company", "man", "theranos", "enron", "story")

    def __init__(self) -> None:
        self.mention: MentionParse | Exception = MentionParse(
            agent="scout", params={"topic": "fraud", "limit": 5}, confident=True
        )
        self.mention_calls = 0
        self.embed_fails = False

    async def parse_mention(self, text: str) -> MentionParse:
        self.mention_calls += 1
        if isinstance(self.mention, Exception):
            raise self.mention
        return self.mention

    async def embed(self, texts: list[str]) -> EmbedResult:
        if self.embed_fails:
            raise ProviderError("nvidia", "down")
        vecs = [[float(w in t.lower()) + 0.01 for w in self.VOCAB] for t in texts]
        return EmbedResult(vectors=vecs, model="fake-embed")


class FakeClaude:
    """Stands in for orchestrator.run_turn; records every call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.reply = "Proposed a plan."
        self.on_call: Callable[[int], Any] | None = None

    async def __call__(
        self, cfg: Any, chat_id: int, session_id: str, resume: bool, prompt: str
    ) -> AsyncIterator[Any]:
        self.calls.append(
            {"chat_id": chat_id, "session": session_id, "resume": resume, "prompt": prompt}
        )
        if self.on_call:
            await self.on_call(chat_id)
            yield orchestrator.TurnEvent("tool", tool="propose_plan")
        for word in self.reply.split(" "):
            yield orchestrator.TurnEvent("text", text=word + " ")
        yield orchestrator.TurnEvent("rate_limit", data={"status": "allowed"})
        yield orchestrator.TurnResult(
            text=self.reply,
            ok=True,
            session_id=session_id,
            duration_ms=1200,
            turns=2,
            tokens_in=100,
            tokens_out=20,
            model="claude-test",
            tools=["propose_plan"] if self.on_call else [],
        )


async def fake_scout(ctx: Any) -> dict[str, Any]:
    return {
        "summary": "Scout found 2 new stories",
        "stories": [
            {"id": 1, "title": "Theranos fraud", "score": 8.1, "mode": "news"},
            {"id": 2, "title": "Enron fraud", "score": 7.5, "mode": "news"},
        ],
    }


async def fake_outlier(ctx: Any) -> dict[str, Any]:
    return {
        "summary": "Outlier scan: 1 video",
        "youtube_units": 3,
        "top": [
            {
                "video_id": "v1",
                "title": "Why Sears died",
                "outlier_score": 9.5,
                "channel": "Company Man",
                "is_short": False,
            }
        ],
    }


@pytest.fixture
def engine(tmp_path: Path) -> Any:
    migrate_path(tmp_path / "chat.db")
    return make_engine(tmp_path / "chat.db")


@pytest.fixture
async def svc(
    engine: Any, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[chat_mod.ChatService, PlanService, FakeClaude, FakeRouter, EventBus]]:
    bus = EventBus(history=1000)
    agents = {"scout": fake_scout, "outlier": fake_outlier}
    runner = JobRunner(engine, bus, poll_interval_s=0.05, resolve=lambda name: agents[name])
    plans = PlanService(engine, bus, runner)
    claude, router = FakeClaude(), FakeRouter()
    status = {"value": READY}

    async def check() -> ClaudeStatus:
        return status["value"]

    monkeypatch.setattr(chat_mod, "get_router", lambda: router)
    monkeypatch.setattr(memory, "get_router", lambda: router)
    monkeypatch.setattr(mcp_server, "get_engine", lambda: engine)
    monkeypatch.setitem(mcp_server._services, "plans", plans)
    service = chat_mod.ChatService(engine, bus, plans, OrchestratorConfig(), check, claude)
    service.claude_status = status  # type: ignore[attr-defined]  # tests flip it
    await runner.start()
    yield service, plans, claude, router, bus
    await service.drain()
    await runner.stop()


def roles(service: chat_mod.ChatService, chat_id: int) -> list[str]:
    view = service.get(chat_id)
    assert view is not None
    return [m["role"] for m in view["messages"]]


# ---------------------------------------------------------------------------- fast path
async def test_mention_fast_path_makes_plan_without_claude(svc: Any) -> None:
    service, _plans, claude, router, _ = svc
    chat = service.create()
    msg = await service.send(chat["id"], "@scout find 5 fraud stories")
    await service.drain()
    assert claude.calls == [] and router.mention_calls == 1  # no Claude call
    view = service.get(chat["id"])
    assert view["title"] == "@scout find 5 fraud stories"
    user = next(m for m in view["messages"] if m["id"] == msg["id"])
    assert user["metadata"] == {"fast_path": True, "claude": False}
    plan_msg = next(m for m in view["messages"] if m["metadata"].get("kind") == "plan")
    plan = view["plans"][str(plan_msg["metadata"]["plan_id"])]
    assert plan["status"] == "pending" and plan["chat_id"] == chat["id"]
    assert [(s["agent"], s["params"]) for s in plan["steps"]] == [
        ("scout", {"mode": "both", "topic": "fraud", "limit": 5})
    ]


@pytest.mark.parametrize(
    "parsed",
    [
        MentionParse(agent="scout", params={}, confident=False),  # ambiguous
        MentionParse(agent="outlier", params={}, confident=True),  # wrong agent
        MentionParse(agent="scout", params={"limit": 0}, confident=True),  # invalid params
        ProviderError("groq", "down"),  # parse failed
    ],
)
async def test_mention_falls_back_to_orchestrator(svc: Any, parsed: Any) -> None:
    service, _plans, claude, router, _ = svc
    router.mention = parsed
    chat = service.create()
    msg = await service.send(chat["id"], "@scout something vague")
    await service.drain()
    assert len(claude.calls) == 1 and claude.calls[0]["prompt"] == "@scout something vague"
    user = next(m for m in service.get(chat["id"])["messages"] if m["id"] == msg["id"])
    assert user["metadata"]["fast_path"] is False and user["metadata"]["fallback_reason"]


async def test_researcher_mention_says_not_built(svc: Any) -> None:
    service, _, claude, router, _ = svc
    chat = service.create()
    await service.send(chat["id"], "@researcher Circuit City")
    await service.drain()
    assert claude.calls == [] and router.mention_calls == 0
    notice = service.get(chat["id"])["messages"][-1]
    assert notice["role"] == "system" and "Phase 6" in notice["content"]


# ---------------------------------------------------------------------------- orchestrator turns
async def test_turn_streams_saves_reply_logs_usage_and_resumes(engine: Any, svc: Any) -> None:
    service, _, claude, _, bus = svc
    chat = service.create()
    await service.send(chat["id"], "what fraud stories do we have?")
    await service.drain()
    deltas = [e.data["text"] for e in bus.recent() if e.type == "chat.delta"]
    assert "".join(deltas).strip() == "Proposed a plan."
    reply = service.get(chat["id"])["messages"][-1]
    assert reply["role"] == "assistant" and reply["content"] == "Proposed a plan."
    assert reply["metadata"]["streaming"] is False and reply["metadata"]["turns"] == 2
    with Session(engine) as s:
        usage = s.exec(select(ProviderUsage).where(ProviderUsage.provider == "claude")).one()
    assert (usage.turns, usage.latency_ms, usage.chat_id, usage.ok) == (2, 1200, chat["id"], True)

    await service.send(chat["id"], "and tech graveyard?")
    await service.drain()
    first, second = claude.calls
    assert first["resume"] is False and second["resume"] is True
    assert first["session"] == second["session"]  # one Claude session per chat
    assert service.get(chat["id"])["has_session"] is True


async def test_claude_unavailable_shows_error_without_calling(svc: Any) -> None:
    service, _, claude, _, _ = svc
    service.claude_status["value"] = ClaudeStatus(
        installed=True, logged_in=False, detail="Run `claude auth login`."
    )
    chat = service.create()
    await service.send(chat["id"], "hello")
    await service.drain()
    assert claude.calls == []
    last = service.get(chat["id"])["messages"][-1]
    assert last["role"] == "system" and "claude auth login" in last["content"]


# ---------------------------------------------------------------------------- results loop
async def test_two_step_plan_results_flow_back_to_orchestrator(svc: Any) -> None:
    service, plans, claude, _, _ = svc
    chat = service.create()

    async def propose(chat_id: int) -> None:  # what Claude does via the MCP tool
        mcp_server._services["test_chat_id"] = chat_id
        async with Client(mcp_server.mcp) as client:
            await client.call_tool(
                "propose_plan",
                {
                    "summary": "10 fraud stories + Company Man outliers",
                    "steps": [
                        {"agent": "scout", "params": {"topic": "fraud", "limit": 10}},
                        {"agent": "outlier", "params": {"channels": ["@companyman114"]}},
                    ],
                },
            )

    claude.on_call = propose
    await service.send(
        chat["id"], "find me 10 fraud stories and check what's working on Company Man"
    )
    await service.drain()
    view = service.get(chat["id"])
    plan_msgs = [m for m in view["messages"] if m["metadata"].get("kind") == "plan"]
    assert len(plan_msgs) == 1  # exactly one plan card...
    plan = view["plans"][str(plan_msgs[0]["metadata"]["plan_id"])]
    assert [s["agent"] for s in plan["steps"]] == ["scout", "outlier"]  # ...with two steps

    claude.on_call = None
    claude.reply = "Summary: 2 fraud stories, Sears video is the standout."
    await plans.approve(plan["id"])
    await wait_for(lambda: len(claude.calls) == 2)
    await service.drain()
    result_msg = next(m for m in service.get(chat["id"])["messages"] if m["role"] == "agent")
    meta = result_msg["metadata"]
    assert meta["kind"] == "result" and meta["status"] == "done" and meta["fed"] is True
    assert [s["agent"] for s in meta["steps"]] == ["scout", "outlier"]
    assert meta["steps"][0]["items"][0] == {
        "label": "Theranos fraud",
        "detail": "score 8.1",
        "href": "/stories?story=1",
        "id": 1,
    }
    engine_prompt = claude.calls[1]["prompt"]
    assert engine_prompt.startswith("[engine] Plan #") and "#1 Theranos fraud" in engine_prompt
    assert "Why Sears died" in engine_prompt and claude.calls[1]["resume"] is True
    assert service.get(chat["id"])["messages"][-1]["content"].startswith("Summary:")


async def test_fast_path_results_wait_for_next_claude_turn(svc: Any) -> None:
    service, plans, claude, _, _ = svc
    chat = service.create()
    await service.send(chat["id"], "@scout find 5 fraud stories")
    await service.drain()
    plan_id = next(
        m["metadata"]["plan_id"]
        for m in service.get(chat["id"])["messages"]
        if m["metadata"].get("kind") == "plan"
    )
    await plans.approve(plan_id)
    await wait_for(lambda: "agent" in roles(service, chat["id"]))
    await service.drain()
    assert claude.calls == []  # no Claude spend for a fast-path run
    await service.send(chat["id"], "which is best?")
    await service.drain()
    prompt = claude.calls[0]["prompt"]
    assert prompt.startswith("[engine] Plan #") and prompt.endswith("[owner] which is best?")
    result = next(m for m in service.get(chat["id"])["messages"] if m["role"] == "agent")
    assert result["metadata"]["fed"] is True


# ---------------------------------------------------------------------------- MCP tools
async def test_mcp_registry_and_story_tools(engine: Any, svc: Any) -> None:
    service, _, _, _, _ = svc
    assert mcp_server.allowed_tools() == [
        f"mcp__wyrd__{n}"
        for n in (
            "propose_plan",
            "list_stories",
            "get_story",
            "update_story",
            "search_memory",
            "list_runs",
            "get_run",
        )
    ]
    with Session(engine) as s:
        s.add(Story(slug="theranos", title="Theranos", hook="A blood test that never worked"))
        s.commit()
    chat = service.create()
    mcp_server._services["test_chat_id"] = chat["id"]
    async with Client(mcp_server.mcp) as client:
        listed = (await client.call_tool("list_stories", {"query": "blood"})).data
        assert [r["title"] for r in listed] == ["Theranos"]
        applied = (
            await client.call_tool("update_story", {"story_id": 1, "fields": {"notes": "good"}})
        ).data
        assert applied["applied"] is True
        moved = (
            await client.call_tool(
                "update_story", {"story_id": 1, "fields": {"status": "Shortlisted"}}
            )
        ).data
        assert moved["needs_approval"] is True and moved["status"] == "pending"
        assert moved["steps"][0]["agent"] == "story_update"
    with Session(engine) as s:
        story = s.get(Story, 1)
        assert story and story.status == "Inbox" and story.notes == "good"  # status waits
    await service.drain()
    assert any(m["metadata"].get("kind") == "plan" for m in service.get(chat["id"])["messages"])


def test_agents_brief_lists_params_and_hides_internal_agents() -> None:
    brief = mcp_server.agents_brief()
    assert "@scout" in brief and "limit" in brief and "@outlier" in brief
    assert "story_update" not in brief and "@demo" not in brief
    assert "@researcher" in brief and "not built yet" in brief


async def test_token_guard_rejects_unknown_callers() -> None:
    sent: list[dict[str, Any]] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        sent.append({"reached": True})

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    guard = mcp_server.TokenGuard(app)
    await guard({"type": "http", "headers": [(b"x-wyrd-token", b"nope")]}, None, send)
    assert sent[0]["status"] == 401 and {"reached": True} not in sent
    sent.clear()
    token = mcp_server.TOKEN.encode()
    await guard({"type": "http", "headers": [(b"x-wyrd-token", token)]}, None, send)
    assert sent == [{"reached": True}]


# ---------------------------------------------------------------------------- memory
async def test_memory_search_recalls_other_chats_and_stories(engine: Any, svc: Any) -> None:
    service, _, _, router, _ = svc
    old = service.create()
    await service.send(old["id"], "We found Theranos and Enron fraud stories yesterday")
    with Session(engine) as s:
        s.add(Story(slug="enron", title="Enron", hook="Fraud at scale"))
        s.commit()
    await service.drain()
    assert await memory.backfill(engine) >= 1  # the story had no vector yet

    new = service.create()
    found = await memory.search(engine, "fraud stories", exclude_chat_id=new["id"])
    types = {(r["type"], r.get("chat_id") or r.get("story_id")) for r in found["results"]}
    assert ("message", old["id"]) in types and ("story", 1) in types
    assert found["semantic"] is True
    hit = next(r for r in found["results"] if r["type"] == "message")
    assert set(hit["match"]) == {"keyword", "semantic"} and hit["chat_title"]

    # The current chat's own messages are excluded; keyword search still works without vectors.
    router.embed_fails = True
    own = await memory.search(engine, "Theranos", exclude_chat_id=old["id"])
    assert own["semantic"] is False and all(r["type"] != "message" for r in own["results"])


def test_fts_query_is_injection_safe() -> None:
    assert memory.fts_query('fraud" OR x NEAR(') == '"fraud"* OR "or"* OR "near"*'
    assert memory.fts_query("a !") == ""


# ---------------------------------------------------------------------------- stream parsing
def test_parse_stream_json_lines() -> None:
    acc: dict[str, Any] = {}
    lines = [
        {
            "type": "system",
            "subtype": "init",
            "session_id": "s1",
            "model": "m",
            "mcp_servers": [{"name": "wyrd", "status": "connected"}],
        },
        {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}},
        },
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}]}},
        {
            "type": "assistant",
            "message": {
                "content": [{"type": "tool_use", "name": "mcp__wyrd__propose_plan", "input": {}}]
            },
        },
        {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed_warning"}},
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "duration_ms": 900,
            "num_turns": 3,
            "result": "Hi",
            "session_id": "s1",
            "usage": {"input_tokens": 10, "cache_read_input_tokens": 5, "output_tokens": 4},
        },
    ]
    events = [e for line in lines for e in orchestrator.parse_line(json.dumps(line), acc)]
    assert [e.kind for e in events] == ["text", "tool", "rate_limit", "result"]
    assert events[1].tool == "propose_plan" and orchestrator.mcp_ready(acc)
    r = orchestrator.finish(acc, 0, "", 1000)
    assert (r.ok, r.text, r.turns, r.tokens_in, r.tokens_out, r.tools) == (
        True,
        "Hi",
        3,
        15,
        4,
        ["propose_plan"],
    )
    assert r.rate_limit == {"status": "allowed_warning"}


def test_failed_turn_explains_login() -> None:
    r = orchestrator.finish({}, 1, "Error: Not logged in", 50)
    assert not r.ok and r.error and "claude auth login" in r.error


def test_command_uses_tight_allowlist() -> None:
    cmd = orchestrator.build_command("claude", OrchestratorConfig(), 7, "sid", resume=False)
    joined = " ".join(cmd)
    assert cmd[cmd.index("--tools") + 1] == ""  # no built-in tools: no shell, no edits
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert "--strict-mcp-config" in cmd and "--session-id sid" in joined
    allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
    assert allowed == mcp_server.allowed_tools()
    mcp = json.loads(cmd[cmd.index("--mcp-config") + 1])["mcpServers"]["wyrd"]
    assert mcp["headers"]["x-wyrd-chat"] == "7" and mcp["url"].endswith("/mcp/")
    resumed = orchestrator.build_command("claude", OrchestratorConfig(), 7, "sid", resume=True)
    assert "--resume" in resumed and "--session-id" not in resumed
    assert "Company Man = @companyman114" in cmd[cmd.index("--system-prompt") + 1]
