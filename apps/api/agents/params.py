"""Typed parameters for each agent (SPEC §6). Plan steps are validated against these."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SeriesName = Literal[
    "Childhood Brands",
    "Tech Graveyard",
    "Fraud Files",
    "Everyday Genius",
    "Comebacks",
    "Recent Collapses",
]


class _Params(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScoutParams(_Params):
    mode: Literal["news", "evergreen", "both"] = "both"
    topic: str | None = None
    limit: int = Field(default=25, ge=1, le=200)
    series: SeriesName | None = None


class OutlierParams(_Params):
    channels: list[str] | None = None  # None = all channels in channels.yaml
    videos_per_channel: int = Field(default=50, ge=1, le=500)
    threshold: float = Field(default=3.0, gt=0)
    format: Literal["shorts", "long", "both"] = "both"


class ResearcherParams(_Params):
    story_id: int | None = None
    topic: str | None = None
    depth: Literal["quick", "standard", "deep"] = "standard"
    focus: str | None = None

    @model_validator(mode="after")
    def _needs_subject(self) -> ResearcherParams:
        if self.story_id is None and not self.topic:
            raise ValueError("researcher needs story_id or topic")
        return self


class DemoParams(_Params):
    """Test agent: simulates a run so the job pipeline can be exercised end to end."""

    steps: int = Field(default=8, ge=1, le=100)
    step_seconds: float = Field(default=1.5, ge=0, le=60)
    fail_at: int | None = Field(
        default=None, ge=1, description="step that raises, to test failures"
    )
