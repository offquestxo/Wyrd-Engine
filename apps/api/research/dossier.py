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

import contextlib
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
from apps.api.providers.base import ProviderError
from apps.api.providers.schemas import SupportItem, SupportResult
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
    action: Literal[
        "fixed",
        "softened",
        "labelled_interpretation",
        "moved_to_open_questions",
        "removed",
        "kept",
    ]
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


# ---------------------------------------------------------------------------- spelled numbers
_UNITS = {
    w: i
    for i, w in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
        ]
    )
}
_TENS = {
    w: 10 * i
    for i, w in enumerate(
        ["_", "_", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
    )
    if w != "_"
}
_WORD = "|".join([*_UNITS, *_TENS, "hundred", "thousand"])
_WORD_RUN = re.compile(rf"\b(?:{_WORD})(?:(?:[\s-]+|\s+and\s+)(?:{_WORD}))*\b", re.IGNORECASE)


def _words_value(words: str) -> int | None:
    total = current = 0
    for w in re.split(r"[\s-]+", words.lower()):
        if w == "and":
            continue
        if w in _UNITS:
            current += _UNITS[w]
        elif w in _TENS:
            current += _TENS[w]
        elif w == "hundred":
            current = max(current, 1) * 100
        elif w == "thousand":
            total += max(current, 1) * 1000
            current = 0
        else:
            return None
    return total + current


def words_to_digits(text: str) -> str:
    """ "eighteen months" → "18 months", "twenty-three" → "23" (for checking, not display)."""

    def repl(m: re.Match[str]) -> str:
        value = _words_value(m.group(0))
        return str(value) if value is not None else m.group(0)

    return _WORD_RUN.sub(repl, text)


# ---------------------------------------------------------------------------- durations
DURATION = re.compile(
    r"\b(?:(about|around|roughly|nearly|almost|some|over|more than|less than|under|just)\s+)?"
    r"(\d+)[\s-](day|week|month|year)s?\b(?:[\s-](?:later|after|before|earlier|old|on))?",
    re.IGNORECASE,
)
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"],
        start=1,
    )
}


class TimelineDate(BaseModel):
    year: int
    month: int | None = None
    day: int | None = None

    def months(self) -> float:
        return self.year * 12 + (self.month or 1) - 1 + ((self.day or 1) - 1) / 30.44


def parse_date(text: str) -> TimelineDate | None:
    """Timeline dates: 2008-11-10, 2008-11, 2008, Nov 2008, November 10, 2008, 10 Nov 2008."""
    t = text.strip()
    if m := re.fullmatch(r"(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?", t):
        y, mo, d = m.groups()
        return TimelineDate(year=int(y), month=int(mo) if mo else None, day=int(d) if d else None)
    if m := re.fullmatch(r"([A-Za-z]{3})[a-z]*\.?\s+(?:(\d{1,2}),?\s+)?(\d{4})", t):
        mon, d, y = m.groups()
        if mon.lower() in _MONTHS:
            return TimelineDate(year=int(y), month=_MONTHS[mon.lower()], day=int(d) if d else None)
    if m := re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{4})", t):
        d, mon, y = m.groups()
        if mon.lower() in _MONTHS:
            return TimelineDate(year=int(y), month=_MONTHS[mon.lower()], day=int(d))
    return None


def durations(text: str) -> list[tuple[str, int, str, bool]]:
    """(phrase, N, unit, approximate?) for each "N months later"-style span."""
    return [
        (m.group(0).strip(), int(m.group(2)), m.group(3).lower(), bool(m.group(1)))
        for m in DURATION.finditer(text)
    ]


def _gap(a: TimelineDate, b: TimelineDate, unit: str) -> float | None:
    if unit == "year" and (a.month is None or b.month is None):
        return float(abs(b.year - a.year))
    if a.month is None or b.month is None:
        return None
    if unit in ("day", "week") and (a.day is None or b.day is None):
        return None
    months = abs(b.months() - a.months())
    return {
        "year": months / 12,
        "month": months,
        "week": months * 30.44 / 7,
        "day": months * 30.44,
    }[unit]


def duration_matches(
    n: int, unit: str, approx: bool, dates: list[TimelineDate]
) -> tuple[bool, str | None]:
    """Does some pair of Timeline dates lie n units apart? Exact wording needs the rounded gap
    to equal n; "about n" allows ±1."""
    gaps = [
        g
        for i, a in enumerate(dates)
        for b in dates[i + 1 :]
        if (g := _gap(a, b, unit)) is not None and g > 0
    ]
    if not gaps:
        return False, None
    tolerance = 1 if approx else 0
    if any(abs(round(g) - n) <= tolerance for g in gaps):
        return True, None
    closest = min(gaps, key=lambda g: abs(g - n))
    return False, f"about {closest:.1f} {unit}s"


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


_SCALE = {"thousand": 1e3, "million": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "b": 1e9}
_PROSE_NUM = re.compile(
    r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(thousand|million|billion|bn|m|b)?\b", re.IGNORECASE
)


def prose_numbers(text: str) -> list[tuple[str, float, float]]:
    """(as written, value, rounding tolerance) for each specific number in prose. Years and
    single digits are skipped (too common to check usefully)."""
    out = []
    for m in _PROSE_NUM.finditer(text):
        token, scale_word = m.group(1).rstrip(",."), (m.group(2) or "").lower()
        digits = token.replace(",", "")
        if _is_year(digits) or (len(digits) < 2 and not scale_word):
            continue
        try:
            value = float(digits)
        except ValueError:
            continue
        scale = _SCALE.get(scale_word, 1.0)
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        out.append((m.group(0).strip(), value * scale, 0.5 * scale / 10**decimals))
    return out


def number_in_text(value: float, tolerance: float, text_numbers: set[float]) -> bool:
    """A source number equals the prose number, allowing filings' "in thousands" tables and
    the prose's rounding."""
    return any(abs(n * unit - value) <= tolerance for n in text_numbers for unit in (1.0, 1e3, 1e6))


def numbers_of(text: str) -> set[float]:
    found = set()
    for token in _NUM.findall(text):
        with contextlib.suppress(ValueError):
            found.add(float(token.replace(",", "")))
    return found


class RowCheck(BaseModel):
    section: str  # "timeline" | "key_numbers" | "twist" | "key_people"
    claim: str
    source: int | None
    ok: bool
    reason: str | None = None
    truncated: bool = False
    meta: dict[str, Any] | None = None  # support_check: who served it (fallback?)


META_SECTIONS = {"prose_numbers", "support_check"}  # not claim rows; counted separately
SupportFn = Callable[[list[SupportItem]], Awaitable[SupportResult]]


async def check_rows(
    data: DossierIn,
    lookup: TextLookup,
    max_words: int,
    support: SupportFn | None = None,
) -> tuple[DossierIn, list[RowCheck], dict[str, str]]:
    """Run the checks. Returns the cleaned dossier (failed rows moved to open questions), the
    per-row results, and per-source fetch errors. `support` (the router's check_support)
    checks that each excerpt supports every part of its claim; without it that step is
    skipped and recorded as skipped."""
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
    passed: list[tuple[str, Any, RowCheck]] = []  # rows that passed the excerpt check
    out = data.model_copy(deep=True)

    timeline: list[TimelineItem] = []
    for item in out.timeline:
        item.excerpt, cut = cap_words(item.excerpt, max_words)
        result = await verify("timeline", f"{item.date}: {item.event}", item.source, item.excerpt)
        result.truncated = cut
        checks.append(result)
        if result.ok:
            timeline.append(item)
            passed.append(("timeline", item, result))
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
            passed.append(("key_numbers", num, result))
        else:
            moved.append(f"{num.figure} ({num.meaning}) — {result.reason}")
    out.key_numbers = numbers

    if out.twist_excerpt:
        out.twist_excerpt, _ = cap_words(out.twist_excerpt, max_words)
    twist = await verify("twist", out.twist, out.twist_source, out.twist_excerpt)
    checks.append(twist)
    if twist.ok:
        passed.append(("twist", out, twist))
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
        if result.ok:
            passed.append(("key_people", person, result))
        if not result.ok:
            moved.append(f"{person.name} ({person.role}) — {result.reason}")
            person.source, person.excerpt = None, None
            person.role = f"{person.role} (unverified)"

    support_status, support_meta = await support_pass(out, passed, support, moved)
    checks.append(
        RowCheck(
            section="support_check", claim=support_status, source=None, ok=True, meta=support_meta
        )
    )

    # Specific numbers in the prose sections must come from a cited source too. They stay in
    # the prose (rewriting it is the researcher's job) but are listed as unverified.
    source_numbers: set[float] = set()
    for src in out.sources:
        text = await text_for(src.n)
        if text:
            source_numbers |= numbers_of(text)
    b = out.story_beats
    prose = {
        "Summary": out.summary,
        "Twist": out.twist,
        "Story Beats": " ".join([b.rise, b.peak, b.cracks, b.fall, b.aftermath]),
        "Hook Ideas": " ".join(out.hook_ideas),
        "Angles": f"{out.best_short_angle} {out.best_long_angle}",
    }
    dates = [d for d in (parse_date(t.date) for t in out.timeline) if d is not None]
    seen: set[str] = set()
    for section, raw in prose.items():
        text = words_to_digits(raw)
        # "N months later" spans must match the gap between two dated Timeline items.
        for phrase, n, unit, approx in durations(text):
            if phrase in seen:
                continue
            seen.add(phrase)
            ok, closest = duration_matches(n, unit, approx, dates)
            if ok:
                continue
            hint = f"; closest Timeline gap is {closest}" if closest else ""
            checks.append(
                RowCheck(
                    section="prose_numbers",
                    claim=f"{section}: “{phrase}”",
                    source=None,
                    ok=False,
                    reason=f"no two dated Timeline items are {n} {unit}s apart{hint}",
                )
            )
            moved.append(f"{section} says “{phrase}”, which doesn't match the Timeline dates{hint}")
        text = DURATION.sub(" ", text)
        for written, value, tolerance in prose_numbers(text):
            if written in seen or number_in_text(value, tolerance, source_numbers):
                continue
            seen.add(written)
            checks.append(
                RowCheck(
                    section="prose_numbers",
                    claim=f"{section}: “{written}”",
                    source=None,
                    ok=False,
                    reason="number not found in any cited source",
                )
            )
            moved.append(f"{section} mentions “{written}”, which no cited source contains")
    out.open_questions = [*out.open_questions, *(f"Unverified: {m}" for m in moved)]
    return out, checks, fetch_errors


def _claim_text(kind: str, row: Any) -> str:
    if kind == "timeline":
        return f"{row.date}: {row.event}"
    if kind == "key_numbers":
        return f"{row.figure} — {row.meaning}"
    if kind == "twist":
        return str(row.twist)
    return f"{row.name} — {row.role}"


def _apply_trim(kind: str, row: Any, trimmed: str) -> bool:
    """Put a trimmed claim back into its row. False if the trim doesn't fit the row."""
    trimmed = trimmed.strip()
    if kind == "timeline":
        prefix = f"{row.date}:"
        row.event = trimmed[len(prefix) :].strip() if trimmed.startswith(prefix) else trimmed
        return bool(row.event)
    if kind == "key_numbers":
        if not figure_supported(row.figure, trimmed):
            return False  # the figure itself was the unsupported part
        meaning = trimmed.split("—", 1)[1].strip() if "—" in trimmed else trimmed
        row.meaning = meaning
        return bool(meaning)
    if kind == "twist":
        row.twist = trimmed
        return True
    role = trimmed.split("—", 1)[1].strip() if "—" in trimmed else trimmed
    row.role = role
    return bool(role)


async def support_pass(
    out: DossierIn,
    passed: list[tuple[str, Any, RowCheck]],
    support: SupportFn | None,
    moved: list[str],
) -> tuple[str, dict[str, Any] | None]:
    """Claim-vs-excerpt support: a quote that exists can still be stretched by its claim.
    Unsupported details are trimmed (when what's left still stands) or the row moves to Open
    Questions. Returns a one-line status for the check summary, and who served the check
    (`fallback` is true when anything other than the primary checker answered)."""
    if not passed:
        return "nothing to check", None
    if support is None:
        return "skipped (no checker configured)", None
    items = [
        SupportItem(
            id=str(i),
            claim=_claim_text(kind, row),
            excerpt=(row.twist_excerpt if kind == "twist" else row.excerpt) or "",
        )
        for i, (kind, row, _) in enumerate(passed)
    ]
    try:
        result = await support(items)
    except ProviderError as e:
        return f"unavailable ({e}); rows kept on the excerpt check alone", None
    verdicts = {v.id: v for v in result.verdicts}
    meta = {"served_by": result.served_by, "primary": result.primary, "fallback": result.fallback}
    trimmed = removed = unchecked = 0
    drop: set[int] = set()
    for i, (kind, row, check) in enumerate(passed):
        verdict = verdicts.get(str(i))
        if verdict is None:
            unchecked += 1
            continue
        if verdict.supported:
            continue
        parts = "; ".join(verdict.unsupported_parts) or "parts of the claim"
        original = items[i].claim
        if verdict.trimmed_claim and _apply_trim(kind, row, verdict.trimmed_claim):
            trimmed += 1
            check.reason = f"trimmed: excerpt doesn't support {parts}"
            moved.append(f"Trimmed from “{original}”: {parts} (not in its excerpt)")
            continue
        removed += 1
        check.ok, check.reason = False, f"excerpt doesn't support: {parts}"
        moved.append(f"{original} — excerpt doesn't support: {parts}")
        drop.add(id(row))
        if kind == "twist":
            out.twist = "Unverified: see Open Questions."
            out.twist_source = out.twist_excerpt = None
        elif kind == "key_people":
            row.source, row.excerpt = None, None
            row.role = f"{row.role} (unverified)"
    out.timeline = [t for t in out.timeline if id(t) not in drop]
    out.key_numbers = [k for k in out.key_numbers if id(k) not in drop]
    status = f"{len(passed)} checked: {trimmed} trimmed, {removed} moved"
    if unchecked:
        status += f", {unchecked} without a verdict (kept)"
    if result.fallback:
        status += f" (checked by fallback: {', '.join(result.served_by)})"
    return status, meta


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

    rows = [c for c in checks if c.section not in META_SECTIONS]
    passed = sum(1 for c in rows if c.ok)
    prose = sum(1 for c in checks if c.section == "prose_numbers")
    note = f" {prose} number(s) in the prose weren't found in any cited source." if prose else ""
    support = next((c for c in checks if c.section == "support_check"), None)
    if support and support.meta and support.meta.get("fallback"):
        note += (
            " The claim-support check ran on a fallback model ("
            + ", ".join(support.meta.get("served_by", []))
            + "), which is more lenient; re-check with Groq."
        )
    lines = [
        f"# {d.title} — Research Dossier",
        "",
        f"*Version {version}. Excerpt check: {passed} of {len(rows)} claims verified against "
        f"their sources; the rest are listed under Open Questions.{note}*",
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
    support: SupportFn | None = None,
) -> dict[str, Any]:
    cfg = load_scoring().research
    with Session(engine) as s:
        story = s.get(Story, story_id)
        if story is None:
            raise LookupError(f"no story {story_id}")
        slug = story.slug
    cleaned, checks, fetch_errors = await check_rows(
        data, lookup, int(cfg.get("excerpt_max_words", 40)), support
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
    rows = [c for c in checks if c.section not in META_SECTIONS]
    passed = sum(1 for c in rows if c.ok)
    summary = {
        "passed": passed,
        "failed": len(rows) - passed,
        "prose_numbers_unverified": sum(1 for c in checks if c.section == "prose_numbers"),
        "support_check": next((c.claim for c in checks if c.section == "support_check"), "not run"),
        "support_checked_by": next(
            (c.meta for c in checks if c.section == "support_check" and c.meta), None
        ),
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
        "excerpt_check": {
            k: summary[k]
            for k in (
                "passed",
                "failed",
                "truncated",
                "prose_numbers_unverified",
                "support_check",
                "support_checked_by",
            )
        },
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
        "support_fallback": bool((checks.get("support_checked_by") or {}).get("fallback")),
        "support_checked_by": (checks.get("support_checked_by") or {}).get("served_by", []),
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


class RecheckUnavailable(RuntimeError):
    """The primary support checker (Groq) couldn't run; nothing was saved."""


async def recheck_with_primary(
    engine: Engine,
    story_id: int,
    support: Callable[[list[SupportItem]], Awaitable[SupportResult]],
    lookup: TextLookup,
    research_dir: Path | None = None,
) -> dict[str, Any]:
    """Re-run every check on the latest version with the primary support checker pinned
    (no fallback) and save the outcome as a new version. Used when a dossier was checked by a
    more lenient fallback model."""
    with Session(engine) as s:
        latest = s.exec(
            select(Dossier)
            .where(Dossier.story_id == story_id)
            .order_by(col(Dossier.version).desc())
        ).first()
        if latest is None or not latest.data:
            raise LookupError(f"no structured dossier for story {story_id}")
        data = DossierIn.model_validate(latest.data)
        review = dict(latest.second_opinion or {})

    async def primary_only(items: list[SupportItem]) -> SupportResult:
        try:
            return await support(items)
        except ProviderError as e:
            raise RecheckUnavailable(
                f"Groq couldn't run the check ({e}). Nothing was changed; try again in a minute."
            ) from e

    review["recheck_of_version"] = latest.version
    return await save_dossier(
        engine,
        story_id,
        data,
        lookup,
        second_opinion=review,
        research_dir=research_dir,
        support=primary_only,
    )
