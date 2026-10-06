"""Job runner + plans: lifecycle, cancellation, failures, approval rules, usage meters."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, select

from apps.api.config import load_engine, load_providers
from apps.api.db.migrate import migrate_path
from apps.api.db.models import AgentRun, ProviderUsage, RunLog
from apps.api.db.session import make_engine
from apps.api.events import EventBus
from apps.api.jobs import JobRunner
from apps.api.plans import PlanError, PlanIn, PlanService, StepIn
from apps.api.runctx import log_to_current_run
from apps.api.settings_store import auto_approve_key, set_setting
from apps.api.usage_report import build_report, day_start


async def wait_for(check: Callable[[], bool], limit_s: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + limit_s
    while not check():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not met in time")
        await asyncio.sleep(0.02)


@pytest.fixture
def engine(tmp_path: Path) -> Any:
    db = tmp_path / "jobs.db"
    migrate_path(db)
    return make_engine(db)


@pytest.fixture
async def stack(engine: Any) -> AsyncIterator[tuple[JobRunner, PlanService, EventBus]]:
    bus = EventBus(history=500)
    runner = JobRunner(engine, bus, max_concurrent=2, poll_interval_s=0.05)
    plans = PlanService(engine, bus, runner)
    await runner.start()
    yield runner, plans, bus
    await runner.stop()


def run_row(engine: Any, run_id: int) -> AgentRun:
    with Session(engine) as s:
        run = s.get(AgentRun, run_id)
        assert run is not None
        return run


def demo(**params: Any) -> StepIn:
    return StepIn(agent="demo", params=params)


async def test_plan_waits_for_approval_then_runs_to_completion(engine: Any, stack: Any) -> None:
    _runner, plans, bus = stack
    plan = await plans.create(PlanIn(summary="test", steps=[demo(steps=3, step_seconds=0)]))
    assert plan["status"] == "pending" and plan["steps"][0]["run_id"] is None
    await asyncio.sleep(0.15)
    with Session(engine) as s:
        assert s.exec(select(AgentRun)).all() == []  # nothing runs before approval

    plan = await plans.approve(plan["id"])
    run_id = plan["steps"][0]["run_id"]
    await wait_for(lambda: run_row(engine, run_id).status == "succeeded")
    run = run_row(engine, run_id)
    assert run.result == {"summary": "Demo finished 3 steps", "steps": 3}
    assert run.progress == 1.0 and run.started_at and run.finished_at
    with Session(engine) as s:
        messages = [r.message for r in s.exec(select(RunLog).where(RunLog.run_id == run_id))]
    assert messages[0] == "Started @demo" and "Step 3/3: Normalizing items" in messages
    await wait_for(lambda: plans.get(plan["id"])["status"] == "done")
    types = {e.type for e in bus.recent()}
    assert {"run.log", "run.status", "plan.status"} <= types


async def test_cancel_running_run_cancels_plan_and_skips_rest(engine: Any, stack: Any) -> None:
    runner, plans, _ = stack
    plan = await plans.create(
        PlanIn(summary="t", steps=[demo(steps=50, step_seconds=0.2), demo(steps=1, step_seconds=0)])
    )
    plan = await plans.approve(plan["id"])
    run_id = plan["steps"][0]["run_id"]
    await wait_for(lambda: run_row(engine, run_id).status == "running")
    await runner.cancel(run_id)
    assert run_row(engine, run_id).status == "cancelled"
    view = plans.get(plan["id"])
    assert view["status"] == "cancelled"
    assert [s["status"] for s in view["steps"]] == ["cancelled", "skipped"]


async def test_cancel_queued_run_never_starts(engine: Any) -> None:
    bus = EventBus()
    runner = JobRunner(engine, bus, max_concurrent=1, poll_interval_s=60)  # loop not started
    run = runner.enqueue("demo", {"steps": 1})
    assert run.id is not None
    cancelled = await runner.cancel(run.id)
    assert cancelled is not None and cancelled.status == "cancelled"
    assert cancelled.started_at is None


async def test_failing_agent_marks_run_and_plan_failed(engine: Any, stack: Any) -> None:
    _, plans, _ = stack
    plan = await plans.create(
        PlanIn(
            summary="t",
            steps=[demo(steps=5, step_seconds=0, fail_at=2), demo(steps=1, step_seconds=0)],
        )
    )
    plan = await plans.approve(plan["id"])
    run_id = plan["steps"][0]["run_id"]
    await wait_for(lambda: run_row(engine, run_id).status == "failed")
    assert "simulated failure at step 2" in (run_row(engine, run_id).error or "")
    await wait_for(lambda: plans.get(plan["id"])["status"] == "failed")
    assert [s["status"] for s in plans.get(plan["id"])["steps"]] == ["failed", "skipped"]


async def test_multi_step_plan_runs_steps_in_order(engine: Any, stack: Any) -> None:
    _, plans, _ = stack
    plan = await plans.create(
        PlanIn(summary="t", steps=[demo(steps=2, step_seconds=0.05), demo(steps=1, step_seconds=0)])
    )
    await plans.approve(plan["id"])
    await wait_for(lambda: plans.get(plan["id"])["status"] == "done")
    steps = plans.get(plan["id"])["steps"]
    first, second = run_row(engine, steps[0]["run_id"]), run_row(engine, steps[1]["run_id"])
    assert first.finished_at and second.started_at and second.started_at >= first.finished_at


async def test_auto_approve_starts_immediately(engine: Any, stack: Any) -> None:
    _, plans, _ = stack
    set_setting(engine, auto_approve_key("demo"), True)
    plan = await plans.create(PlanIn(summary="t", steps=[demo(steps=1, step_seconds=0)]))
    assert plan["status"] == "approved" and plan["steps"][0]["run_id"] is not None


async def test_approve_with_edited_params(engine: Any, stack: Any) -> None:
    _, plans, _ = stack
    plan = await plans.create(PlanIn(summary="t", steps=[demo(steps=9, step_seconds=0)]))
    plan = await plans.approve(plan["id"], edits={1: {"steps": 2, "step_seconds": 0}})
    run_id = plan["steps"][0]["run_id"]
    await wait_for(lambda: run_row(engine, run_id).status == "succeeded")
    assert run_row(engine, run_id).result == {"summary": "Demo finished 2 steps", "steps": 2}
    with pytest.raises(PlanError, match="not pending"):
        await plans.approve(plan["id"])


async def test_plan_validation(stack: Any) -> None:
    _, plans, _ = stack
    with pytest.raises(PlanError, match="isn't built yet"):
        await plans.create(PlanIn(summary="t", steps=[StepIn(agent="outlier")]))
    with pytest.raises(PlanError, match="unknown agent"):
        await plans.create(PlanIn(summary="t", steps=[StepIn(agent="factcheck")]))
    with pytest.raises(PlanError, match="steps"):
        await plans.create(PlanIn(summary="t", steps=[demo(steps=0)]))
    with pytest.raises(PlanError, match="at least one step"):
        await plans.create(PlanIn(summary="t", steps=[]))


async def test_concurrency_limit(engine: Any) -> None:
    bus = EventBus()
    runner = JobRunner(engine, bus, max_concurrent=1, poll_interval_s=0.05)
    await runner.start()
    try:
        a = runner.enqueue("demo", {"steps": 20, "step_seconds": 0.05})
        b = runner.enqueue("demo", {"steps": 1, "step_seconds": 0})
        assert a.id and b.id
        await wait_for(lambda: run_row(engine, a.id).status == "running")  # type: ignore[arg-type]
        await asyncio.sleep(0.2)
        assert run_row(engine, b.id).status == "queued"
        await wait_for(lambda: run_row(engine, b.id).status == "succeeded")  # type: ignore[arg-type]
    finally:
        await runner.stop()


async def test_restart_marks_interrupted_runs_failed(engine: Any) -> None:
    with Session(engine) as s:
        s.add(AgentRun(agent="demo", status="running", started_at=datetime.now(UTC)))
        s.commit()
    runner = JobRunner(engine, EventBus(), poll_interval_s=60)
    await runner.start()
    await runner.stop()
    with Session(engine) as s:
        run = s.exec(select(AgentRun)).one()
    assert run.status == "failed" and "Interrupted" in (run.error or "")


async def test_router_events_land_in_the_current_runs_log(engine: Any) -> None:
    async def agent(ctx: Any) -> dict[str, Any]:
        log_to_current_run("warn", "score_items: fallback via nvidia: groq failed")
        return {}

    runner = JobRunner(engine, EventBus(), poll_interval_s=0.05, resolve=lambda _: agent)
    await runner.start()
    try:
        run = runner.enqueue("demo", {})
        assert run.id
        await wait_for(lambda: run_row(engine, run.id).status == "succeeded")  # type: ignore[arg-type]
        with Session(engine) as s:
            levels = [
                (r.level, r.message) for r in s.exec(select(RunLog).where(RunLog.run_id == run.id))
            ]
        assert ("warn", "score_items: fallback via nvidia: groq failed") in levels
    finally:
        await runner.stop()


def test_usage_report_counts_today(engine: Any) -> None:
    now = datetime(2026, 10, 5, 20, 0, tzinfo=UTC)  # 13:00 in Los Angeles
    with Session(engine) as s:
        for ok, fallback in ((True, False), (True, True), (False, False)):
            s.add(
                ProviderUsage(
                    provider="mistral",
                    model="mistral-small-latest",
                    task="score_items",
                    ok=ok,
                    fallback=fallback,
                    tokens_in=100,
                    tokens_out=50,
                    ts=now,
                )
            )
        s.add(
            ProviderUsage(
                provider="mistral",
                model="mistral-small-latest",
                ok=True,
                ts=datetime(2026, 10, 5, 6, 0, tzinfo=UTC),
            )
        )  # 23:00 yesterday in LA
        s.add(
            ProviderUsage(
                provider="youtube", model="search", task="search", ok=True, units=1, ts=now
            )
        )
        s.add(
            ProviderUsage(
                provider="youtube", model="videos", task="videos", ok=True, units=1, ts=now
            )
        )
        s.commit()
    report = build_report(engine, load_providers(), load_engine(), {"mistral": "set"}, now=now)
    assert report["since"] == "2026-10-05T07:00:00+00:00"
    meters = {m["provider"]: m for m in report["meters"]}
    mistral = meters["mistral"]
    assert (mistral["requests"], mistral["errors"], mistral["fallbacks"]) == (3, 1, 1)
    small = next(m for m in mistral["models"] if m["alias"] == "small")
    assert small["tokens"] == 450
    youtube = meters["youtube"]
    assert (youtube["used"], youtube["limit"], youtube["search_calls"]) == (2, 10000, 1)
    assert meters["claude"]["unit"] == "runs"


def test_day_start_uses_configured_timezone() -> None:
    assert (
        day_start("America/Los_Angeles", datetime(2026, 1, 15, 3, 0, tzinfo=UTC)).isoformat()
        == "2026-01-14T08:00:00+00:00"
    )  # PST, previous local day
