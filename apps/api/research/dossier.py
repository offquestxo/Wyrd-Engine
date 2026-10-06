"""Dossiers: structured input → integrity checks → markdown (SPEC §6.3 template) → DB + export.

The researcher submits structured JSON, not free markdown, so every Timeline item, Key Number
and the Twist carries a source number and excerpt that can be checked mechanically:

1. **Excerpt length cap** (`scoring.yaml` research.excerpt_max_words): longer excerpts are cut
   to that many words. A prefix of a real quote is still a real quote.
2. **Excerpt check:** the excerpt must appear in the cited source's text: the text the engine
   served to the researcher this run, or the URL fetched now. Whitespace, quotes, dashes and
   case are normalized.
3. **Figure check** (Key Numbers): the figure's numbers must appear in its excerpt (matching
   significant digits, so "$11.7 billion" matches "11,743,700").

A row that fails any check is not saved as fact: it moves to "Open Questions / Unverified"
with the reason. Sources on primary domains (filings, court records, archives) are marked
primary by the engine.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import Engine
from sqlmodel import Session, col, func, select

from apps.api.config import load_scoring
from apps.api.db.models import Dossier, Story, StorySource, utcnow
from apps.api.research.texts import cap_words, excerpt_in
from apps.api.settings import RESEARCH_DIR
from apps.api.sources._http import SourceError


# ---------------------------------------------------------------------------- input schema
class SourceRef(BaseModel):
    n: int = Field(description="Source number used by rows, starting at 1")
    url: str
    title: str
    kind: str | None = Field(default=None, description='e.g. "10-K filing", "court opinion"')


class TimelineItem(BaseModel):
    date: str = Field(description='"2008-11-10" or "Nov 2008" or "2008"')
    event: str
    source: int = Field(description="Source number n")
    excerpt: str = Field(description="Short quote copied exactly from that source")


class KeyNumber(BaseModel):
    figure: str = Field(description='e.g. "$11.7 billion"')
    meaning: str
    source: int
    excerpt: str


class Person(BaseModel):
    name: str
    role: str
    source: int | None = None
    excerpt: str | None = None


class StoryBeats(BaseModel):
    rise: str
    peak: str
    cracks: str
    fall: str
    aftermath: str


class Resolution(BaseModel):
    claim: str
    action: Literal["fixed", "softened", "moved_to_open_questions", "removed", "kept"]
    note: str = ""


class DossierIn(BaseModel):
    title: str = Field(description="Company or story name")
    summary: str
    twist: str = Field(description="The single most surprising fact")
    twist_source: int | None = None
    twist_excerpt: str | None = None
    timeline: list[TimelineItem]
    key_people: list[Person] = Field(default_factory=list)
    key_numbers: list[KeyNumber]
    story_beats: StoryBeats
    hook_ideas: list[str] = Field(description="5 hook ideas")
    best_short_angle: str
    best_long_angle: str
    open_questions: list[str] = Field(default_factory=list)
    sources: list[SourceRef]
    second_opinion_resolutions: list[Resolution] = Field(
        default_factory=list, description="How each second-opinion flag was handled"
    )

    @field_validator("sources")
    @classmethod
    def _unique_numbers(cls, sources: list[SourceRef]) -> list[SourceRef]:
        numbers = [s.n for s in sources]
        if len(numbers) != len(set(numbers)):
            raise ValueError("source numbers must be unique")
        return sources


# ---------------------------------------------------------------------------- checks
TextLookup = Callable[[str], Awaitable[str]]

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def significant_digits(token: str) -> str:
    digits = token.replace(",", "").replace(".", "").lstrip("0")
    return digits.rstrip("0") or "0"


def _is_year(token: str) -> bool:
    return re.fullmatch(r"(19|20)\d\d", token) is not None


def figure_supported(figure: str, excerpt: str) -> bool:
    """Every non-year number in the figure appears in the excerpt (same leading significant
    digits, allowing rounding); a figure with only years needs those years."""
    fig = _NUM.findall(figure)
    if not fig:
        return True  # nothing numeric to check (e.g. "Chapter 11")
    wanted = [t for t in fig if not _is_year(t)] or fig
    found = _NUM.findall(excerpt)
    for token in wanted:
        target = significant_digits(token)
        ok = False
        for other in found:
            digits = significant_digits(other)
            if digits.startswith(target):
                ok = True
            elif len(digits) > len(target):
                rounded = str((int(digits[: len(target) + 1]) + 5) // 10)  # half up
                ok = rounded == target
            if ok:
                break
        if not ok:
            return False
    return True


def is_primary(url: str, domains: list[str]) -> bool:
    host = urlparse(url).netloc.lower().split(":")[0]
    return any(host == d or host.endswith("." + d) for d in domains)


class RowCheck(BaseModel):
    section: str  # "timeline" | "key_numbers" | "twist" | "key_people"
    claim: str
    source: int | None
    ok: bool
    reason: str | None = None
    truncated: bool = False


async def check_rows(
    data: DossierIn, lookup: TextLookup, max_words: int
) -> tuple[DossierIn, list[RowCheck], dict[str, str]]:
    """Run the checks. Returns the cleaned dossier (failed rows moved to open questions), the
    per-row results, and per-source fetch errors."""
    by_n = {s.n: s for s in data.sources}
    texts: dict[str, str | None] = {}
    fetch_errors: dict[str, str] = {}

    async def text_for(n: int) -> str | None:
        src = by_n.get(n)
        if src is None:
            return None
        if src.url not in texts:
            try:
                texts[src.url] = await lookup(src.url)
            except SourceError as e:
                texts[src.url] = None
                fetch_errors[src.url] = str(e)
        return texts[src.url]

    async def verify(section: str, claim: str, n: int | None, excerpt: str | None) -> RowCheck:
        if n is None or not excerpt:
            return RowCheck(
                section=section, claim=claim, source=n, ok=False, reason="no source or excerpt"
            )
        if n not in by_n:
            return RowCheck(
                section=section, claim=claim, source=n, ok=False, reason=f"source [{n}] not listed"
            )
        text = await text_for(n)
        if text is None:
            reason = f"couldn't read source [{n}]: {fetch_errors.get(by_n[n].url, 'unknown')}"
            return RowCheck(section=section, claim=claim, source=n, ok=False, reason=reason)
        if not excerpt_in(excerpt, text):
            return RowCheck(
                section=section,
                claim=claim,
                source=n,
                ok=False,
                reason=f"excerpt not found in source [{n}]",
            )
        return RowCheck(section=section, claim=claim, source=n, ok=True)

    checks: list[RowCheck] = []
    moved: list[str] = []
    out = data.model_copy(deep=True)

    timeline: list[TimelineItem] = []
    for item in out.timeline:
        item.excerpt, cut = cap_words(item.excerpt, max_words)
        result = await verify("timeline", f"{item.date}: {item.event}", item.source, item.excerpt)
        result.truncated = cut
        checks.append(result)
        if result.ok:
            timeline.append(item)
        else:
            moved.append(f"{item.date}: {item.event} — {result.reason}")
    out.timeline = timeline

    numbers: list[KeyNumber] = []
    for num in out.key_numbers:
        num.excerpt, cut = cap_words(num.excerpt, max_words)
        result = await verify(
            "key_numbers", f"{num.figure} — {num.meaning}", num.source, num.excerpt
        )
        result.truncated = cut
        if result.ok and not figure_supported(num.figure, num.excerpt):
            result.ok, result.reason = False, f"the figure {num.figure!r} isn't in its excerpt"
        checks.append(result)
        if result.ok:
            numbers.append(num)
        else:
            moved.append(f"{num.figure} ({num.meaning}) — {result.reason}")
    out.key_numbers = numbers

    if out.twist_excerpt:
        out.twist_excerpt, _ = cap_words(out.twist_excerpt, max_words)
    twist = await verify("twist", out.twist, out.twist_source, out.twist_excerpt)
    checks.append(twist)
    if not twist.ok:
        moved.append(f"Twist: {out.twist} — {twist.reason}")
        out.twist = "Unverified: see Open Questions."
        out.twist_source = out.twist_excerpt = None

    for person in out.key_people:  # optional: checked only when a source is given
        if person.source is None and not person.excerpt:
            continue
        if person.excerpt:
            person.excerpt, _ = cap_words(person.excerpt, max_words)
        result = await verify(
            "key_people", f"{person.name}, {person.role}", person.source, person.excerpt
        )
        checks.append(result)
        if not result.ok:
            moved.append(f"{person.name} ({person.role}) — {result.reason}")
            person.source, person.excerpt = None, None
            person.role = f"{person.role} (unverified)"

    out.open_questions = [*out.open_questions, *(f"Unverified: {m}" for m in moved)]
    return out, checks, fetch_errors


# ---------------------------------------------------------------------------- rendering
def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(
    d: DossierIn, primary: dict[int, bool], checks: list[RowCheck], version: int
) -> str:
    def cite(n: int | None) -> str:
        if n is None:
            return ""
        src = next((s for s in d.sources if s.n == n), None)
        return f"[[{n}]]({src.url})" if src else f"[{n}]"

    passed = sum(1 for c in checks if c.ok)
    lines = [
        f"# {d.title} — Research Dossier",
        "",
        f"*Version {version}. Excerpt check: {passed} of {len(checks)} claims verified against "
        "their sources; the rest are listed under Open Questions.*",
        "",
        "## Summary",
        d.summary,
        "",
        "## The Twist",
        d.twist + (f" {cite(d.twist_source)}" if d.twist_source else ""),
    ]
    if d.twist_excerpt:
        lines += ["", f"> {d.twist_excerpt}"]
    lines += ["", "## Timeline"]
    lines += [f"- **{t.date}**: {t.event} {cite(t.source)} — “{t.excerpt}”" for t in d.timeline]
    lines += ["", "## Key People"]
    lines += [
        f"- **{p.name}**: {p.role}" + (f" {cite(p.source)}" if p.source else "")
        for p in d.key_people
    ]
    lines += [
        "",
        "## Key Numbers",
        "| Figure | Meaning | Source | Supporting excerpt |",
        "|---|---|---|---|",
    ]
    for k in d.key_numbers:
        src = next((s for s in d.sources if s.n == k.source), None)
        url = src.url if src else ""
        lines.append(
            f"| {_cell(k.figure)} | {_cell(k.meaning)} | [[{k.source}]]({url}) "
            f"| “{_cell(k.excerpt)}” |"
        )
    b = d.story_beats
    lines += [
        "",
        "## Story Beats",
        f"- **Rise:** {b.rise}",
        f"- **Peak:** {b.peak}",
        f"- **Cracks:** {b.cracks}",
        f"- **Fall / comeback:** {b.fall}",
        f"- **Aftermath:** {b.aftermath}",
        "",
        "## Hook Ideas",
        *[f"{i}. {h}" for i, h in enumerate(d.hook_ideas, start=1)],
        "",
        "## Best Angle for a Short",
        d.best_short_angle,
        "",
        "## Best Angle for Long-form",
        d.best_long_angle,
        "",
        "## Open Questions / Unverified",
        *([f"- {q}" for q in d.open_questions] or ["- None."]),
        "",
        "## Sources",
    ]
    for s in sorted(d.sources, key=lambda s: s.n):
        tag = " **(primary)**" if primary.get(s.n) else ""
        kind = f" — {s.kind}" if s.kind else ""
        lines.append(f"{s.n}. [{s.title}]({s.url}){kind}{tag}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------- save
def sources_json(
    d: DossierIn, primary: dict[int, bool], checks: list[RowCheck]
) -> list[dict[str, Any]]:
    out = []
    for s in sorted(d.sources, key=lambda s: s.n):
        used = [c for c in checks if c.source == s.n]
        out.append(
            {
                "n": s.n,
                "url": s.url,
                "title": s.title,
                "kind": s.kind,
                "source_type": "primary" if primary.get(s.n) else "secondary",
                "claims_checked": len(used),
                "claims_verified": sum(1 for c in used if c.ok),
            }
        )
    return out


async def save_dossier(
    engine: Engine,
    story_id: int,
    data: DossierIn,
    lookup: TextLookup,
    *,
    second_opinion: dict[str, Any] | None = None,
    run_id: int | None = None,
    research_dir: Path | None = None,
) -> dict[str, Any]:
    cfg = load_scoring().research
    with Session(engine) as s:
        story = s.get(Story, story_id)
        if story is None:
            raise LookupError(f"no story {story_id}")
        slug = story.slug
    cleaned, checks, fetch_errors = await check_rows(
        data, lookup, int(cfg.get("excerpt_max_words", 40))
    )
    domains = list(cfg.get("primary_domains", []))
    primary = {src.n: is_primary(src.url, domains) for src in cleaned.sources}

    with Session(engine) as s:
        version = (
            int(
                s.exec(
                    select(func.coalesce(func.max(Dossier.version), 0)).where(
                        Dossier.story_id == story_id
                    )
                ).one()
            )
            + 1
        )
    markdown = render_markdown(cleaned, primary, checks, version)
    srcs = sources_json(cleaned, primary, checks)
    passed = sum(1 for c in checks if c.ok)
    summary = {
        "passed": passed,
        "failed": len(checks) - passed,
        "truncated": sum(1 for c in checks if c.truncated),
        "rows": [c.model_dump() for c in checks],
        "fetch_errors": fetch_errors,
    }

    folder = (research_dir or RESEARCH_DIR) / slug
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "dossier.md").write_text(markdown)
    (folder / "sources.json").write_text(json.dumps(srcs, indent=2, ensure_ascii=False) + "\n")

    with Session(engine) as s:
        dossier = Dossier(
            story_id=story_id,
            version=version,
            markdown=markdown,
            sources_json=srcs,
            second_opinion=second_opinion,
            data=cleaned.model_dump(),
            checks=summary,
            run_id=run_id,
            export_path=str(folder / "dossier.md"),
        )
        s.add(dossier)
        known = {
            row.url for row in s.exec(select(StorySource).where(StorySource.story_id == story_id))
        }
        excerpts: dict[int, str] = {}
        for t in cleaned.timeline:
            excerpts.setdefault(t.source, t.excerpt)
        for k in cleaned.key_numbers:
            excerpts.setdefault(k.source, k.excerpt)
        for src in cleaned.sources:
            if src.url not in known:
                s.add(
                    StorySource(
                        story_id=story_id,
                        url=src.url,
                        title=src.title,
                        source_type="primary" if primary[src.n] else "secondary",
                        excerpt=excerpts.get(src.n),
                        added_by="researcher",
                    )
                )
        row = s.get(Story, story_id)
        if row is not None:
            row.updated_at = utcnow()
            s.add(row)
        s.commit()
        s.refresh(dossier)
        dossier_id = dossier.id
    return {
        "dossier_id": dossier_id,
        "story_id": story_id,
        "version": version,
        "excerpt_check": {k: summary[k] for k in ("passed", "failed", "truncated")},
        "moved_to_open_questions": [
            f"{c.section}: {c.claim} — {c.reason}" for c in checks if not c.ok
        ],
        "primary_sources": sum(1 for v in primary.values() if v),
        "export": str(folder / "dossier.md"),
    }


def list_dossiers(engine: Engine) -> list[dict[str, Any]]:
    """Latest version per story, newest first."""
    with Session(engine) as s:
        rows = s.exec(select(Dossier).order_by(col(Dossier.created_at).desc())).all()
        latest: dict[int, Dossier] = {}
        versions: dict[int, list[int]] = {}
        for d in rows:
            latest.setdefault(d.story_id, d)
            versions.setdefault(d.story_id, []).append(d.version)
        out = []
        for story_id, d in latest.items():
            story = s.get(Story, story_id)
            out.append(_summary(d, story, sorted(versions[story_id])))
        return out


def _summary(d: Dossier, story: Story | None, versions: list[int]) -> dict[str, Any]:
    checks = d.checks or {}
    flags = (d.second_opinion or {}).get("flags") or []
    return {
        "id": d.id,
        "story_id": d.story_id,
        "story_title": story.title if story else f"Story #{d.story_id}",
        "slug": story.slug if story else None,
        "status": story.status if story else None,
        "version": d.version,
        "versions": versions,
        "created_at": d.created_at.isoformat(),
        "run_id": d.run_id,
        "excerpt_check": {"passed": checks.get("passed", 0), "failed": checks.get("failed", 0)},
        "flags": len(flags),
        "source_count": len(d.sources_json or []),
        "primary_count": sum(1 for x in d.sources_json or [] if x.get("source_type") == "primary"),
    }


def get_dossier(engine: Engine, story_id: int, version: int | None = None) -> dict[str, Any] | None:
    with Session(engine) as s:
        stmt = select(Dossier).where(Dossier.story_id == story_id)
        rows = s.exec(stmt.order_by(col(Dossier.version).desc())).all()
        if not rows:
            return None
        d = next((r for r in rows if r.version == version), None) if version else rows[0]
        if d is None:
            return None
        story = s.get(Story, story_id)
        return _summary(d, story, sorted(r.version for r in rows)) | {
            "markdown": d.markdown,
            "sources": d.sources_json or [],
            "second_opinion": d.second_opinion,
            "checks": d.checks,
            "export_path": d.export_path,
        }
