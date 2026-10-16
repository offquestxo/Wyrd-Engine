"""Chat threads with the orchestrator (SPEC §5).

- A user message starting with @scout / @outlier / @researcher takes the **fast path**: Groq's
  `parse_mention` turns it into params and a single-step plan is created. No Claude call. If
  parsing fails or is ambiguous, the message goes to the orchestrator instead.
- Any other message is one orchestrator turn (`agents/orchestrator.py`): Claude Code headless,
  one session per chat, resumed every turn. Text streams to the UI over SSE (`chat.delta`).
- Plans created for a chat (by Claude's `propose_plan`, the fast path, or `update_story`)
  appear in the thread as plan-card messages.
- **Results loop:** when an approved plan finishes, a compact result card is posted. If the
  chat has a Claude session, the orchestrator gets an `[engine]` turn to summarize and suggest
  next steps; otherwise (fast-path-only chats) the result is fed to Claude with the next turn,
  so @mention runs never spend Claude usage on their own.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session, col, func, select

from apps.api import memory
from apps.api.agents import orchestrator
from apps.api.agents.registry import AGENTS
from apps.api.config import OrchestratorConfig
from apps.api.db.models import AgentRun, Chat, Message, Plan, utcnow
from apps.api.events import EventBus
from apps.api.plans import PlanError, PlanIn, PlanService, StepIn
from apps.api.providers.base import ProviderError
from apps.api.providers.router import get_router
from apps.api.providers.usage import UsageLog
from apps.api.settings_store import set_setting
from apps.api.system import ClaudeStatus

log = logging.getLogger(__name__)

MENTION = re.compile(r"^\s*@(scout|outlier|researcher)\b", re.IGNORECASE)
TITLE_CHARS = 60
RESULT_ITEMS = 5
QUIET_AGENTS = {"story_update", "demo"}  # their results don't need an orchestrator summary

ClaudeCheck = Callable[[], Awaitable[ClaudeStatus]]
TurnRunner = Callable[..., Any]  # orchestrator.run_turn (swappable in tests)


class ChatError(ValueError):
    pass


def message_view(m: Message) -> dict[str, Any]:
    return {
        "id": m.id,
        "chat_id": m.chat_id,
        "role": m.role,
        "content": m.content,
        "metadata": m.metadata_ or {},
        "created_at": m.created_at.isoformat(),
    }


def chat_view(c: Chat, **extra: Any) -> dict[str, Any]:
    return {
        "id": c.id,
        "title": c.title,
        "has_session": bool(c.claude_session_id),
        "created_at": c.created_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
    } | extra


# ---------------------------------------------------------------------------- results
def step_items(agent: str, result: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Top items of a run for the result card, each with a link to its full view."""
    result = result or {}
    if agent == "scout":
        return [
            {
                "label": s.get("title"),
                "detail": f"score {s['score']}" if s.get("score") is not None else s.get("mode"),
                "href": f"/stories?story={s['id']}",
                "id": s.get("id"),
            }
            for s in (result.get("stories") or [])[:RESULT_ITEMS]
        ]
    if agent == "outlier":
        return [
            {
                "label": v.get("title"),
                "detail": f"{v.get('channel')} · {v.get('outlier_score')}× · "
                f"{'Short' if v.get('is_short') else 'long'}",
                "href": "/outliers",
                "id": v.get("video_id"),
            }
            for v in (result.get("top") or [])[:RESULT_ITEMS]
        ]
    if agent == "story_update" and result.get("story_id"):
        return [{"label": "Open story", "href": f"/stories?story={result['story_id']}"}]
    return []


def results_text(plan: dict[str, Any], steps: list[dict[str, Any]]) -> str:
    """Compact plain-text summary of a finished plan (fed to Claude and searchable)."""
    lines = [f"Plan #{plan['id']} {plan['status']}: {plan.get('summary') or ''}".strip()]
    for st in steps:
        head = f"- @{st['agent']} (run #{st['run_id']}) {st['status']}"
        if st.get("summary"):
            head += f": {st['summary']}"
        if st.get("error"):
            head += f" — error: {st['error']}"
        lines.append(head)
        for item in st.get("items", []):
            ident = f"#{item['id']} " if isinstance(item.get("id"), int) else ""
            detail = f" ({item['detail']})" if item.get("detail") else ""
            lines.append(f"  • {ident}{item['label']}{detail}")
    return "\n".join(lines)


class ChatService:
    def __init__(
        self,
        engine: Engine,
        bus: EventBus,
        plans: PlanService,
        cfg: OrchestratorConfig,
        claude_check: ClaudeCheck,
        turn_runner: TurnRunner | None = None,
    ) -> None:
        self.engine = engine
        self.bus = bus
        self.plans = plans
        self.cfg = cfg
        self.claude_check = claude_check
        self.turn_runner = turn_runner or orchestrator.run_turn
        self.usage = UsageLog(engine)
        self._locks: dict[int, asyncio.Lock] = {}
        self._busy: set[int] = set()
        self._tasks: set[asyncio.Task[Any]] = set()
        plans.on_created(self._plan_created)
        plans.on_done(self._plan_done)

    # ------------------------------------------------------------------ queries
    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with Session(self.engine) as s:
            chats = s.exec(select(Chat).order_by(col(Chat.updated_at).desc()).limit(limit)).all()
            counts: dict[int, int] = {
                cid: int(n)
                for cid, n in s.exec(
                    select(Message.chat_id, func.count(col(Message.id))).group_by(
                        col(Message.chat_id)
                    )
                ).all()
            }
            out = []
            for c in chats:
                last = s.exec(
                    select(Message)
                    .where(Message.chat_id == c.id, col(Message.role).in_(["user", "assistant"]))
                    .order_by(col(Message.id).desc())
                ).first()
                out.append(
                    chat_view(
                        c,
                        message_count=counts.get(c.id or 0, 0),
                        preview=(last.content[:120] if last else ""),
                        busy=c.id in self._busy,
                    )
                )
            return out

    def get(self, chat_id: int) -> dict[str, Any] | None:
        with Session(self.engine) as s:
            chat = s.get(Chat, chat_id)
            if chat is None:
                return None
            msgs = s.exec(
                select(Message).where(Message.chat_id == chat_id).order_by(col(Message.id))
            ).all()
            plan_ids = [
                int(m.metadata_["plan_id"])
                for m in msgs
                if m.metadata_ and m.metadata_.get("kind") == "plan"
            ]
        plans = {pid: self.plans.get(pid) for pid in plan_ids}
        return chat_view(
            chat,
            busy=chat_id in self._busy,
            messages=[message_view(m) for m in msgs],
            plans={str(k): v for k, v in plans.items() if v is not None},
        )

    # ------------------------------------------------------------------ commands
    def create(self, title: str | None = None) -> dict[str, Any]:
        with Session(self.engine) as s:
            chat = Chat(title=(title or "New chat")[:TITLE_CHARS])
            s.add(chat)
            s.commit()
            s.refresh(chat)
            view = chat_view(chat, message_count=0, preview="", busy=False)
        self.bus.publish("chat.changed", chat_id=view["id"])
        return view

    def rename(self, chat_id: int, title: str) -> dict[str, Any] | None:
        with Session(self.engine) as s:
            chat = s.get(Chat, chat_id)
            if chat is None:
                return None
            chat.title = title.strip()[:TITLE_CHARS] or chat.title
            s.add(chat)
            s.commit()
            s.refresh(chat)
            view = chat_view(chat)
        self.bus.publish("chat.changed", chat_id=chat_id)
        return view

    def delete(self, chat_id: int) -> bool:
        if chat_id in self._busy:
            raise ChatError("this chat is still replying")
        with Session(self.engine) as s:
            chat = s.get(Chat, chat_id)
            if chat is None:
                return False
            for m in s.exec(select(Message).where(Message.chat_id == chat_id)).all():
                s.delete(m)
            for p in s.exec(select(Plan).where(Plan.chat_id == chat_id)).all():
                p.chat_id = None  # plans and runs stay in history
                s.add(p)
            s.delete(chat)
            s.commit()
        self.bus.publish("chat.changed", chat_id=chat_id, deleted=True)
        return True

    async def send(self, chat_id: int, content: str) -> dict[str, Any]:
        content = content.strip()
        if not content:
            raise ChatError("empty message")
        with Session(self.engine) as s:
            chat = s.get(Chat, chat_id)
            if chat is None:
                raise LookupError(f"no chat {chat_id}")
            first = s.exec(select(Message.id).where(Message.chat_id == chat_id)).first() is None
            if first and chat.title in ("", "New chat"):
                chat.title = re.sub(r"\s+", " ", content)[:TITLE_CHARS]
            chat.updated_at = utcnow()
            s.add(chat)
            s.commit()
        msg = self._add(chat_id, "user", content)
        self._spawn(self._handle(chat_id, content, msg["id"]))
        return msg

    # ------------------------------------------------------------------ internals
    def _spawn(self, coro: Awaitable[Any]) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self, timeout_s: float = 30.0) -> None:
        """Wait for background chat work (tests). Fails loudly instead of hanging."""
        deadline = asyncio.get_running_loop().time() + timeout_s
        while self._tasks:
            remaining = deadline - asyncio.get_running_loop().time()
            _, pending = await asyncio.wait(list(self._tasks), timeout=max(0.0, remaining))
            if pending and asyncio.get_running_loop().time() >= deadline:
                for task in pending:
                    task.print_stack()
                raise TimeoutError(f"{len(pending)} chat task(s) still running after {timeout_s}s")

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)

    def _lock(self, chat_id: int) -> asyncio.Lock:
        return self._locks.setdefault(chat_id, asyncio.Lock())

    def _add(
        self, chat_id: int, role: str, content: str, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with Session(self.engine) as s:
            m = Message(chat_id=chat_id, role=role, content=content, metadata_=metadata)
            s.add(m)
            s.commit()
            s.refresh(m)
            view = message_view(m)
        self.bus.publish("chat.message", chat_id=chat_id, message=view)
        if role in memory.EMBEDDED_ROLES and content.strip():
            self._spawn(memory.embed_message(self.engine, view["id"]))
        return view

    def _update(
        self, message_id: int, content: str | None = None, metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        with Session(self.engine) as s:
            m = s.get(Message, message_id)
            assert m is not None
            if content is not None:
                m.content = content
            if metadata is not None:
                m.metadata_ = (m.metadata_ or {}) | metadata
            s.add(m)
            s.commit()
            s.refresh(m)
            view = message_view(m)
        self.bus.publish("chat.message", chat_id=view["chat_id"], message=view)
        return view

    def _set_busy(self, chat_id: int, busy: bool) -> None:
        (self._busy.add if busy else self._busy.discard)(chat_id)
        self.bus.publish("chat.status", chat_id=chat_id, busy=busy)

    async def _handle(self, chat_id: int, content: str, message_id: int) -> None:
        mention = MENTION.match(content)
        if mention and await self._fast_path(
            chat_id, content, mention.group(1).lower(), message_id
        ):
            return
        await self.turn(chat_id, content)

    async def _fast_path(self, chat_id: int, content: str, agent: str, message_id: int) -> bool:
        """True if handled without Claude."""
        info = AGENTS[agent]
        if info.runner is None:
            self._add(
                chat_id,
                "system",
                f"@{agent} isn't built yet (arrives in {info.arrives_in or 'v2'}).",
                {"kind": "notice"},
            )
            return True
        self._set_busy(chat_id, True)
        try:
            parsed = await get_router().parse_mention(content)
        except ProviderError as e:
            reason = f"couldn't parse the @{agent} request ({e}); asking the orchestrator"
            parsed = None
        finally:
            self._set_busy(chat_id, False)
        if parsed is not None:
            if parsed.agent != agent:
                reason = f"parser picked @{parsed.agent}, not @{agent}; asking the orchestrator"
            elif not parsed.confident:
                reason = "the request looks ambiguous; asking the orchestrator"
            else:
                try:
                    await self.plans.create(
                        PlanIn(
                            summary=content[:200],
                            steps=[StepIn(agent=agent, params=parsed.params)],
                            chat_id=chat_id,
                        )
                    )
                except PlanError as e:
                    reason = f"those @{agent} params didn't validate ({e}); asking the orchestrator"
                else:
                    self._update(message_id, metadata={"fast_path": True, "claude": False})
                    return True
        self._update(message_id, metadata={"fast_path": False, "fallback_reason": reason})
        log.info("chat %s: fast path fell back: %s", chat_id, reason)
        return False

    async def claude_ready(self) -> ClaudeStatus:
        return await self.claude_check()

    async def turn(self, chat_id: int, prompt: str, engine_turn: bool = False) -> None:
        """One orchestrator turn. Queued behind any turn already running in this chat."""
        async with self._lock(chat_id):
            status = await self.claude_ready()
            if not status.usable:
                self._add(
                    chat_id,
                    "system",
                    f"The orchestrator is unavailable: {status.detail}",
                    {"kind": "error", "claude": False, "cli_output": status.output},
                )
                return
            with Session(self.engine) as s:
                chat = s.get(Chat, chat_id)
                if chat is None:
                    return
                resume = bool(chat.claude_session_id)
                session_id = chat.claude_session_id or str(uuid.uuid4())
                pending = s.exec(
                    select(Message).where(Message.chat_id == chat_id, Message.role == "agent")
                ).all()
                unfed = [
                    m
                    for m in pending
                    if (m.metadata_ or {}).get("fed") is False and not engine_turn
                ]
            if unfed:  # results Claude hasn't seen yet (fast-path runs)
                prompt = (
                    "\n\n".join(f"[engine] {m.content}" for m in unfed) + f"\n\n[owner] {prompt}"
                )
            reply = self._add(
                chat_id, "assistant", "", {"streaming": True, "engine_turn": engine_turn}
            )
            self._set_busy(chat_id, True)
            text: list[str] = []
            tools: list[str] = []
            start = time.monotonic()
            result: orchestrator.TurnResult | None = None
            try:
                async for ev in self.turn_runner(self.cfg, chat_id, session_id, resume, prompt):
                    if isinstance(ev, orchestrator.TurnResult):
                        result = ev
                    elif ev.kind == "text":
                        text.append(ev.text)
                        self.bus.publish(
                            "chat.delta", chat_id=chat_id, message_id=reply["id"], text=ev.text
                        )
                    elif ev.kind == "tool":
                        tools.append(ev.tool)
                        self.bus.publish(
                            "chat.tool", chat_id=chat_id, message_id=reply["id"], tool=ev.tool
                        )
                    elif ev.kind == "rate_limit":
                        seen = ev.data | {"seen_at": time.time()}
                        set_setting(self.engine, "claude.rate_limit", seen)
            except Exception as e:  # never let a chat turn crash the app
                log.exception("chat %s: orchestrator turn failed", chat_id)
                result = orchestrator.TurnResult(
                    text="".join(text),
                    ok=False,
                    session_id=None,
                    duration_ms=int((time.monotonic() - start) * 1000),
                    turns=0,
                    tokens_in=0,
                    tokens_out=0,
                    model=None,
                    tools=tools,
                    error=f"{type(e).__name__}: {e}",
                )
            finally:
                self._set_busy(chat_id, False)
            assert result is not None
            final_text = result.text or "".join(text).strip()
            self._update(
                reply["id"],
                content=final_text or ("" if result.ok else "(no reply)"),
                metadata={
                    "streaming": False,
                    "tools": result.tools or tools,
                    "duration_ms": result.duration_ms,
                    "turns": result.turns,
                    "model": result.model,
                    "error": result.error,
                },
            )
            if final_text:
                self._spawn(memory.embed_message(self.engine, reply["id"]))
            self.usage.record(
                provider="claude",
                model=result.model,
                task="orchestrator",
                ok=result.ok,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                latency_ms=result.duration_ms,
                error=result.error,
                turns=result.turns,
                chat_id=chat_id,
            )
            with Session(self.engine) as s:
                chat = s.get(Chat, chat_id)
                if chat is not None:
                    # Keep the session only once Claude has actually created it.
                    if result.ok or resume:
                        chat.claude_session_id = result.session_id or session_id
                    chat.updated_at = utcnow()
                    s.add(chat)
                    if result.ok:
                        for m in unfed:
                            row = s.get(Message, m.id)
                            if row is not None:
                                row.metadata_ = (row.metadata_ or {}) | {"fed": True}
                                s.add(row)
                    s.commit()
            self.bus.publish("chat.changed", chat_id=chat_id)

    # ------------------------------------------------------------------ plan hooks
    def _plan_created(self, plan: dict[str, Any]) -> None:
        chat_id = plan.get("chat_id")
        if not chat_id:
            return
        agents = ", ".join(f"@{s['agent']}" for s in plan["steps"])
        self._add(
            chat_id,
            "system",
            f"Plan #{plan['id']} ({agents}): {plan.get('summary') or ''}",
            {"kind": "plan", "plan_id": plan["id"]},
        )

    def _plan_done(self, plan: dict[str, Any]) -> None:
        chat_id = plan.get("chat_id")
        ran = [s for s in plan["steps"] if s.get("run_id")]
        if not chat_id or not ran:
            return  # cancelled before approval: nothing to report
        self._spawn(self.post_results(chat_id, plan))

    async def post_results(self, chat_id: int, plan: dict[str, Any]) -> None:
        steps: list[dict[str, Any]] = []
        with Session(self.engine) as s:
            for st in plan["steps"]:
                run = s.get(AgentRun, st["run_id"]) if st.get("run_id") else None
                result = run.result if run else None
                steps.append(
                    {
                        "order": st["order"],
                        "agent": st["agent"],
                        "run_id": st.get("run_id"),
                        "status": run.status if run else st["status"],
                        "summary": (result or {}).get("summary"),
                        "error": run.error if run else None,
                        "youtube_units": (result or {}).get("youtube_units"),
                        "items": step_items(st["agent"], result),
                    }
                )
            chat = s.get(Chat, chat_id)
            has_session = bool(chat and chat.claude_session_id)
        quiet = all(st["agent"] in QUIET_AGENTS for st in steps)
        text = results_text(plan, steps)
        self._add(
            chat_id,
            "agent",
            text,
            {
                "kind": "result",
                "plan_id": plan["id"],
                "status": plan["status"],
                "steps": steps,
                "fed": quiet or has_session,  # fast-path chats: Claude sees it next turn
            },
        )
        if has_session and not quiet:
            await self.turn(chat_id, f"[engine] {text}", engine_turn=True)
