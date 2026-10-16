"""Thumbnail figures (redesign stage 4): grounding, dossier confirmation, and backfill.

A story's `hook_figure` is a striking number for its thumbnail idea, with a `hook_caption` of
at most 5 words. Research integrity rules:

- A figure is kept only if every number in it appears in the source text the model was given
  (`ground`). Anything else is dropped. Nothing is invented.
- A kept figure is an unverified lead until the latest dossier's Key Numbers contain the same
  number (`confirmed`). The UI marks unverified figures with "?" and confirmed ones with ✓.

Backfill existing stories from their own source text:
    python -m apps.api.hook_figures backfill [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session, col, select

from apps.api.db.models import Dossier, Story, StorySource

MAX_CAPTION_WORDS = 5
_NUMBER = re.compile(r"\d[\d,.]*\d|\d")
_SCALE = {
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "mn": 1e6,
    "million": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
    "t": 1e12,
    "trillion": 1e12,
}
_SCALED = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(trillion|billion|million|thousand|bn|mn|[kmbt])\b", re.I
)


def _cores(text: str) -> list[str]:
    """Numbers in `text` without thousands separators: "$3,400 and 1.4" → ["3400", "1.4"]."""
    return [m.group(0).replace(",", "").rstrip(".") for m in _NUMBER.finditer(text)]


def _values(text: str) -> set[float]:
    """Numeric values, with scale words applied: "$1.4 million" and "$1.4M" → {1.4, 1400000}."""
    out = {float(c) for c in _cores(text) if c.replace(".", "", 1).isdigit()}
    for m in _SCALED.finditer(text):
        out.add(float(m.group(1).replace(",", "")) * _SCALE[m.group(2).lower()])
    return out


def ground(
    figure: str | None, caption: str | None, source_text: str
) -> tuple[str | None, str | None]:
    """Keep the figure only if every number in it appears in the source text; else drop both.

    A caption without a figure is dropped. A caption longer than 5 words is dropped (the
    figure alone is still useful).
    """
    figure = (figure or "").strip().strip("\"'“”") or None
    caption = " ".join((caption or "").split()) or None
    if figure is None:
        return None, None
    cores = _cores(figure)
    if not cores:
        return None, None
    # A year on its own ("1971 · founded") is a date, not a striking number.
    if re.fullmatch(r"(?:in\s+)?(1[5-9]\d\d|20\d\d)s?", figure.strip(), re.I):
        return None, None
    # A bare single digit ("1 piece of advice") isn't a thumbnail number.
    if all(len(c.replace(".", "")) == 1 for c in cores) and not re.search(
        r"[$€£%]|[a-z]", figure, re.I
    ):
        return None, None
    text_cores = set(_cores(source_text))
    if not all(c in text_cores for c in cores):
        return None, None
    if caption and (
        len(caption.split()) > MAX_CAPTION_WORDS or any(c in _cores(caption) for c in cores)
    ):
        caption = None  # too long, or just repeats the figure
    return figure, caption


def confirmed(figure: str | None, key_numbers: list[dict[str, Any]]) -> bool:
    """True if a dossier Key Number has the same value as the figure ("$1.4M" = "$1.4 million")."""
    if not figure:
        return False
    wanted = _values(figure)
    if not wanted:
        return False
    return any(wanted & _values(str(row.get("figure") or "")) for row in key_numbers)


def key_numbers_by_story(
    s: Session, story_ids: list[int] | None = None
) -> dict[int, list[dict[str, Any]]]:
    """Key Numbers of each story's latest dossier version."""
    stmt = select(Dossier.story_id, Dossier.version, Dossier.data).order_by(
        col(Dossier.story_id), col(Dossier.version)
    )
    if story_ids is not None:
        stmt = stmt.where(col(Dossier.story_id).in_(story_ids))
    out: dict[int, list[dict[str, Any]]] = {}
    for story_id, _version, data in s.exec(stmt).all():
        out[story_id] = list((data or {}).get("key_numbers") or [])  # later versions overwrite
    return out


def source_text(s: Session, story: Story) -> str:
    """The text a figure may come from: the story's headline, its sources' titles/excerpts,
    and its latest dossier's Key Numbers (each backed by a source excerpt)."""
    parts = [story.title]
    for src in s.exec(select(StorySource).where(StorySource.story_id == story.id)).all():
        parts += [src.title or "", src.excerpt or ""]
    for row in key_numbers_by_story(s, [story.id or 0]).get(story.id or 0, []):
        parts += [
            f"{row.get('figure', '')}: {row.get('meaning', '')}",
            str(row.get("excerpt") or ""),
        ]
    return "\n".join(p for p in parts if p)


async def backfill(engine: Engine, dry_run: bool = False) -> list[dict[str, Any]]:
    """Propose figures for stories that have none, from their own source text only."""
    from apps.api.providers.base import ProviderError
    from apps.api.providers.router import get_router

    router = get_router()
    report: list[dict[str, Any]] = []
    with Session(engine) as s:
        stories = s.exec(select(Story).where(col(Story.hook_figure).is_(None))).all()
        jobs = [(story.id, story.title, source_text(s, story)) for story in stories]
    for story_id, title, text in jobs:
        try:
            proposal = await router.propose_hook_figure(text)
        except ProviderError as e:
            report.append({"story_id": story_id, "title": title, "error": str(e)[:200]})
            continue
        figure, caption = ground(proposal.figure, proposal.caption, text)
        entry = {"story_id": story_id, "title": title, "figure": figure, "caption": caption}
        if proposal.figure and not figure:
            entry["dropped"] = proposal.figure  # not found in the source text
        report.append(entry)
        if figure and not dry_run:
            with Session(engine) as s:
                story = s.get(Story, story_id)
                if story is not None and story.hook_figure is None:
                    story.hook_figure, story.hook_caption = figure, caption
                    s.add(story)
                    s.commit()
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill", help="propose figures for stories without one")
    b.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    from apps.api.db.session import get_engine

    report = asyncio.run(backfill(get_engine(), dry_run=args.dry_run))
    print(json.dumps(report, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
