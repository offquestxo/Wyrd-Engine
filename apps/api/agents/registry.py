"""Agent registry. Adding an agent (e.g. v2 @factcheck) = one module + one entry here.

`runner` is "module:function" for the agent's `async def run(ctx: RunContext) -> dict`.
Agents without a runner yet can't be put in a plan.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from apps.api.agents.params import (
    DemoParams,
    OutlierParams,
    ResearcherParams,
    ScoutParams,
    StoryUpdateParams,
)

if TYPE_CHECKING:
    from apps.api.jobs import RunContext

AgentFn = Callable[["RunContext"], Awaitable[dict[str, Any]]]


class AgentInfo(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    uses_claude: bool
    uses_youtube_quota: bool
    available: bool = True  # False = reserved for a later version
    hidden: bool = False  # internal/test agents: not offered in @autocomplete
    runner: str | None = None  # "module:function"; None until the agent is built
    arrives_in: str | None = None  # phase that implements it, for helpful errors
    params_model: type[BaseModel] | None = None
    estimate: str | None = None  # "module:function(params) -> dict" for plan-card estimates

    def load_runner(self) -> AgentFn:
        if not self.runner:
            raise LookupError(f"@{self.name} is not implemented yet ({self.arrives_in or 'v2'})")
        module, _, func = self.runner.partition(":")
        fn: AgentFn = getattr(importlib.import_module(module), func)
        return fn

    def estimate_for(self, params: dict[str, Any]) -> dict[str, Any] | None:
        if not self.estimate:
            return None
        module, _, func = self.estimate.partition(":")
        result: dict[str, Any] = getattr(importlib.import_module(module), func)(params)
        return result

    def public(self) -> dict[str, Any]:
        return self.model_dump(exclude={"runner", "params_model", "estimate"}) | {
            "implemented": self.runner is not None
        }


AGENTS: dict[str, AgentInfo] = {
    "scout": AgentInfo(
        name="scout",
        description="Finds and scores new story leads (news + evergreen gaps)",
        uses_claude=False,
        uses_youtube_quota=True,
        runner="apps.api.agents.scout:run",
        estimate="apps.api.agents.scout:estimate",
        params_model=ScoutParams,
    ),
    "outlier": AgentInfo(
        name="outlier",
        description="Finds competitor videos that beat their channel median",
        uses_claude=False,
        uses_youtube_quota=True,
        runner="apps.api.agents.outlier:run",
        estimate="apps.api.agents.outlier:estimate",
        params_model=OutlierParams,
    ),
    "researcher": AgentInfo(
        name="researcher",
        description="Builds a sourced research dossier for a story",
        uses_claude=True,
        uses_youtube_quota=False,
        arrives_in="Phase 6",
        params_model=ResearcherParams,
    ),
    "demo": AgentInfo(
        name="demo",
        description="Test agent: simulates a run to exercise the job pipeline",
        uses_claude=False,
        uses_youtube_quota=False,
        hidden=True,
        runner="apps.api.agents.demo:run",
        params_model=DemoParams,
    ),
    "story_update": AgentInfo(
        name="story_update",
        description="Applies a story change that needs approval (e.g. a status move)",
        uses_claude=False,
        uses_youtube_quota=False,
        hidden=True,
        runner="apps.api.agents.story_update:run",
        params_model=StoryUpdateParams,
    ),
    "factcheck": AgentInfo(
        name="factcheck",
        description="Verifies script claims against dossier sources (v2)",
        uses_claude=True,
        uses_youtube_quota=False,
        available=False,
    ),
    "graphics": AgentInfo(
        name="graphics",
        description="Renders [GRAPHIC] cues with Remotion templates (v2)",
        uses_claude=False,
        uses_youtube_quota=False,
        available=False,
    ),
}
