"""Agent registry. Adding an agent (e.g. v2 @factcheck) = one module + one entry here."""

from __future__ import annotations

from pydantic import BaseModel


class AgentInfo(BaseModel):
    name: str
    description: str
    uses_claude: bool
    uses_youtube_quota: bool
    available: bool = True  # False = reserved for a later version


AGENTS: dict[str, AgentInfo] = {
    "scout": AgentInfo(
        name="scout",
        description="Finds and scores new story leads (news + evergreen gaps)",
        uses_claude=False,
        uses_youtube_quota=True,
    ),
    "outlier": AgentInfo(
        name="outlier",
        description="Finds competitor videos that beat their channel median",
        uses_claude=False,
        uses_youtube_quota=True,
    ),
    "researcher": AgentInfo(
        name="researcher",
        description="Builds a sourced research dossier for a story",
        uses_claude=True,
        uses_youtube_quota=False,
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
