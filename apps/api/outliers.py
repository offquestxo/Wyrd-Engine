"""Outlier queries and actions for the Outliers page (SPEC §9.5)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session, col, select

from apps.api.config import load_scoring
from apps.api.db.models import Channel, Story, Video
from apps.api.stories import SourceIn, StoryIn, create_story


def video_view(video: Video, channel: Channel | None) -> dict[str, Any]:
    return video.model_dump(mode="json") | {
        "channel_name": channel.name if channel else None,
        "channel_handle": channel.handle if channel else None,
        "url": f"https://www.youtube.com/watch?v={video.video_id}",
    }


def list_outliers(
    engine: Engine,
    *,
    channel: str | None = None,
    format: str | None = None,
    min_score: float | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    cfg = load_scoring().outlier
    threshold = min_score if min_score is not None else float(cfg.get("default_threshold", 3.0))
    # Same rule as flagging: videos still gaining their first views aren't outliers yet.
    settled_before = datetime.now(UTC) - timedelta(days=int(cfg.get("min_age_days", 3)))
    with Session(engine) as s:
        stmt = (
            select(Video, Channel)
            .join(Channel, col(Channel.id) == col(Video.channel_id))
            .where(col(Video.outlier_score) >= threshold)
            .where(col(Video.published_at) <= settled_before)
            .order_by(col(Video.outlier_score).desc())
            .limit(limit)
        )
        if channel:
            stmt = stmt.where(Channel.handle == channel)
        if format in ("shorts", "long"):
            stmt = stmt.where(Video.is_short == (format == "shorts"))
        rows = s.exec(stmt).all()
        story_by_video = {
            ref: sid for sid, ref in s.exec(select(Story.id, Story.outlier_ref)).all() if ref
        }
        return [video_view(v, c) | {"story_id": story_by_video.get(v.id or 0)} for v, c in rows]


def list_channels(engine: Engine) -> list[dict[str, Any]]:
    with Session(engine) as s:
        out = []
        for ch in s.exec(select(Channel).order_by(col(Channel.name))).all():
            count = len(s.exec(select(Video.id).where(Video.channel_id == ch.id)).all())
            out.append(ch.model_dump(mode="json") | {"videos": count})
        return out


def create_story_from_outlier(engine: Engine, video_id: str) -> dict[str, Any] | None:
    """Turn an outlier's topic into an Inbox story (tagged via outlier_ref)."""
    with Session(engine) as s:
        found = s.exec(
            select(Video, Channel)
            .join(Channel, col(Channel.id) == col(Video.channel_id))
            .where(Video.video_id == video_id)
        ).first()
        if found is None:
            return None
        video, channel = found
        existing = s.exec(select(Story).where(Story.outlier_ref == video.id)).first()
        if existing is not None:
            return {"story_id": existing.id, "created": False}
    analysis = video.analysis or {}
    topic = str(analysis.get("topic") or video.title)
    angle = analysis.get("wyrd_angle")
    story = create_story(
        engine,
        StoryIn(
            title=topic,
            company=topic,
            hook=str(angle) if angle else None,
            format="Short" if video.is_short else "Long",
            notes=(
                f"From @outlier: “{video.title}” on {channel.name} did "
                f"{video.outlier_score}× its channel median ({(video.views or 0):,} views). "
                + (
                    f"Why it worked: {analysis.get('why_it_worked')}"
                    if analysis.get("why_it_worked")
                    else ""
                )
            ),
            sources=[
                SourceIn(
                    url=f"https://www.youtube.com/watch?v={video.video_id}",
                    title=f"{video.title} — {channel.name} (YouTube)",
                    source_type="secondary",
                )
            ],
        ),
        added_by="outlier",
    )
    with Session(engine) as s:
        row = s.get(Story, story.id)
        assert row is not None
        row.outlier_ref = video.id
        s.add(row)
        s.commit()
    return {"story_id": story.id, "created": True}
