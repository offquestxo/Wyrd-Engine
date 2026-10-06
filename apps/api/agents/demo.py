"""@demo: a test agent that simulates work, so runs, logs, and cancellation can be tested."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from apps.api.agents.params import DemoParams

if TYPE_CHECKING:
    from apps.api.jobs import RunContext

STEPS = [
    "Loading sources",
    "Fetching feeds",
    "Normalizing items",
    "Deduplicating",
    "Scoring batch",
    "Ranking",
    "Saving results",
    "Writing summary",
]


async def run(ctx: RunContext) -> dict[str, Any]:
    params = DemoParams.model_validate(ctx.params)
    for i in range(1, params.steps + 1):
        name = STEPS[(i - 1) % len(STEPS)]
        ctx.step(f"{name} ({i}/{params.steps})", progress=(i - 1) / params.steps)
        ctx.log("info", f"Step {i}/{params.steps}: {name}", {"step": i})
        if params.fail_at == i:
            raise RuntimeError(f"simulated failure at step {i}")
        await asyncio.sleep(params.step_seconds)  # cancellation lands here
    ctx.step("Done", progress=1.0)
    return {"summary": f"Demo finished {params.steps} steps", "steps": params.steps}
