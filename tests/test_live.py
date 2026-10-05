"""Live checks against real APIs, using Circuit City as the known company (SPEC §11 Phase 0).

Run with `make test-live`. Keyed sources/providers skip when their key is missing.
"""

from __future__ import annotations

import pytest

from apps.api.providers.router import get_router
from apps.api.settings import get_settings
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

pytestmark = pytest.mark.live


def need(env_value: str, name: str) -> None:
    if not env_value or "your@email.com" in env_value:
        pytest.skip(f"{name} not set in .env")


async def test_edgar() -> None:
    need(get_settings().sec_user_agent, "SEC_USER_AGENT")
    companies = await edgar.search_companies("Circuit City")
    assert companies[0].cik == "0000104599"
    tenks = await edgar.filings("0000104599", ["10-K"], limit=3)
    assert tenks and tenks[0].url.startswith("https://www.sec.gov/Archives/")
    assert await edgar.full_text_search('"Circuit City" liquidation', forms="8-K", limit=3)
    best_buy = await edgar.company_facts("764478", ["Revenues"])
    assert best_buy.facts


async def test_wikipedia() -> None:
    article = await wikipedia.article("Circuit City")
    assert article.references > 20 and article.length_bytes > 10_000
    assert (await wikipedia.pageviews("Circuit City", 60)).total > 0
    assert await wikipedia.category("Category:Defunct retail companies of the United States", 5)


async def test_wayback() -> None:
    snaps = await wayback.snapshots("circuitcity.com", "2007", "2009", limit=3, per="year")
    assert snaps and snaps[0].url.startswith("https://web.archive.org/web/")


async def test_courtlistener() -> None:
    assert await courtlistener.search("Circuit City Stores", limit=3)


async def test_loc_newspapers() -> None:
    assert await loc_newspapers.search("Circuit City", limit=3)


async def test_internet_archive() -> None:
    assert await internet_archive.search('"Circuit City"', limit=3)


async def test_news_rss() -> None:
    assert await news_rss.google_news("Circuit City", limit=3)


async def test_hackernews() -> None:
    assert await hackernews.search("Circuit City", limit=3)


async def test_reddit_rss() -> None:
    assert await reddit_rss.search("Circuit City", "business", limit=3)


async def test_gdelt() -> None:
    assert await gdelt.search("Circuit City", limit=3) is not None


async def test_yahoo() -> None:
    # Circuit City (CCTYQ) is delisted and absent from Yahoo; Best Buy proves the module works.
    assert (await yahoo.history("BBY", "1y", "1mo")).points


async def test_youtube() -> None:
    need(get_settings().youtube_api_key, "YOUTUBE_API_KEY")
    info = await youtube.channel("@companyman")
    assert info.uploads_playlist_id.startswith("UU")


@pytest.mark.parametrize("provider", ["groq", "gemini", "nvidia", "mistral", "openrouter"])
async def test_provider_connection(provider: str) -> None:
    router = get_router()
    if not router.providers[provider].configured:
        pytest.skip(f"{provider} key not set in .env")
    result = await router.test_connection(provider)
    assert result.ok, result.detail


async def test_router_embed_live() -> None:
    router = get_router()
    if not any(router.providers[p].configured for p in ("nvidia", "gemini")):
        pytest.skip("no embedding provider key set")
    result = await router.embed(["Circuit City liquidation", "Best Buy earnings"])
    assert len(result.vectors) == 2 and len(result.vectors[0]) > 100


async def test_router_score_items_live() -> None:
    """Real end-to-end scoring through whatever providers currently work (with fallback)."""
    from apps.api.providers.schemas import ItemToScore

    router = get_router()
    if not any(router.providers[p].configured for p in ("groq", "gemini", "nvidia")):
        pytest.skip("no LLM provider key set")
    scores = await router.score_items(
        [
            ItemToScore(
                id="cc",
                title="Circuit City to liquidate all U.S. stores after failing to find a buyer",
                snippet="The electronics retailer will close its remaining 567 stores.",
                source="test",
            )
        ]
    )
    assert scores and scores[0].id == "cc" and 1 <= scores[0].drama <= 10
    print("router events:", [(e.kind, e.provider) for e in router.events])
