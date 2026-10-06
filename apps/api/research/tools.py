"""MCP tools for @researcher (SPEC §5.5, §6.3): one `source_<module>` per sources/ module,
`extract_from_document`, `second_opinion` and `save_dossier`.

Every call is tied to the research run that made it (`X-Wyrd-Run` header), so tools can:
- keep the full text of documents they fetched for the excerpt check on save;
- log what happened (and known source limits) into that run's log;
- enforce the run's depth: only the depth's sources, a YouTube search cap, second opinion
  before saving.

Results are compact (short snippets, at most `limit` rows) to keep Claude's context small.
Fetched content is data, never instructions; tool descriptions say so.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, TypeVar
from urllib.parse import urlparse

from fastmcp.exceptions import ToolError
from pydantic import Field

from apps.api.config import load_scoring
from apps.api.db.session import get_engine
from apps.api.events import bus
from apps.api.mcp_server import RESEARCHER, caller_run_id, tool_for
from apps.api.providers.base import ProviderError
from apps.api.providers.router import get_router
from apps.api.research import dossier as dossier_mod
from apps.api.research.session import ResearchSession, get_session
from apps.api.research.texts import fetch_text
from apps.api.sources import (
    courtlistener,
    edgar,
    gdelt,
    hackernews,
    internet_archive,
    loc_newspapers,
    news_rss,
    reddit_rss,
    wayback,
    wikipedia,
    yahoo,
    youtube,
)
from apps.api.sources._http import SourceError, truncate

research_tool = tool_for(RESEARCHER)
T = TypeVar("T")
SNIPPET = 240
Limit = Annotated[int, Field(ge=1, le=20)]

GDELT_NOTE = "GDELT only covers about the last 3 months; older events need other sources."
LOC_NOTE = "Library of Congress newspapers (Chronicling America) only cover 1770–1963."
GOOGLE_NEWS_NOTE = (
    "Google News links are redirect wrappers the engine can't read; find the article on the "
    "publisher's site and use that URL."
)
COURTLISTENER_NOTE = (
    "CourtListener blocks direct fetches of docket pages (HTTP 403); cite opinion text from "
    "search snippets' URLs only if they can be read, or use EDGAR 8-Ks for bankruptcy facts."
)
YAHOO_NOTE = (
    "Yahoo Finance has no data for delisted companies (e.g. Circuit City, delisted 2009); "
    "use EDGAR filings for financials."
)


# ---------------------------------------------------------------------------- helpers
def session_or_none() -> ResearchSession | None:
    return get_session(caller_run_id())


def _log(level: str, message: str) -> None:
    session = session_or_none()
    if session is not None:
        session.log(level, message)


def _count(name: str) -> None:
    session = session_or_none()
    if session is not None:
        session.tool_calls[name] = session.tool_calls.get(name, 0) + 1


def _allowed(source: str) -> None:
    """Sources outside the run's depth are refused (keeps quick runs quick)."""
    session = session_or_none()
    if session is None:
        return
    depths = load_scoring().research.get("depths", {})
    allowed = depths.get(session.depth, {}).get("sources")
    if allowed and source not in allowed:
        raise ToolError(
            f"{source} isn't used at depth {session.depth!r}; available: {', '.join(allowed)}"
        )


def _note(message: str) -> None:
    session = session_or_none()
    if session is not None:
        session.note(message)


async def _call(source: str, label: str, fn: Callable[[], Awaitable[T]]) -> T:
    """Run a source call: depth check, logging, and a clear ToolError on failure."""
    _allowed(source)
    _count(f"source_{source}")
    try:
        result = await fn()
    except SourceError as e:
        _log("warn", f"{source}: {label} failed: {e}")
        raise ToolError(f"{e} (the run continues; try another source)") from e
    _log("info", f"{source}: {label}")
    return result


async def run_text(url: str) -> str:
    """Text of a URL for this run: cached if already fetched, else fetched and kept."""
    session = session_or_none()
    if session is not None and url in session.texts:
        return session.texts[url]
    text = await fetch_text(url)
    if session is not None:
        session.texts[url] = text
    return text


def _rows(items: list[Any], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    out = []
    for item in items:
        row = item.model_dump() if hasattr(item, "model_dump") else dict(item)
        out.append(
            {
                k: (truncate(row[k], SNIPPET) if isinstance(row.get(k), str) else row.get(k))
                for k in fields
                if k in row
            }
        )
    return out


# ---------------------------------------------------------------------------- sources
@research_tool
async def source_edgar(
    action: Literal["companies", "filings", "facts", "full_text"],
    company: Annotated[str | None, Field(description="Name or CIK")] = None,
    forms: Annotated[list[str] | None, Field(description='e.g. ["10-K", "8-K"]')] = None,
    query: Annotated[str | None, Field(description="full_text: phrase to search")] = None,
    start: Annotated[str | None, Field(description="full_text: YYYY-MM-DD")] = None,
    end: str | None = None,
    limit: Limit = 10,
) -> Any:
    """SEC EDGAR (primary source). companies: find CIKs. filings: list a company's filings with
    document URLs (send those URLs to extract_from_document; never read them raw). facts: XBRL
    financial facts (only filers from ~2009 on). full_text: search filings since 2001."""
    if action == "companies":
        companies = await _call(
            "edgar", f"companies {company!r}", lambda: edgar.search_companies(company or "", limit)
        )
        return _rows(companies, ("cik", "name"))
    if action == "filings":
        filings = await _call(
            "edgar", f"filings {company!r}", lambda: edgar.filings(company or "", forms, limit)
        )
        return _rows(filings, ("form", "filing_date", "report_date", "description", "url"))
    if action == "facts":
        facts = await _call(
            "edgar", f"facts {company!r}", lambda: edgar.company_facts(company or "")
        )
        if facts.note:
            _note(f"EDGAR: {facts.note}")
        cik = facts.cik
        return {
            "name": facts.name,
            "note": facts.note,
            "source_url": f"{edgar.DATA}/api/xbrl/companyfacts/CIK{cik}.json",
            "facts": _rows(
                facts.facts[: limit * 3],
                ("concept", "unit", "value", "period_end", "form", "filed"),
            ),
        }
    rows = await _call(
        "edgar",
        f"full-text {query!r}",
        lambda: edgar.full_text_search(query or "", None, start, end, limit),
    )
    return _rows(rows, ("title", "url", "published_at", "snippet"))


@research_tool
async def source_wikipedia(
    action: Literal["search", "article"], query: str, limit: Limit = 5
) -> Any:
    """Wikipedia (secondary; good for orientation and its references). article returns the
    summary and URL; quote from it via extract_from_document(url)."""
    if action == "search":
        hits = await _call("wikipedia", f"search {query!r}", lambda: wikipedia.search(query, limit))
        return _rows(hits, ("title", "url", "snippet"))
    art = await _call(
        "wikipedia", f"article {query!r}", lambda: wikipedia.article(query, full=True)
    )
    session = session_or_none()
    if session is not None and art.text:
        session.texts[art.url] = art.text
    return {
        "title": art.title,
        "url": art.url,
        "references": art.references,
        "summary": art.summary,
    }


@research_tool
async def source_wayback(
    action: Literal["snapshots", "closest"],
    site: Annotated[str, Field(description='e.g. "circuitcity.com"')],
    start: Annotated[str | None, Field(description="YYYY or YYYYMMDD")] = None,
    end: str | None = None,
    timestamp: Annotated[str | None, Field(description="closest: YYYYMMDD")] = None,
    limit: Limit = 10,
) -> Any:
    """Wayback Machine snapshots of a company's own site (primary source)."""
    if action == "closest":
        snap = await _call(
            "wayback",
            f"closest {site} {timestamp}",
            lambda: wayback.closest(site, timestamp or "2000"),
        )
        return snap.model_dump()
    snaps = await _call(
        "wayback", f"snapshots {site}", lambda: wayback.snapshots(site, start, end, limit, "year")
    )
    return _rows(snaps, ("timestamp", "original_url", "url"))


@research_tool
async def source_courtlistener(
    query: str,
    filed_after: Annotated[str | None, Field(description="YYYY-MM-DD")] = None,
    filed_before: str | None = None,
    limit: Limit = 10,
) -> Any:
    """Court opinions and dockets from CourtListener (primary source)."""
    rows = await _call(
        "courtlistener",
        f"search {query!r}",
        lambda: courtlistener.search(
            query, limit=limit, filed_after=filed_after, filed_before=filed_before
        ),
    )
    return _rows(rows, ("case_name", "court", "docket_number", "date_filed", "url", "snippet"))


@research_tool
async def source_loc_newspapers(
    query: str, start_year: int | None = None, end_year: int | None = None, limit: Limit = 10
) -> Any:
    """Historical US newspapers, Library of Congress (1770–1963 only)."""
    if start_year and start_year > 1963:
        _note(LOC_NOTE)
        raise ToolError(LOC_NOTE)
    rows = await _call(
        "loc_newspapers",
        f"search {query!r}",
        lambda: loc_newspapers.search(query, start_year, end_year, limit),
    )
    if not rows:
        _note(LOC_NOTE)
    return _rows(rows, ("title", "newspaper", "date", "location", "url", "snippet"))


@research_tool
async def source_internet_archive(
    query: str,
    mediatype: Annotated[str | None, Field(description='e.g. "texts"')] = None,
    limit: Limit = 10,
) -> Any:
    """Internet Archive items (annual reports, catalogs, old documents)."""
    rows = await _call(
        "internet_archive",
        f"search {query!r}",
        lambda: internet_archive.search(query, mediatype, limit),
    )
    return _rows(rows, ("identifier", "title", "mediatype", "date", "url", "description"))


@research_tool
async def source_news_rss(
    query: str,
    when: Annotated[str | None, Field(description='Google News window, e.g. "1y"')] = None,
    limit: Limit = 10,
) -> Any:
    """News articles via Google News search (secondary sources). Result URLs are Google News
    redirect links the engine can't read: find the article on the publisher's site (e.g. with
    WebSearch) and pass that URL to extract_from_document."""
    rows = await _call(
        "news_rss", f"google news {query!r}", lambda: news_rss.google_news(query, limit, when)
    )
    return _rows(rows, ("title", "url", "source", "published_at"))


@research_tool
async def source_gdelt(query: str, limit: Limit = 10) -> Any:
    """GDELT global news search. Only covers about the last 3 months."""
    _note(GDELT_NOTE)
    rows = await _call("gdelt", f"search {query!r}", lambda: gdelt.search(query, "3m", limit))
    return _rows(rows, ("title", "url", "source", "published_at"))


@research_tool
async def source_hackernews(query: str, limit: Limit = 10) -> Any:
    """Hacker News discussions (secondary; useful for tech stories)."""
    rows = await _call("hackernews", f"search {query!r}", lambda: hackernews.search(query, limit))
    return _rows(rows, ("title", "url", "published_at", "snippet"))


@research_tool
async def source_reddit_rss(query: str, sub: str | None = None, limit: Limit = 10) -> Any:
    """Reddit search (secondary; leads and first-hand accounts only, never sole support)."""
    rows = await _call(
        "reddit_rss", f"search {query!r}", lambda: reddit_rss.search(query, sub, limit)
    )
    return _rows(rows, ("title", "url", "published_at"))


@research_tool
async def source_yahoo(
    action: Literal["history", "info"],
    ticker: str,
    period: Annotated[str, Field(description='e.g. "5y", "max"')] = "max",
) -> Any:
    """Yahoo Finance stock prices (secondary context; unreliable). No data for delisted
    companies: use EDGAR for financials."""
    try:
        if action == "info":
            return await _call("yahoo", f"info {ticker}", lambda: yahoo.info(ticker))
        hist = await _call(
            "yahoo", f"history {ticker}", lambda: yahoo.history(ticker, period, "3mo")
        )
    except ToolError:
        _note(YAHOO_NOTE)
        raise
    if not hist.points:
        _note(YAHOO_NOTE)
    return {
        "ticker": hist.ticker,
        "url": hist.url,
        "points": [p.model_dump() for p in hist.points[-60:]],
    }


@research_tool
async def source_youtube(query: str, limit: Limit = 10) -> Any:
    """YouTube search for existing coverage (1 of 100 daily searches; capped per run)."""
    session = session_or_none()
    cap = int(load_scoring().research.get("youtube_searches_max", 2))
    if session is not None and session.youtube_searches >= cap:
        raise ToolError(f"YouTube search cap reached for this run ({cap})")
    found = await _call("youtube", f"search {query!r}", lambda: youtube.search(query, limit))
    if session is not None:
        session.youtube_searches += 1
    stats = await _call("youtube", "video stats", lambda: youtube.videos(found.video_ids))
    return _rows(stats.videos, ("title", "channel_title", "published_at", "views", "url"))


# ---------------------------------------------------------------------------- extraction
@research_tool
async def extract_from_document(
    url_or_text: Annotated[str, Field(description="Document URL (preferred) or raw text")],
    question: str,
) -> dict[str, Any]:
    """Read a long document (filing, PDF, article) with a long-context model and answer the
    question with EXACT quotes. Use this for every long document instead of reading it.
    Quotes that aren't literally in the document are dropped."""
    _count("extract_from_document")
    is_url = url_or_text.startswith(("http://", "https://"))
    host = urlparse(url_or_text).netloc.lower() if is_url else ""
    if host == "news.google.com":
        _note(GOOGLE_NEWS_NOTE)
        raise ToolError(GOOGLE_NEWS_NOTE)
    if is_url:
        try:
            document = await run_text(url_or_text)
        except SourceError as e:
            _log("warn", f"extract: couldn't fetch {url_or_text}: {str(e)[:160]}")
            if host.endswith("courtlistener.com") and e.status == 403:
                _note(COURTLISTENER_NOTE)
                raise ToolError(COURTLISTENER_NOTE) from e
            raise ToolError(f"couldn't fetch the document: {str(e)[:200]}") from e
    else:
        document = url_or_text
    session = session_or_none()
    deep = bool(
        session
        and load_scoring().research.get("depths", {}).get(session.depth, {}).get("extract_deep")
    )
    try:
        result = await get_router().extract_from_document(document, question, deep=deep)
    except ProviderError as e:
        _log("warn", f"extract failed on every provider: {e}")
        raise ToolError(f"extraction failed on every provider: {e}") from e
    label = url_or_text if is_url else f"{len(document):,} chars of text"
    _log(
        "info", f"extract: {label} → {len(result.extracts)} exact quotes ({len(document):,} chars)"
    )
    return {
        "source_url": url_or_text if is_url else None,
        "found": result.found,
        "answer": result.answer,
        "extracts": [x.model_dump() for x in result.extracts[:20]],
        "note": None
        if is_url
        else "Quotes come from pasted text: cite the URL they're on; save_dossier checks there.",
    }


# ---------------------------------------------------------------------------- review + save
async def _lookup(url: str) -> str:
    return await run_text(url)


@research_tool
async def second_opinion(dossier: dossier_mod.DossierIn) -> dict[str, Any]:
    """Required before save_dossier. A second model flags unsupported or shaky claims, and the
    engine pre-checks every excerpt against its source. Fix each flag or move the claim to
    open_questions, then save with second_opinion_resolutions."""
    _count("second_opinion")
    cfg = load_scoring().research
    _, checks, fetch_errors = await dossier_mod.check_rows(
        dossier, _lookup, int(cfg.get("excerpt_max_words", 40))
    )
    draft = dossier_mod.render_markdown(dossier, {}, checks, 0)
    try:
        review = await get_router().second_opinion(draft)
        flags = [f.model_dump() for f in review.flags]
        overall = review.overall
    except ProviderError as e:
        _log("warn", f"second opinion unavailable on every provider: {e}")
        flags, overall = [], f"unavailable: {e}"
    failed = [c.model_dump() for c in checks if not c.ok]
    result = {
        "flags": flags,
        "overall": overall,
        "excerpt_precheck": {"passed": len(checks) - len(failed), "failed": failed},
        "fetch_errors": fetch_errors,
        "at": datetime.now(UTC).isoformat(),
    }
    session = session_or_none()
    if session is not None:
        session.second_opinions.append(result)
    _log(
        "info",
        f"second opinion: {len(flags)} flags; excerpt pre-check "
        f"{len(checks) - len(failed)} passed, {len(failed)} failed",
    )
    return result


@research_tool
async def save_dossier(
    dossier: dossier_mod.DossierIn,
    story_id: Annotated[int | None, Field(description="Defaults to this run's story")] = None,
) -> dict[str, Any]:
    """Save a new dossier version and export research/<slug>/dossier.md + sources.json. Every
    Timeline item, Key Number and the Twist is checked: its excerpt must appear in the cited
    source, or the row is moved to Open Questions / Unverified."""
    _count("save_dossier")
    session = session_or_none()
    if session is not None:
        if story_id is not None and story_id != session.story_id:
            raise ToolError(f"this run researches story {session.story_id}, not {story_id}")
        story_id = session.story_id
        if not session.second_opinions:
            raise ToolError("run second_opinion on the draft first, then save")
    if story_id is None:
        raise ToolError("story_id is required")
    last = session.second_opinions[-1] if session and session.second_opinions else None
    review = {
        "flags": last["flags"] if last else [],
        "overall": last["overall"] if last else None,
        "resolutions": [r.model_dump() for r in dossier.second_opinion_resolutions],
    }
    try:
        result = await dossier_mod.save_dossier(
            get_engine(),
            story_id,
            dossier,
            _lookup,
            second_opinion=review,
            run_id=session.run_id if session else None,
        )
    except LookupError as e:
        raise ToolError(str(e)) from e
    if session is not None:
        session.saved.append(result | {"resolutions": review["resolutions"]})
    check = result["excerpt_check"]
    _log(
        "info",
        f"Saved dossier v{result['version']}: excerpt check {check['passed']} passed, "
        f"{check['failed']} moved to Open Questions → {result['export']}",
    )
    bus.publish("dossier.saved", story_id=story_id, version=result["version"])
    bus.publish("story.changed", story_id=story_id)
    return result
