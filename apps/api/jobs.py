"""DB-backed job queue and runner (SPEC §3 "Jobs", §6).

Runs live in `agent_runs`. The runner loop (started in the FastAPI lifespan) claims queued
runs FIFO up to `max_concurrent_runs`, executes the agent's `run(ctx)` as an asyncio task,
streams logs to `run_logs` + SSE, and records the result. Cancelling a running run cancels
its task; cancelling a queued run just marks it. Runs are only ever enqueued from an approved
plan (see plans.py) — there is no "start a run" endpoint.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import traceback
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session, col, select

from apps.api.agents.registry import AGENTS, AgentFn
from apps.api.db.models import AgentRun, RunLog, RunStatus, utcnow
from apps.api.events import EventBus
from apps.api.runctx import current_run_logger, current_run_once

log = logging.getLogger("wyrd.jobs")

FINAL = {RunStatus.SUCCEEDED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}
RunFinishedHook = Callable[[AgentRun], Awaitable[None]]


def run_payload(run: AgentRun) -> dict[str, Any]:
    return {
        "run_id": run.id,
        "agent": run.agent,
        "status": run.status,
        "current_step": run.current_step,
        "progress": run.progress,
        "plan_id": run.plan_id,
        "error": run.error,
    }


class RunContext:
    """What an agent sees: its params, a logger, and progress reporting."""

    def __init__(self, runner: JobRunner, run: AgentRun) -> None:
        assert run.id is not None
        self.run_id: int = run.id
        self.agent = run.agent
        self.params: dict[str, Any] = dict(run.params or {})
        self._runner = runner

    def log(self, level: str, message: str, data: dict[str, Any] | None = None) -> None:
        self._runner.write_log(self.run_id, level, message, data)

    def step(self, name: str, progress: float | None = None) -> None:
        self._runner.update_progress(self.run_id, name, progress)


class JobRunner:
    def __init__(
        self,
        engine: Engine,
        bus: EventBus,
        *,
        max_concurrent: int = 2,
        poll_interval_s: float = 2.0,
        resolve: Callable[[str], AgentFn] | None = None,
    ) -> None:
        self.engine = engine
        self.bus = bus
        self.max_concurrent = max_concurrent
        self.poll_interval_s = poll_interval_s
        self._resolve = resolve or (lambda name: AGENTS[name].load_runner())
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._wake = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None
        self._on_finished: list[RunFinishedHook] = []

    # ------------------------------------------------------------------ lifecycle
    def on_finished(self, hook: RunFinishedHook) -> None:
        self._on_finished.append(hook)

    async def start(self) -> None:
        self._recover_interrupted()
        self._loop_task = asyncio.create_task(self._loop(), name="job-runner")

    async def stop(self) -> None:
        if self._loop_task:
            self._loop_task.cancel()
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        if self._loop_task:
            await asyncio.gather(self._loop_task, return_exceptions=True)

    def _recover_interrupted(self) -> None:
        """Runs left 'running' by a crash or restart can't resume; mark them failed."""
        with Session(self.engine) as s:
            stale = s.exec(select(AgentRun).where(AgentRun.status == RunStatus.RUNNING.value)).all()
            for run in stale:
                run.status = RunStatus.FAILED.value
                run.error = "Interrupted: the engine stopped while this run was in progress."
                run.finished_at = utcnow()
                s.add(run)
            s.commit()

    # ------------------------------------------------------------------ queue
    def enqueue(self, agent: str, params: dict[str, Any], plan_id: int | None = None) -> AgentRun:
        run = AgentRun(
            agent=agent,
            params=params,
            plan_id=plan_id,
            status=RunStatus.QUEUED.value,
            current_step="Queued",
        )
        with Session(self.engine) as s:
            s.add(run)
            s.commit()
            s.refresh(run)
        self.bus.publish("run.status", **run_payload(run))
        self._wake.set()
        return run

    async def cancel(self, run_id: int) -> AgentRun | None:
        with Session(self.engine) as s:
            run = s.get(AgentRun, run_id)
            if run is None:
                return None
            if run.status in FINAL:
                return run
            if run.status == RunStatus.QUEUED.value:
                run.status = RunStatus.CANCELLED.value
                run.finished_at = utcnow()
                run.current_step = "Cancelled before start"
                s.add(run)
                s.commit()
                s.refresh(run)
                self.bus.publish("run.status", **run_payload(run))
                await self._finished(run)
                return run
        task = self._tasks.get(run_id)
        if task is not None:
            self.write_log(run_id, "warn", "Cancellation requested")
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        with Session(self.engine) as s:
            return s.get(AgentRun, run_id)

    async def _loop(self) -> None:
        while True:
            try:
                self._claim_and_start()
            except Exception:
                log.exception("job runner loop error")
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_interval_s)

    def _claim_and_start(self) -> None:
        free = self.max_concurrent - len(self._tasks)
        if free <= 0:
            return
        with Session(self.engine) as s:
            queued = s.exec(
                select(AgentRun)
                .where(AgentRun.status == RunStatus.QUEUED.value)
                .order_by(col(AgentRun.id))
                .limit(free)
            ).all()
            for run in queued:
                run.status = RunStatus.RUNNING.value
                run.started_at = utcnow()
                run.current_step = "Starting"
                s.add(run)
            s.commit()
            for run in queued:
                s.refresh(run)
        for run in queued:
            assert run.id is not None
            self.bus.publish("run.status", **run_payload(run))
            self._tasks[run.id] = asyncio.create_task(self._execute(run), name=f"run-{run.id}")

    # ------------------------------------------------------------------ execution
    async def _execute(self, run: AgentRun) -> None:
        assert run.id is not None
        run_id = run.id
        ctx = RunContext(self, run)
        token = current_run_logger.set(
            lambda lvl, msg, data: self.write_log(run_id, lvl, msg, data)
        )
        once_token = current_run_once.set(set())
        status, result, error = RunStatus.FAILED.value, None, None
        try:
            self.write_log(run_id, "info", f"Started @{run.agent}", {"params": run.params})
            fn = self._resolve(run.agent)
            result = await fn(ctx)
            status = RunStatus.SUCCEEDED.value
            self.write_log(run_id, "info", "Finished", None)
        except asyncio.CancelledError:
            status = RunStatus.CANCELLED.value
            self.write_log(run_id, "warn", "Cancelled")
        except Exception as e:  # a failing agent must never take down the runner
            error = f"{type(e).__name__}: {e}"
            self.write_log(run_id, "error", error, {"traceback": traceback.format_exc(limit=5)})
        finally:
            current_run_logger.reset(token)
            current_run_once.reset(once_token)
            self._tasks.pop(run_id, None)
            with Session(self.engine) as s:
                row = s.get(AgentRun, run_id)
                if row is not None:
                    row.status = status
                    row.finished_at = utcnow()
                    row.result = result
                    row.error = error
                    if status != RunStatus.SUCCEEDED.value:
                        row.current_step = status.capitalize()
                    s.add(row)
                    s.commit()
                    s.refresh(row)
                    self.bus.publish("run.status", **run_payload(row))
                    await self._finished(row)
            self._wake.set()

    async def _finished(self, run: AgentRun) -> None:
        for hook in self._on_finished:
            try:
                await hook(run)
            except Exception:
                log.exception("run-finished hook failed for run %s", run.id)

    # ------------------------------------------------------------------ logging/progress
    def write_log(
        self, run_id: int, level: str, message: str, data: dict[str, Any] | None = None
    ) -> None:
        entry = RunLog(run_id=run_id, level=level, message=message[:2000], data=data)
        with Session(self.engine) as s:
            s.add(entry)
            s.commit()
            s.refresh(entry)
        self.bus.publish(
            "run.log",
            run_id=run_id,
            id=entry.id,
            level=level,
            message=entry.message,
            ts=entry.ts.isoformat(),
        )

    def update_progress(self, run_id: int, step: str, progress: float | None) -> None:
        with Session(self.engine) as s:
            run = s.get(AgentRun, run_id)
            if run is None:
                return
            run.current_step = step[:300]
            if progress is not None:
                run.progress = max(0.0, min(1.0, progress))
            s.add(run)
            s.commit()
            s.refresh(run)
            self.bus.publish("run.status", **run_payload(run))

    @property
    def active_run_ids(self) -> list[int]:
        return list(self._tasks)
