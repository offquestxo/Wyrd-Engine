"""SQLModel classes mirroring migrations/*.sql (the SQL files are the schema source of truth).

tests/test_db.py checks that these classes and the migrated schema stay in sync.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, LargeBinary
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


class StoryStatus(StrEnum):
    INBOX = "Inbox"
    SHORTLISTED = "Shortlisted"
    RESEARCHING = "Researching"
    SCRIPTING = "Scripting"
    FACT_CHECK = "Fact-check"
    RECORDING = "Recording"
    EDITING = "Editing"
    PUBLISHED = "Published"
    ARCHIVED = "Archived"


class PlanStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    CANCELLED = "cancelled"
    DONE = "done"
    FAILED = "failed"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Story(SQLModel, table=True):
    __tablename__ = "stories"
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True)
    title: str
    company: str | None = None
    status: str = StoryStatus.INBOX.value
    series: str | None = None
    format: str | None = None
    hook: str | None = None
    scores: dict[str, Any] | None = Field(default=None, sa_type=JSON)
    gap_score: float | None = None
    outlier_ref: int | None = Field(default=None, foreign_key="videos.id")
    notes: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    notion_page_id: str | None = None
    notion_synced_at: datetime | None = None


class StorySource(SQLModel, table=True):
    __tablename__ = "story_sources"
    id: int | None = Field(default=None, primary_key=True)
    story_id: int = Field(foreign_key="stories.id")
    url: str
    title: str | None = None
    source_type: str = "secondary"
    excerpt: str | None = None
    added_by: str | None = None


class Dossier(SQLModel, table=True):
    __tablename__ = "dossiers"
    id: int | None = Field(default=None, primary_key=True)
    story_id: int = Field(foreign_key="stories.id")
    version: int
    markdown: str
    sources_json: list[dict[str, Any]] | None = Field(default=None, sa_type=JSON)
    second_opinion: dict[str, Any] | None = Field(default=None, sa_type=JSON)
    created_at: datetime = Field(default_factory=utcnow)


class Channel(SQLModel, table=True):
    __tablename__ = "channels"
    id: int | None = Field(default=None, primary_key=True)
    handle: str = Field(unique=True)
    channel_id: str | None = None
    name: str | None = None
    uploads_playlist_id: str | None = None
    last_scanned_at: datetime | None = None


class Video(SQLModel, table=True):
    __tablename__ = "videos"
    id: int | None = Field(default=None, primary_key=True)
    channel_id: int = Field(foreign_key="channels.id")
    video_id: str = Field(unique=True)
    title: str
    published_at: datetime | None = None
    duration_s: int | None = None
    is_short: bool = False
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    outlier_score: float | None = None
    analysis: dict[str, Any] | None = Field(default=None, sa_type=JSON)


class Chat(SQLModel, table=True):
    __tablename__ = "chats"
    id: int | None = Field(default=None, primary_key=True)
    title: str
    claude_session_id: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Message(SQLModel, table=True):
    __tablename__ = "messages"
    id: int | None = Field(default=None, primary_key=True)
    chat_id: int = Field(foreign_key="chats.id")
    role: str
    content: str
    metadata_: dict[str, Any] | None = Field(
        default=None, sa_type=JSON, sa_column_kwargs={"name": "metadata"}
    )
    created_at: datetime = Field(default_factory=utcnow)


class Plan(SQLModel, table=True):
    __tablename__ = "plans"
    id: int | None = Field(default=None, primary_key=True)
    chat_id: int | None = Field(default=None, foreign_key="chats.id")
    status: str = PlanStatus.PENDING.value
    summary: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    decided_at: datetime | None = None


class PlanStep(SQLModel, table=True):
    __tablename__ = "plan_steps"
    id: int | None = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="plans.id")
    order: int
    agent: str
    params: dict[str, Any] | None = Field(default=None, sa_type=JSON)
    status: str = "pending"
    run_id: int | None = Field(default=None, foreign_key="agent_runs.id")


class AgentRun(SQLModel, table=True):
    __tablename__ = "agent_runs"
    id: int | None = Field(default=None, primary_key=True)
    agent: str
    params: dict[str, Any] | None = Field(default=None, sa_type=JSON)
    status: str = RunStatus.QUEUED.value
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result: dict[str, Any] | None = Field(default=None, sa_type=JSON)
    error: str | None = None


class RunLog(SQLModel, table=True):
    __tablename__ = "run_logs"
    id: int | None = Field(default=None, primary_key=True)
    run_id: int = Field(foreign_key="agent_runs.id")
    ts: datetime = Field(default_factory=utcnow)
    level: str = "info"
    message: str
    data: dict[str, Any] | None = Field(default=None, sa_type=JSON)


class ProviderUsage(SQLModel, table=True):
    __tablename__ = "provider_usage"
    id: int | None = Field(default=None, primary_key=True)
    provider: str
    model: str | None = None
    task: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    units: int = 0
    latency_ms: int = 0
    ok: bool
    error: str | None = None
    ts: datetime = Field(default_factory=utcnow)


class Setting(SQLModel, table=True):
    __tablename__ = "settings"
    key: str = Field(primary_key=True)
    value: Any | None = Field(default=None, sa_type=JSON)


class Embedding(SQLModel, table=True):
    __tablename__ = "embeddings"
    id: int | None = Field(default=None, primary_key=True)
    ref_type: str
    ref_id: int
    vector: bytes = Field(sa_type=LargeBinary)
    model: str
