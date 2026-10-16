"""Story repository: create, list, update stories and their sources (SPEC §7)."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlmodel import Session, col, func, select

from apps.api import hook_figures
from apps.api.config import load_scoring
from apps.api.db.models import Dossier, Story, StorySource, StoryStatus, utcnow

PRIMARY_SOURCES = ("SEC EDGAR", "SEC press releases", "DOJ press releases", "CourtListener")


def slugify(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return slug[:80] or "story"


def unique_slug(s: Session, base: str) -> str:
    slug, n = slugify(base), 2
    candidate = slug
    while s.exec(select(Story.id).where(Story.slug == candidate)).first() is not None:
        candidate = f"{slug}-{n}"
        n += 1
    return candidate


def total_score(scores: dict[str, Any] | None) -> float | None:
    """Weighted rubric average (weights in scoring.yaml), 1–10."""
    if not scores:
        return None
    weights: dict[str, float] = load_scoring().scout.get("rubric_weights", {})
    pairs = [
        (float(scores[k]), w) for k, w in weights.items() if isinstance(scores.get(k), int | float)
    ]
    if not pairs:
        return None
    return round(sum(v * w for v, w in pairs) / sum(w for _, w in pairs), 2)


class SourceIn(BaseModel):
    url: str
    title: str | None = None
    source_type: str = "secondary"
    excerpt: str | None = None


class StoryIn(BaseModel):
    title: str
    company: str | None = None
    series: str | None = None
    format: str | None = None
    hook: str | None = None
    hook_figure: str | None = None  # already grounded in the source text by the caller
    hook_caption: str | None = None
    scores: dict[str, Any] | None = None
    gap_score: float | None = None
    notes: str | None = None
    sources: list[SourceIn] = []


def create_story(engine: Engine, data: StoryIn, added_by: str) -> Story:
    with Session(engine) as s:
        scores = dict(data.scores or {})
        if scores:
            scores["total"] = total_score(scores)
        story = Story(
            slug=unique_slug(s, data.title),
            title=data.title,
            company=data.company,
            status=StoryStatus.INBOX.value,
            series=data.series,
            format=data.format,
            hook=data.hook,
            hook_figure=data.hook_figure,
            hook_caption=data.hook_caption,
            scores=scores or None,
            gap_score=data.gap_score,
            notes=data.notes,
        )
        s.add(story)
        s.commit()
        s.refresh(story)
        assert story.id is not None
        for src in data.sources:
            s.add(
                StorySource(
                    story_id=story.id,
                    url=src.url,
                    title=src.title,
                    source_type=src.source_type,
                    excerpt=src.excerpt,
                    added_by=added_by,
                )
            )
        s.commit()
        s.refresh(story)
        return story


def known_source_urls(engine: Engine) -> set[str]:
    with Session(engine) as s:
        return set(s.exec(select(StorySource.url)).all())


def title_exists(engine: Engine, title: str) -> bool:
    """Case-insensitive: a story with this title is already saved (e.g. by a parallel run)."""
    with Session(engine) as s:
        return (
            s.exec(select(Story.id).where(func.lower(Story.title) == title.strip().lower())).first()
            is not None
        )


def known_titles(engine: Engine) -> set[str]:
    with Session(engine) as s:
        return {t.lower() for t in s.exec(select(Story.title)).all()}


def story_view(
    s: Session,
    story: Story,
    full: bool = False,
    key_numbers: dict[int, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    view = story.model_dump(mode="json")
    view["total_score"] = (story.scores or {}).get("total")
    if key_numbers is None:
        key_numbers = hook_figures.key_numbers_by_story(s, [story.id or 0])
    view["hook_figure_verified"] = hook_figures.confirmed(
        story.hook_figure, key_numbers.get(story.id or 0, [])
    )
    sources = s.exec(select(StorySource).where(StorySource.story_id == story.id)).all()
    view["source_count"] = len(sources)
    if full:
        view["sources"] = [src.model_dump(mode="json") for src in sources]
        view["dossier_versions"] = list(
            s.exec(
                select(Dossier.version)
                .where(Dossier.story_id == story.id)
                .order_by(col(Dossier.version))
            ).all()
        )
    return view


def list_stories(
    engine: Engine,
    *,
    status: str | None = None,
    series: str | None = None,
    format: str | None = None,
    q: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    with Session(engine) as s:
        stmt = select(Story).order_by(col(Story.updated_at).desc()).limit(limit)
        if status:
            stmt = stmt.where(Story.status == status)
        if series:
            stmt = stmt.where(Story.series == series)
        if format:
            stmt = stmt.where(Story.format == format)
        if q:
            # FTS5 over title/hook/notes; quote each term so user input can't inject syntax.
            terms = " ".join(f'"{t}"*' for t in re.findall(r"\w+", q))
            if terms:
                ids = [
                    r[0]
                    for r in s.execute(
                        text("SELECT rowid FROM stories_fts WHERE stories_fts MATCH :q"),
                        {"q": terms},
                    )
                ]
                stmt = stmt.where(col(Story.id).in_(ids))
        rows = s.exec(stmt).all()
        numbers = hook_figures.key_numbers_by_story(s, [st.id or 0 for st in rows])
        return [story_view(s, st, key_numbers=numbers) for st in rows]


def get_story(engine: Engine, story_id: int) -> dict[str, Any] | None:
    with Session(engine) as s:
        story = s.get(Story, story_id)
        return None if story is None else story_view(s, story, full=True)


class StoryPatch(BaseModel):
    status: StoryStatus | None = None
    series: str | None = None
    format: str | None = None
    notes: str | None = None
    hook: str | None = None


def update_story(engine: Engine, story_id: int, patch: StoryPatch) -> dict[str, Any] | None:
    with Session(engine) as s:
        story = s.get(Story, story_id)
        if story is None:
            return None
        for field, value in patch.model_dump(exclude_unset=True).items():
            setattr(story, field, value.value if isinstance(value, StoryStatus) else value)
        story.updated_at = utcnow()
        s.add(story)
        s.commit()
        s.refresh(story)
        return story_view(s, story, full=True)
