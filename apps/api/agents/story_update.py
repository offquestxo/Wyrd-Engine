"""Internal step: apply a story update that changes status (SPEC §5.5: status changes need
plan approval). The orchestrator's `update_story` tool creates a plan with this step."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from apps.api.agents.params import StoryUpdateParams
from apps.api.db.session import get_engine
from apps.api.events import bus
from apps.api.stories import StoryPatch, update_story

if TYPE_CHECKING:
    from apps.api.jobs import RunContext


async def run(ctx: RunContext) -> dict[str, Any]:
    p = StoryUpdateParams.model_validate(ctx.params)
    fields = p.fields.model_dump(exclude_none=True)
    story = update_story(get_engine(), p.story_id, StoryPatch.model_validate(fields))
    if story is None:
        raise ValueError(f"no story {p.story_id}")
    bus.publish("story.changed", story_id=p.story_id, status=story["status"])
    changed = ", ".join(
        f"{k} → {v}" for k, v in fields.items() if k in ("status", "series", "format")
    )
    ctx.log("info", f"Updated story #{p.story_id} “{story['title']}”: {changed or 'fields'}")
    return {
        "summary": f"Story #{p.story_id} “{story['title']}” updated ({changed or 'fields'})",
        "story_id": p.story_id,
        "fields": fields,
    }
