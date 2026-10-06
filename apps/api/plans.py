"""Plans: the only way agent runs start (CLAUDE.md hard rule 3).

A plan is created `pending` with ordered steps. Approving it (by the owner, or automatically
when every step's agent has auto-approve on) enqueues step 1; each step starts when the
previous one succeeds. A failed or cancelled step skips the rest.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import Engine
from sqlmodel import Session, col, select

from apps.api.agents.registry import AGENTS
from apps.api.config import load_providers
from apps.api.db.models import (
    AgentRun,
    Plan,
    PlanStatus,
    PlanStep,
    RunStatus,
    StepStatus,
    utcnow,
)
from apps.api.events import EventBus
from apps.api.jobs import JobRunner
from apps.api.settings_store import auto_approve_key, get_setting

log = logging.getLogger(__name__)


class PlanError(ValueError):
    pass


class StepIn(BaseModel):
    agent: str = Field(description='Agent name, e.g. "scout"')
    params: dict[str, Any] = {}

    @field_validator("agent")
    @classmethod
    def _bare_name(cls, value: str) -> str:
        return value.strip().lstrip("@").lower()  # "@scout" → "scout"


class PlanIn(BaseModel):
    summary: str
    steps: list[StepIn]
    chat_id: int | None = None


def validate_step(step: StepIn) -> dict[str, Any]:
    info = AGENTS.get(step.agent)
    if info is None or not info.available:
        raise PlanError(f"unknown agent @{step.agent}")
    if info.runner is None:
        raise PlanError(f"@{step.agent} isn't built yet (arrives in {info.arrives_in or 'v2'})")
    if info.params_model is None:
        return dict(step.params)
    try:
        return info.params_model.model_validate(step.params).model_dump(exclude_none=True)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "params"
        raise PlanError(f"@{step.agent} {where}: {first['msg']}") from e


def step_providers(agent: str) -> list[str]:
    """Providers a step may use, primary first: its router tasks' routes (from
    providers.yaml), then YouTube and Claude when it uses them."""
    info = AGENTS[agent]
    try:
        routes = load_providers().tasks
    except Exception:  # config errors must not break showing a plan
        routes = {}
    names: list[str] = []
    for task in info.tasks:
        for step in routes.get(task, []):
            if step.provider not in names:
                names.append(step.provider)
    if info.uses_youtube_quota:
        names.append("youtube")
    if info.uses_claude:
        names.append("claude")
    return names


def _safe_estimate(agent: str, params: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return AGENTS[agent].estimate_for(params)
    except Exception:  # an estimate must never break showing a plan
        return None


PlanHook = Callable[[dict[str, Any]], None]


class PlanService:
    def __init__(self, engine: Engine, bus: EventBus, runner: JobRunner) -> None:
        self.engine = engine
        self.bus = bus
        self.runner = runner
        runner.on_finished(self._on_run_finished)
        # Chat integration (Phase 5): called with the plan view. Hooks must not block; the
        # chat service schedules its own async work.
        self._on_created: list[PlanHook] = []
        self._on_done: list[PlanHook] = []

    def on_created(self, hook: PlanHook) -> None:
        self._on_created.append(hook)

    def on_done(self, hook: PlanHook) -> None:
        """Called when a plan reaches done/failed/cancelled."""
        self._on_done.append(hook)

    def _call(self, hooks: list[PlanHook], plan_id: int) -> None:
        view = self.get(plan_id)
        if view is None:
            return
        for hook in hooks:
            try:
                hook(view)
            except Exception:
                log.exception("plan hook failed for plan %s", plan_id)

    # ------------------------------------------------------------------ queries
    def get(self, plan_id: int) -> dict[str, Any] | None:
        with Session(self.engine) as s:
            plan = s.get(Plan, plan_id)
            return None if plan is None else self._view(s, plan)

    def list(self, status: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        with Session(self.engine) as s:
            stmt = select(Plan).order_by(col(Plan.id).desc()).limit(limit)
            if status:
                stmt = stmt.where(Plan.status == status)
            return [self._view(s, p) for p in s.exec(stmt).all()]

    def _view(self, s: Session, plan: Plan) -> dict[str, Any]:
        steps = s.exec(
            select(PlanStep).where(PlanStep.plan_id == plan.id).order_by(col(PlanStep.order))
        ).all()
        return {
            **plan.model_dump(mode="json"),
            "steps": [
                {
                    **step.model_dump(mode="json"),
                    "uses_claude": AGENTS[step.agent].uses_claude,
                    "uses_youtube_quota": AGENTS[step.agent].uses_youtube_quota,
                    "estimate": _safe_estimate(step.agent, step.params or {}),
                    "providers": step_providers(step.agent),
                }
                for step in steps
            ],
        }

    # ------------------------------------------------------------------ commands
    async def create(self, data: PlanIn) -> dict[str, Any]:
        if not data.steps:
            raise PlanError("a plan needs at least one step")
        params = [validate_step(step) for step in data.steps]
        with Session(self.engine) as s:
            plan = Plan(chat_id=data.chat_id, summary=data.summary, status=PlanStatus.PENDING.value)
            s.add(plan)
            s.commit()
            s.refresh(plan)
            assert plan.id is not None
            plan_id = plan.id
            for i, (step, p) in enumerate(zip(data.steps, params, strict=True), start=1):
                s.add(PlanStep(plan_id=plan_id, order=i, agent=step.agent, params=p))
            s.commit()
        self.bus.publish(
            "plan.status", plan_id=plan_id, status=PlanStatus.PENDING.value, chat_id=data.chat_id
        )
        self._call(self._on_created, plan_id)
        if all(get_setting(self.engine, auto_approve_key(st.agent), False) for st in data.steps):
            return await self.approve(plan_id, auto=True)
        view = self.get(plan_id)
        assert view is not None
        return view

    async def approve(
        self, plan_id: int, edits: dict[int, dict[str, Any]] | None = None, auto: bool = False
    ) -> dict[str, Any]:
        """Approve a pending plan. `edits` maps step order → replacement params."""
        with Session(self.engine) as s:
            plan = s.get(Plan, plan_id)
            if plan is None:
                raise PlanError(f"no plan {plan_id}")
            if plan.status != PlanStatus.PENDING.value:
                raise PlanError(f"plan {plan_id} is {plan.status}, not pending")
            steps = s.exec(select(PlanStep).where(PlanStep.plan_id == plan_id)).all()
            for step in steps:
                if edits and step.order in edits:
                    step.params = validate_step(StepIn(agent=step.agent, params=edits[step.order]))
                    s.add(step)
            plan.status = PlanStatus.APPROVED.value
            plan.decided_at = utcnow()
            s.add(plan)
            s.commit()
        self.bus.publish(
            "plan.status", plan_id=plan_id, status=PlanStatus.APPROVED.value, auto=auto
        )
        self._start_next(plan_id)
        view = self.get(plan_id)
        assert view is not None
        return view

    async def cancel(self, plan_id: int) -> dict[str, Any]:
        with Session(self.engine) as s:
            plan = s.get(Plan, plan_id)
            if plan is None:
                raise PlanError(f"no plan {plan_id}")
            status = plan.status
            running = s.exec(
                select(PlanStep).where(
                    PlanStep.plan_id == plan_id,
                    col(PlanStep.status).in_([StepStatus.QUEUED.value, StepStatus.RUNNING.value]),
                )
            ).all()
        if status == PlanStatus.PENDING.value:
            self._finish_plan(plan_id, PlanStatus.CANCELLED.value)
        elif status == PlanStatus.APPROVED.value:
            for step in running:
                if step.run_id is not None:
                    await self.runner.cancel(step.run_id)  # hook finishes the plan
            if not running:
                self._finish_plan(plan_id, PlanStatus.CANCELLED.value)
        view = self.get(plan_id)
        assert view is not None
        return view

    # ------------------------------------------------------------------ progression
    def _start_next(self, plan_id: int) -> None:
        with Session(self.engine) as s:
            step = s.exec(
                select(PlanStep)
                .where(PlanStep.plan_id == plan_id, PlanStep.status == StepStatus.PENDING.value)
                .order_by(col(PlanStep.order))
            ).first()
            if step is None:
                plan_done = True
            else:
                plan_done = False
                run = self.runner.enqueue(step.agent, dict(step.params or {}), plan_id=plan_id)
                step.run_id = run.id
                step.status = StepStatus.QUEUED.value
                s.add(step)
                s.commit()
        if plan_done:
            self._finish_plan(plan_id, PlanStatus.DONE.value)

    async def _on_run_finished(self, run: AgentRun) -> None:
        if run.plan_id is None:
            return
        with Session(self.engine) as s:
            step = s.exec(select(PlanStep).where(PlanStep.run_id == run.id)).first()
            if step is None:
                return
            step.status = run.status
            s.add(step)
            s.commit()
        if run.status == RunStatus.SUCCEEDED.value:
            self._start_next(run.plan_id)
        else:
            outcome = (
                PlanStatus.CANCELLED.value
                if run.status == RunStatus.CANCELLED.value
                else PlanStatus.FAILED.value
            )
            self._finish_plan(run.plan_id, outcome)

    def _finish_plan(self, plan_id: int, status: str) -> None:
        with Session(self.engine) as s:
            plan = s.get(Plan, plan_id)
            if plan is None:
                return
            plan.status = status
            if plan.decided_at is None:
                plan.decided_at = utcnow()
            s.add(plan)
            for step in s.exec(select(PlanStep).where(PlanStep.plan_id == plan_id)).all():
                if step.status == StepStatus.PENDING.value:
                    step.status = StepStatus.SKIPPED.value
                    s.add(step)
            s.commit()
        self.bus.publish("plan.status", plan_id=plan_id, status=status)
        self._call(self._on_done, plan_id)


def run_view(run: AgentRun, logs: list[Any] | None = None) -> dict[str, Any]:
    return {**run.model_dump(mode="json"), **({"logs": logs} if logs is not None else {})}
