"""@scout — story discovery (SPEC §6.1).

News mode: pull feeds/searches → normalize → drop stale/known → exact dedup (URL hash, title)
→ semantic dedup (embeddings vs. each other and existing stories) → score → save top `limit`.

Evergreen mode ("gap finder"): crawl Wikipedia categories → article length/refs/pageviews →
pre-score → YouTube coverage check for the top N, within today's search-call and unit budget
→ gap score → save top `limit`.

Every source and provider failure is logged to the run and reported in the result; it never
ends the run unless nothing at all could be scored.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any

from apps.api import prompts
from apps.api.agents.dedup import (
    load_vectors,
    normalize_url,
    save_vector,
    semantic_dedupe,
    title_key,
)
from apps.api.agents.params import ScoutParams
from apps.api.config import load_engine, load_providers, load_scoring, load_sources
from apps.api.db.session import get_engine
from apps.api.providers.base import ProviderError
from apps.api.providers.router import get_router
from apps.api.providers.schemas import ItemScore, ItemToScore
from apps.api.settings import get_settings
from apps.api.sources import edgar, gdelt, hackernews, news_rss, reddit_rss, wikipedia, youtube
from apps.api.sources._http import SourceError, truncate
from apps.api.sources.models import SourceItem
from apps.api.stories import (
    PRIMARY_SOURCES,
    SourceIn,
    StoryIn,
    create_story,
    known_source_urls,
    known_titles,
    total_score,
)
from apps.api.usage_report import youtube_used_today

if TYPE_CHECKING:
    from apps.api.jobs import RunContext

SCORE_CHUNK = 20  # items per score_items call, so one failing call loses little
EMBED_REF = "story"


@dataclass
class Lead:
    item: SourceItem
    origin: str  # which feed/query produced it
    primary: bool = False
    vector: list[float] | None = None
    score: ItemScore | None = None
    extra_sources: list[SourceItem] = field(default_factory=list)


@dataclass
class Report:
    """Counts and problems that end up in the run result."""

    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    source_errors: list[str] = field(default_factory=list)
    provider_errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------- entry point
async def run(ctx: RunContext) -> dict[str, Any]:
    params = ScoutParams.model_validate(ctx.params)
    report = Report()
    created: list[dict[str, Any]] = []
    if params.mode == "both":
        news_limit, ever_limit = math.ceil(params.limit / 2), params.limit // 2
    else:
        news_limit = ever_limit = params.limit

    if params.mode in ("news", "both"):
        created += await run_news(ctx, params, news_limit, report)
    if params.mode in ("evergreen", "both") and ever_limit > 0:
        created += await run_evergreen(ctx, params, ever_limit, report)

    created.sort(key=lambda s: s["score"] or 0, reverse=True)
    summary = f"Scout found {len(created)} new stor{'y' if len(created) == 1 else 'ies'}"
    if created:
        summary += ". Top: " + "; ".join(f"{s['title']} ({s['score']})" for s in created[:5])
    ctx.step("Done", 1.0)
    return {
        "summary": summary,
        "stories": created,
        "counts": dict(report.counts),
        "source_errors": report.source_errors,
        "provider_errors": report.provider_errors,
        "notes": report.notes,
    }


# ---------------------------------------------------------------------------- news mode
async def run_news(
    ctx: RunContext, p: ScoutParams, limit: int, report: Report
) -> list[dict[str, Any]]:
    engine = get_engine()
    scoring = load_scoring().scout
    ctx.step("News: fetching feeds", 0.02)
    leads = await fetch_news(ctx, p, report)
    report.counts["news_fetched"] = len(leads)
    ctx.log(
        "info",
        f"Fetched {len(leads)} items from {len({lead.origin for lead in leads})} feeds/queries",
    )

    leads = drop_stale(leads, int(scoring.get("max_age_days", 30)))
    leads, exact = exact_dedupe(leads, known_source_urls(engine), known_titles(engine))
    report.counts["news_exact_duplicates"] = exact
    leads = cap_round_robin(leads, int(scoring.get("max_items_to_score", 80)))
    ctx.log("info", f"{len(leads)} unique, recent items after exact dedup ({exact} dropped)")

    ctx.step("News: semantic dedup", 0.25)
    leads, model = await semantic_pass(ctx, leads, report, int(scoring.get("embed_batch_size", 50)))
    report.counts["news_unique"] = len(leads)
    if not leads:
        report.notes.append("No new news items after deduplication.")
        return []

    ctx.step(f"News: scoring {len(leads)} items", 0.4)
    await score_leads(ctx, leads, p, report, progress=(0.4, 0.7))
    scored = [lead for lead in leads if lead.score is not None]
    report.counts["news_scored"] = len(scored)
    ranked = rank(scored, p.series)[:limit]

    ctx.step(f"News: saving {len(ranked)} stories", 0.72)
    out = []
    for lead in ranked:
        assert lead.score is not None
        story = create_story(
            engine,
            StoryIn(
                title=clean_title(lead.item.title),
                company=lead.score.company,
                series=lead.score.series,
                format=lead.score.format,
                hook=lead.score.hook,
                scores=score_dict(lead.score),
                notes=f"Found by @scout (run #{ctx.run_id}) via {lead.origin}.",
                sources=[to_source(lead.item, lead.primary)]
                + [to_source(s, False) for s in lead.extra_sources[:4]],
            ),
            added_by="scout",
        )
        assert story.id is not None
        if lead.vector is not None and model:
            save_vector(engine, EMBED_REF, story.id, model, lead.vector)
        out.append(
            {
                "id": story.id,
                "title": story.title,
                "score": (story.scores or {}).get("total"),
                "series": story.series,
                "mode": "news",
            }
        )
    report.counts["news_saved"] = len(out)
    ctx.log("info", f"Saved {len(out)} news stories")
    return out


async def fetch_news(ctx: RunContext, p: ScoutParams, report: Report) -> list[Lead]:
    src = load_sources().news
    scoring = load_scoring().scout
    per = int(scoring.get("per_query_limit", 15))
    days = int(scoring.get("max_age_days", 30))
    since = (datetime.now(UTC) - timedelta(days=days)).date().isoformat()
    topic = (p.topic or "").strip()
    jobs: list[tuple[str, bool, Callable[[], Awaitable[list[SourceItem]]]]] = []

    def add(origin: str, primary: bool, fn: Callable[[], Awaitable[list[SourceItem]]]) -> None:
        jobs.append((origin, primary, fn))

    if topic:
        gn_queries = [
            f"{topic} {suffix}".strip() for suffix in src.get("topic_query_suffixes", [""])
        ]
    else:
        gn_queries = list(src.get("google_news_queries", []))
    for q in gn_queries:
        add(f"Google News: {q}", False, partial(news_rss.google_news, q, per, when=f"{days}d"))

    for feed in src.get("press_feeds", []):
        add(feed["name"], True, partial(news_rss.feed, feed["url"], feed["name"], limit=50))

    edgar_queries = (
        [{"q": f'"{topic}"', "forms": "8-K"}]
        if topic
        else list(src.get("edgar_full_text_queries", []))
    )
    if get_settings().sec_user_agent:
        for eq in edgar_queries:
            add(
                f"EDGAR full-text: {eq['q']}",
                True,
                partial(edgar.full_text_search, eq["q"], eq.get("forms"), start=since, limit=per),
            )
    else:
        report.source_errors.append("EDGAR skipped: SEC_USER_AGENT is not set")

    for q in [topic] if topic else src.get("hackernews_queries", []):
        add(
            f"Hacker News: {q}",
            False,
            partial(hackernews.search, q, limit=per, recent=True, min_points=20),
        )

    for sub in src.get("subreddits", []):
        if topic:
            add(f"r/{sub}: {topic}", False, partial(reddit_rss.search, topic, sub, limit=per))
        else:
            add(f"r/{sub}", False, partial(reddit_rss.subreddit, sub, "top", limit=per))

    for q in [topic] if topic else src.get("gdelt_queries", []):
        add(f"GDELT: {q}", False, partial(gdelt.search, q, timespan=f"{days}d", limit=per))

    async def one(
        origin: str, primary: bool, fn: Callable[[], Awaitable[list[SourceItem]]]
    ) -> list[Lead]:
        try:
            items = await fn()
        except SourceError as e:
            report.source_errors.append(f"{origin}: {e}")
            ctx.log("warn", f"Source failed, skipped: {origin}: {e}")
            return []
        except Exception as e:  # unexpected parser errors etc. must not end the run
            report.source_errors.append(f"{origin}: {type(e).__name__}: {e}")
            ctx.log("warn", f"Source failed, skipped: {origin}: {type(e).__name__}: {e}")
            return []
        if topic and primary and origin in {f["name"] for f in src.get("press_feeds", [])}:
            items = [i for i in items if topic.lower() in f"{i.title} {i.snippet}".lower()]
        return [
            Lead(item=i, origin=origin, primary=primary)
            for i in items[: max(per, 50)]
            if i.url and i.title
        ]

    results = await asyncio.gather(*(one(o, pr, fn) for o, pr, fn in jobs))
    return [lead for batch in results for lead in batch]


def drop_stale(leads: list[Lead], max_age_days: int) -> list[Lead]:
    cutoff = datetime.now(UTC) - timedelta(days=max_age_days)
    fresh = []
    for lead in leads:
        published = parse_date(lead.item.published_at)
        if published is None or published >= cutoff:
            fresh.append(lead)
    return fresh


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def exact_dedupe(
    leads: list[Lead], known_urls: set[str], known_story_titles: set[str]
) -> tuple[list[Lead], int]:
    """Drop items whose normalized URL or headline was already seen (in this run or saved)."""
    seen_urls = {normalize_url(u) for u in known_urls}
    seen_titles = {title_key(t) for t in known_story_titles}
    # Primary sources first, so a press release beats a re-post of it.
    ordered = sorted(leads, key=lambda lead: not lead.primary)
    kept: list[Lead] = []
    by_title: dict[str, Lead] = {}
    dropped = 0
    for lead in ordered:
        url = normalize_url(lead.item.url)
        key = title_key(lead.item.title)
        if url in seen_urls or (key and key in seen_titles and key not in by_title):
            dropped += 1
            continue
        if key and key in by_title:
            by_title[key].extra_sources.append(lead.item)  # same headline elsewhere = extra source
            seen_urls.add(url)
            dropped += 1
            continue
        seen_urls.add(url)
        if key:
            by_title[key] = lead
        kept.append(lead)
    return kept, dropped


def cap_round_robin(leads: list[Lead], cap: int) -> list[Lead]:
    """Keep at most `cap` items, taking them round-robin across feeds (newest first in each)."""
    groups: dict[str, list[Lead]] = defaultdict(list)
    for lead in leads:
        groups[lead.origin].append(lead)
    for group in groups.values():
        group.sort(
            key=lambda lead: parse_date(lead.item.published_at) or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
    picked: list[Lead] = []
    while len(picked) < cap and any(groups.values()):
        for origin in list(groups):
            if groups[origin] and len(picked) < cap:
                picked.append(groups[origin].pop(0))
    return picked


def embed_text(item: SourceItem) -> str:
    return f"{clean_title(item.title)}. {truncate(item.snippet, 300)}"


async def semantic_pass(
    ctx: RunContext, leads: list[Lead], report: Report, batch: int
) -> tuple[list[Lead], str | None]:
    """Embedding dedup against each other and saved stories. Skipped (exact dedup only) if
    embeddings fail or providers switch models mid-run (vectors wouldn't be comparable)."""
    if not leads:
        return leads, None
    router = get_router()
    vectors: list[list[float]] = []
    model: str | None = None
    try:
        for start in range(0, len(leads), batch):
            result = await router.embed(
                [embed_text(lead.item) for lead in leads[start : start + batch]]
            )
            if model and result.model != model:
                raise ProviderError(
                    "router", f"embedding model changed mid-run ({model} → {result.model})"
                )
            model = result.model
            vectors += result.vectors
    except ProviderError as e:
        report.provider_errors.append(f"embed: {e}")
        ctx.log("warn", f"Semantic dedup skipped (exact dedup still applied): {e}")
        return leads, None
    assert model is not None
    threshold = float(load_scoring().dedup.get("embedding_cosine_threshold", 0.88))
    existing = load_vectors(get_engine(), EMBED_REF, model)
    kept, dupes = semantic_dedupe(vectors, existing, threshold)
    for d in dupes:
        if d.of_item is not None:
            leads[d.of_item].extra_sources.append(leads[d.index].item)
    report.counts["news_semantic_duplicates"] = len(dupes)
    report.counts["news_duplicates_of_saved_stories"] = sum(1 for d in dupes if d.of_story)
    ctx.log(
        "info",
        f"Semantic dedup ({model}, ≥{threshold}): dropped {len(dupes)} "
        f"({report.counts['news_duplicates_of_saved_stories']} already saved as stories)",
    )
    for i, lead in enumerate(leads):
        lead.vector = vectors[i]
    return [leads[i] for i in kept], model


async def score_leads(
    ctx: RunContext,
    leads: list[Lead],
    p: ScoutParams,
    report: Report,
    progress: tuple[float, float],
) -> None:
    router = get_router()
    hint = prompts.render("scout_series_hint", series=p.series) if p.series else ""
    chunks = [leads[i : i + SCORE_CHUNK] for i in range(0, len(leads), SCORE_CHUNK)]
    for n, chunk in enumerate(chunks, start=1):
        items = [
            ItemToScore(
                id=str(i),
                title=lead.item.title,
                snippet=truncate(lead.item.snippet, 400),
                source=lead.item.source,
                url=lead.item.url,
            )
            for i, lead in enumerate(chunk)
        ]
        try:
            scores = await router.score_items(items, series_hint=hint)
        except ProviderError as e:
            report.provider_errors.append(f"score_items: {e}")
            ctx.log("error", f"Scoring batch {n}/{len(chunks)} failed, skipped: {e}")
            continue
        for score in scores:
            if score.id.isdigit() and int(score.id) < len(chunk):
                chunk[int(score.id)].score = score
        lo, hi = progress
        ctx.step(f"Scored batch {n}/{len(chunks)}", lo + (hi - lo) * n / len(chunks))
    if leads and not any(lead.score for lead in leads):
        raise RuntimeError(
            "Every scoring call failed; no stories could be ranked. "
            + "; ".join(report.provider_errors[-3:])
        )


def score_dict(score: ItemScore) -> dict[str, Any]:
    return score.model_dump(
        include={"drama", "twist", "relatability", "visual_potential", "hook_number", "freshness"}
    )


def rank(leads: list[Lead], series: str | None) -> list[Lead]:
    def key(lead: Lead) -> tuple[bool, float]:
        assert lead.score is not None
        return (
            bool(series) and lead.score.series == series,
            total_score(score_dict(lead.score)) or 0,
        )

    return sorted(leads, key=key, reverse=True)


def clean_title(title: str) -> str:
    """Drop the ' - Publisher' suffix Google News adds to headlines."""
    return re.sub(r"\s+-\s+[^-]{2,60}$", "", title.strip()) or title.strip()


def to_source(item: SourceItem, primary: bool) -> SourceIn:
    is_primary = primary or item.source in PRIMARY_SOURCES
    excerpt = truncate(item.snippet, 280)
    if title_key(excerpt).startswith(title_key(clean_title(item.title))):
        excerpt = ""  # Google News "snippets" just repeat the headline
    return SourceIn(
        url=item.url,
        title=truncate(item.title, 200),
        source_type="primary" if is_primary else "secondary",
        excerpt=excerpt or None,
    )


# ---------------------------------------------------------------------------- evergreen mode
@dataclass
class Candidate:
    title: str
    url: str
    length: int = 0
    references: int = 0
    pageviews: int = 0
    summary: str = ""
    score: ItemScore | None = None
    popular_videos: int | None = None  # None = coverage not checked
    top_video: str | None = None
    gap: float | None = None


def youtube_budget(engine: Any) -> tuple[int, int, int]:
    """(search calls allowed, units allowed, search calls used today), after reserves."""
    providers = load_providers()
    limits = providers.providers["youtube"].limits
    gap = load_scoring().gap_finder
    units_used, searches_used = youtube_used_today(engine, load_engine())
    search_left = (
        (limits.get("search_calls_per_day") or 100)
        - searches_used
        - int(gap.get("search_calls_reserve", 10))
    )
    units_left = (
        (limits.get("units_per_day") or 10000) - units_used - int(gap.get("units_reserve", 500))
    )
    return max(0, search_left), max(0, units_left), searches_used


UNITS_PER_CHECK = youtube.UNIT_COST["search"] + youtube.UNIT_COST["videos"]


def estimate(params: dict[str, Any]) -> dict[str, Any]:
    """Plan-card estimate: YouTube calls this run may use (SPEC §6.1 step 5).

    Evergreen always checks the top N pre-scored articles (sources.yaml), independent of
    `limit`, so the gap ranking has candidates to choose from."""
    p = ScoutParams.model_validate(params)
    if p.mode == "news":
        return {"youtube_search_calls": 0, "youtube_units": 0}
    checks = int(load_sources().evergreen.get("top_n_for_youtube_check", 20))
    return {
        "youtube_search_calls": checks,
        "youtube_units": checks * UNITS_PER_CHECK,
        "note": "upper bound; capped by today's remaining YouTube budget",
    }


async def run_evergreen(
    ctx: RunContext, p: ScoutParams, limit: int, report: Report
) -> list[dict[str, Any]]:
    engine = get_engine()
    ever = load_sources().evergreen
    gap_cfg = load_scoring().gap_finder
    days = int(ever.get("pageview_days", 60))

    ctx.step("Evergreen: crawling Wikipedia categories", 0.75)
    candidates = await crawl_categories(ctx, ever, report)
    known = known_titles(engine)
    known_urls = known_source_urls(engine)
    candidates = [c for c in candidates if c.title.lower() not in known and c.url not in known_urls]
    report.counts["evergreen_articles"] = len(candidates)
    if p.topic:
        topic = p.topic.lower()
        candidates.sort(key=lambda c: topic not in c.title.lower())  # topic matches first
    if not candidates:
        report.notes.append("No new Wikipedia articles in the configured categories.")
        return []

    try:
        lengths = await wikipedia.page_lengths([c.title for c in candidates])
    except SourceError as e:
        report.source_errors.append(f"Wikipedia lengths: {e}")
        ctx.log("warn", f"Could not fetch article lengths: {e}")
        lengths = {}
    for c in candidates:
        c.length = lengths.get(c.title, 0)
    detailed = sorted(candidates, key=lambda c: c.length, reverse=True)[
        : int(ever.get("max_articles_detailed", 60))
    ]

    ctx.step(f"Evergreen: reading {len(detailed)} articles", 0.78)
    await enrich_articles(ctx, detailed, days, report)
    detailed = [c for c in detailed if c.summary]

    ctx.step(f"Evergreen: pre-scoring {len(detailed)} articles", 0.82)
    leads = [
        Lead(
            item=SourceItem(
                title=c.title,
                url=c.url,
                source="Wikipedia",
                snippet=f"{truncate(c.summary, 400)} (Wikipedia: {c.references} references, "
                f"{c.length:,} bytes, {c.pageviews:,} views in {days} days)",
            ),
            origin="Wikipedia",
        )
        for c in detailed
    ]
    await score_leads(ctx, leads, p, report, progress=(0.82, 0.88))
    for c, lead in zip(detailed, leads, strict=True):
        c.score = lead.score
    scored = sorted(
        (c for c in detailed if c.score is not None),
        key=lambda c: (total_score(score_dict(c.score)) if c.score else None) or 0.0,
        reverse=True,
    )
    report.counts["evergreen_scored"] = len(scored)

    # YouTube coverage check, within today's budget.
    top_n = int(ever.get("top_n_for_youtube_check", 20))
    search_left, units_left, searches_used = youtube_budget(engine)
    checks = min(top_n, len(scored), search_left, units_left // UNITS_PER_CHECK)
    if not get_settings().youtube_api_key:
        checks = 0
        report.source_errors.append("YouTube coverage check skipped: YOUTUBE_API_KEY is not set")
    if checks < min(top_n, len(scored)):
        msg = (
            f"YouTube budget allows {checks} coverage checks (wanted {min(top_n, len(scored))}; "
            f"{searches_used} search calls already used today)"
        )
        report.notes.append(msg)
        ctx.log("warn", msg)
    ctx.step(f"Evergreen: checking YouTube coverage for {checks} articles", 0.88)
    threshold = int(gap_cfg.get("youtube_view_threshold", 100000))
    per_check = int(gap_cfg.get("search_results_per_check", 10))
    calls = units = 0
    for i, c in enumerate(scored[:checks], start=1):
        try:
            found, top = await youtube_coverage(c.title, threshold, per_check)
        except SourceError as e:
            report.source_errors.append(f"YouTube coverage for {c.title}: {e}")
            ctx.log("warn", f"YouTube check failed for {c.title}: {e}")
            if "quota" in str(e).lower() or "403" in str(e):
                break  # out of quota: stop spending
            continue
        finally:
            calls += 1
            units += UNITS_PER_CHECK
        c.popular_videos, c.top_video = found, top
        ctx.log("info", f"YouTube coverage: {c.title}: {found} videos ≥ {threshold:,} views")
        ctx.step(f"YouTube check {i}/{checks}", 0.88 + 0.08 * i / max(checks, 1))
    report.counts["youtube_search_calls"] = calls
    report.counts["youtube_units"] = units

    for c in scored:
        c.gap = gap_score(c, gap_cfg)
    checked = [c for c in scored if c.gap is not None]
    ranked = sorted(checked, key=lambda c: c.gap or 0, reverse=True)
    if p.series:
        ranked.sort(key=lambda c: c.score is not None and c.score.series == p.series, reverse=True)
    ranked = ranked[:limit]

    ctx.step(f"Evergreen: saving {len(ranked)} stories", 0.97)
    out = []
    for c in ranked:
        assert c.score is not None
        note = (
            f"Found by @scout gap finder (run #{ctx.run_id}). Wikipedia: {c.references} refs, "
            f"{c.length:,} bytes, {c.pageviews:,} views/{days}d. YouTube: {c.popular_videos} "
            f"videos ≥ {threshold:,} views"
            + (f" (top: {c.top_video})" if c.top_video else "")
            + "."
        )
        story = create_story(
            engine,
            StoryIn(
                title=c.title,
                company=c.score.company or c.title,
                series=c.score.series,
                format=c.score.format,
                hook=c.score.hook,
                scores=score_dict(c.score),
                gap_score=c.gap,
                notes=note,
                sources=[
                    SourceIn(
                        url=c.url,
                        title=f"{c.title} — Wikipedia",
                        source_type="secondary",
                        excerpt=truncate(c.summary, 280) or None,
                    )
                ],
            ),
            added_by="scout",
        )
        out.append(
            {
                "id": story.id,
                "title": story.title,
                "score": (story.scores or {}).get("total"),
                "gap_score": c.gap,
                "series": story.series,
                "mode": "evergreen",
            }
        )
    report.counts["evergreen_saved"] = len(out)
    ctx.log(
        "info",
        f"Saved {len(out)} evergreen stories; YouTube used {calls} search calls, {units} units",
    )
    return out


async def crawl_categories(
    ctx: RunContext, ever: dict[str, Any], report: Report
) -> list[Candidate]:
    per_category = int(ever.get("per_category", 40))
    seen: dict[str, Candidate] = {}
    for name in ever.get("wikipedia_categories", []):
        try:
            members = await wikipedia.category(name, limit=per_category)
        except SourceError as e:
            report.source_errors.append(f"{name}: {e}")
            ctx.log("warn", f"Category failed, skipped: {name}: {e}")
            continue
        for m in members:
            if not m.is_subcategory and m.title not in seen:
                seen[m.title] = Candidate(title=m.title, url=m.url)
    ctx.log(
        "info",
        f"Crawled {len(ever.get('wikipedia_categories', []))} categories: {len(seen)} articles",
    )
    return list(seen.values())


async def enrich_articles(
    ctx: RunContext, candidates: list[Candidate], days: int, report: Report
) -> None:
    sem = asyncio.Semaphore(4)

    async def one(c: Candidate) -> None:
        async with sem:
            try:
                art = await wikipedia.article(c.title)
                c.summary, c.references, c.length = (
                    art.summary,
                    art.references,
                    art.length_bytes or c.length,
                )
                c.pageviews = (await wikipedia.pageviews(c.title, days)).total
            except SourceError as e:
                report.source_errors.append(f"Wikipedia {c.title}: {e}")

    await asyncio.gather(*(one(c) for c in candidates))
    failed = sum(1 for c in candidates if not c.summary)
    if failed:
        ctx.log("warn", f"{failed} Wikipedia articles could not be read and were skipped")


def core_name(title: str) -> str:
    return re.sub(r"\s*\(.*?\)\s*", " ", title).strip()


async def youtube_coverage(title: str, view_threshold: int, results: int) -> tuple[int, str | None]:
    """One search.list + one videos.list: videos about this company above the view threshold."""
    name = core_name(title)
    found = await youtube.search(f"{name} company story", max_results=results)
    if not found.video_ids:
        return 0, None
    stats = await youtube.videos(found.video_ids)
    words = [w for w in title_key(name).split() if len(w) > 2] or title_key(name).split()
    popular = [
        v
        for v in stats.videos
        if (v.views or 0) >= view_threshold and all(w in title_key(v.title) for w in words)
    ]
    popular.sort(key=lambda v: v.views or 0, reverse=True)
    return len(popular), popular[0].url if popular else None


def gap_score(c: Candidate, cfg: dict[str, Any]) -> float | None:
    """Gap = quality + article richness + low YouTube coverage (weights in scoring.yaml), 0–10."""
    if c.score is None or c.popular_videos is None:
        return None
    w = cfg.get("weights", {})
    quality = (total_score(score_dict(c.score)) or 0) / 10
    richness = (
        0.5 * min(1.0, c.references / float(cfg.get("richness_refs_full", 100)))
        + 0.25 * min(1.0, c.length / float(cfg.get("richness_length_full", 80000)))
        + 0.25
        * min(
            1.0,
            math.log10(c.pageviews + 1)
            / math.log10(float(cfg.get("richness_pageviews_full", 100000)) + 1),
        )
    )
    low_coverage = 1 - min(1.0, c.popular_videos / float(cfg.get("coverage_saturation", 5)))
    total_w = sum(float(v) for v in w.values()) or 1.0
    score = (
        float(w.get("story_quality", 0.5)) * quality
        + float(w.get("article_richness", 0.2)) * richness
        + float(w.get("low_coverage", 0.3)) * low_coverage
    ) / total_w
    return round(10 * score, 2)
