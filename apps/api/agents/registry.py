"""Agent registry. Adding an agent (e.g. v2 @factcheck) = one module + one entry here.

`runner` is "module:function" for the agent's `async def run(ctx: RunContext) -> dict`.
Agents without a runner yet can't be put in a plan.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from apps.api.agents.params import DemoParams, OutlierParams, ResearcherParams, ScoutParams

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

    def load_runner(self) -> AgentFn:
        if not self.runner:
            raise LookupError(f"@{self.name} is not implemented yet ({self.arrives_in or 'v2'})")
        module, _, func = self.runner.partition(":")
        fn: AgentFn = getattr(importlib.import_module(module), func)
        return fn

    def public(self) -> dict[str, Any]:
        return self.model_dump(exclude={"runner", "params_model"}) | {
            "implemented": self.runner is not None
        }


AGENTS: dict[str, AgentInfo] = {
    "scout": AgentInfo(
        name="scout",
        description="Finds and scores new story leads (news + evergreen gaps)",
        uses_claude=False,
        uses_youtube_quota=True,
        arrives_in="Phase 3",
        params_model=ScoutParams,
    ),
    "outlier": AgentInfo(
        name="outlier",
        description="Finds competitor videos that beat their channel median",
        uses_claude=False,
        uses_youtube_quota=True,
        arrives_in="Phase 4",
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
