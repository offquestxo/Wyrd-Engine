"""@scout with faked sources and providers (no network): dedup, scoring, saving, YouTube budget."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, select

from apps.api.agents import dedup, scout
from apps.api.agents.scout import Candidate, Lead, cap_round_robin, exact_dedupe, gap_score
from apps.api.db.migrate import migrate_path
from apps.api.db.models import Embedding, ProviderUsage, Story, StorySource
from apps.api.db.session import make_engine
from apps.api.providers.base import EmbedResult, ProviderError
from apps.api.providers.schemas import ItemScore, ItemToScore
from apps.api.sources import wikipedia, youtube
from apps.api.sources.models import SourceItem

NOW = datetime.now(UTC)


def item(
    title: str, url: str, source: str = "Google News", days_ago: int = 1, snippet: str = ""
) -> SourceItem:
    return SourceItem(
        title=title,
        url=url,
        source=source,
        published_at=(NOW - timedelta(days=days_ago)).isoformat(),
        snippet=snippet,
    )


# ---------------------------------------------------------------------------- helpers
def test_normalize_url_strips_tracking_and_www() -> None:
    assert dedup.normalize_url(
        "https://www.Example.com/a/?utm_source=x&id=3#top"
    ) == dedup.normalize_url("https://example.com/a?id=3")


def test_title_key_drops_publisher_suffix() -> None:
    assert dedup.title_key("Acme files for bankruptcy - Reuters") == "acme files for bankruptcy"


def test_semantic_dedupe_against_items_and_saved_stories() -> None:
    vectors = [[1.0, 0.0], [0.99, 0.05], [0.0, 1.0], [0.7, 0.7]]
    existing = [(42, [0.0, 1.0])]
    kept, dupes = dedup.semantic_dedupe(vectors, existing, threshold=0.95)
    assert kept == [0, 3]
    assert {(d.index, d.of_item, d.of_story) for d in dupes} == {(1, 0, None), (2, None, 42)}


def test_pack_roundtrip() -> None:
    assert dedup.unpack(dedup.pack([0.5, -1.25])) == [0.5, -1.25]


def test_exact_dedupe_prefers_primary_and_collects_extra_sources() -> None:
    leads = [
        Lead(
            item("Acme charged with fraud - CNN", "https://cnn.com/a?utm_source=x"), "Google News"
        ),
        Lead(
            item("Acme charged with fraud", "https://sec.gov/r1", "SEC press releases"),
            "SEC",
            primary=True,
        ),
        Lead(item("Other story", "https://cnn.com/a"), "HN"),  # same URL as first after normalizing
        Lead(item("Old saved headline", "https://x.com/1"), "HN"),
    ]
    kept, dropped = exact_dedupe(
        leads, known_urls={"https://y.com/z"}, known_story_titles={"Old saved headline"}
    )
    assert [k.item.url for k in kept] == ["https://sec.gov/r1"]
    assert [s.url for s in kept[0].extra_sources] == ["https://cnn.com/a?utm_source=x"]
    assert dropped == 3


def test_cap_round_robin_spreads_across_feeds() -> None:
    leads = [Lead(item(f"a{i}", f"https://a/{i}", days_ago=i), "A") for i in range(5)]
    leads += [Lead(item(f"b{i}", f"https://b/{i}", days_ago=i), "B") for i in range(5)]
    picked = cap_round_robin(leads, 4)
    assert [lead.item.title for lead in picked] == ["a0", "b0", "a1", "b1"]


def score(i: str, total: int = 8, series: str = "Fraud Files") -> ItemScore:
    return ItemScore(
        id=i,
        drama=total,
        twist=total,
        relatability=total,
        visual_potential=total,
        hook_number=total,
        freshness=total,
        hook="A hook.",
        series=series,  # type: ignore[arg-type]
        format="Long",
        company="Acme",
    )


def test_gap_score_rewards_low_coverage() -> None:
    cfg = {
        "weights": {"story_quality": 0.5, "article_richness": 0.2, "low_coverage": 0.3},
        "coverage_saturation": 5,
        "richness_refs_full": 100,
        "richness_length_full": 80000,
        "richness_pageviews_full": 100000,
    }
    base = dict(
        title="X", url="u", length=80000, references=100, pageviews=100000, score=score("1")
    )
    uncovered = gap_score(Candidate(**base, popular_videos=0), cfg)  # type: ignore[arg-type]
    covered = gap_score(Candidate(**base, popular_videos=9), cfg)  # type: ignore[arg-type]
    assert uncovered == 9.0 and covered == 6.0
    assert gap_score(Candidate(title="X", url="u", score=score("1")), cfg) is None  # unchecked


# ---------------------------------------------------------------------------- full runs
class Ctx:
    def __init__(self, params: dict[str, Any]) -> None:
        self.params, self.run_id, self.logs, self.steps = params, 7, [], []

    def log(self, level: str, message: str, data: Any = None) -> None:
        self.logs.append((level, message))

    def step(self, name: str, progress: float | None = None) -> None:
        self.steps.append(name)


class FakeParallel:
    """Stands in for providers/parallel.py: scores everything through FakeRouter in one batch."""

    def __init__(self, router: FakeRouter) -> None:
        self.router = router

    async def score(
        self,
        items: list[ItemToScore],
        series_hint: str = "",
        on_batch: Any = None,
        on_lane_drop: Any = None,
    ) -> Any:
        from apps.api.providers.parallel import BatchResult, ParallelOutcome

        try:
            scores = await self.router.score_items(items, series_hint)
        except ProviderError as e:
            if on_lane_drop:
                on_lane_drop("fake/model", str(e))
            return ParallelOutcome(
                scores={}, scored_by={}, unscored=list(items), lane_errors=[str(e)]
            )
        if on_batch:
            on_batch(BatchResult("fake", "model", list(items), scores, 0.1))
        return ParallelOutcome(
            scores={s.id: s for s in scores},
            scored_by={s.id: "fake/model" for s in scores},
            unscored=[],
        )


class FakeRouter:
    def __init__(self, fail_scoring: bool = False) -> None:
        self.scored: list[str] = []
        self.fail_scoring = fail_scoring

    async def embed(self, texts: list[str]) -> EmbedResult:
        # "Acme" headlines embed identically, everything else is orthogonal-ish.
        def vec(t: str) -> list[float]:
            return [1.0, 0.0, 0.0] if "acme" in t.lower() else [0.0, (len(t) % 7) + 1.0, 1.0]

        return EmbedResult(vectors=[vec(t) for t in texts], model="fake-embed")

    async def score_items(self, items: list[ItemToScore], series_hint: str = "") -> list[ItemScore]:
        if self.fail_scoring:
            raise ProviderError("router", "all providers failed")
        self.scored += [i.title for i in items]
        return [score(i.id, total=9 if "acme" in i.title.lower() else 6) for i in items]


@pytest.fixture
def engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env: pytest.MonkeyPatch) -> Any:
    db = tmp_path / "scout.db"
    migrate_path(db)
    eng = make_engine(db)
    monkeypatch.setattr(scout, "get_engine", lambda: eng)
    env.setenv("SEC_USER_AGENT", "test contact@example.com")
    env.setenv("YOUTUBE_API_KEY", "yt-test")
    return eng


def fake_news(monkeypatch: pytest.MonkeyPatch, router: FakeRouter) -> None:
    async def google_news(q: str, limit: int, when: str | None = None) -> list[SourceItem]:
        return [
            item(f"Acme Corp accused of accounting fraud - {q}", f"https://news/{q}/acme"),
            item(f"Startup {q} shuts down after funding dries up", f"https://news/{q}/shut"),
            item("Ancient story", f"https://news/{q}/old", days_ago=400),
        ]

    async def feed(url: str, label: str | None = None, limit: int = 50) -> list[SourceItem]:
        return [item("SEC charges Acme executives with fraud", f"{url}#1", label or url)]

    async def failing(*_a: Any, **_k: Any) -> list[SourceItem]:
        from apps.api.sources._http import SourceError

        raise SourceError("gdelt", "HTTP 429")

    async def empty(*_a: Any, **_k: Any) -> list[SourceItem]:
        return []

    monkeypatch.setattr(scout.news_rss, "google_news", google_news)
    monkeypatch.setattr(scout.news_rss, "feed", feed)
    monkeypatch.setattr(scout.gdelt, "search", failing)
    for mod, fn in (
        (scout.edgar, "full_text_search"),
        (scout.hackernews, "search"),
        (scout.reddit_rss, "subreddit"),
        (scout.reddit_rss, "search"),
    ):
        monkeypatch.setattr(mod, fn, empty)
    monkeypatch.setattr(scout, "get_router", lambda: router)
    monkeypatch.setattr(scout, "parallel_scorer", lambda: FakeParallel(router))


async def test_news_run_saves_scored_deduplicated_stories_with_sources(
    engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    router = FakeRouter()
    fake_news(monkeypatch, router)
    ctx = Ctx({"mode": "news", "limit": 10})
    result = await scout.run(ctx)  # type: ignore[arg-type]

    with Session(engine) as s:
        stories = s.exec(select(Story)).all()
        sources = s.exec(select(StorySource)).all()
        vectors = s.exec(select(Embedding)).all()
    titles = [st.title for st in stories]
    # All "Acme" items collapse into one story (exact title + embedding dedup); stale item dropped.
    assert sum("acme" in t.lower() for t in titles) == 1
    assert not any("Ancient" in t for t in titles)
    acme = next(st for st in stories if "acme" in st.title.lower())
    acme_sources = [src for src in sources if src.story_id == acme.id]
    assert acme_sources[0].source_type == "primary"  # the SEC release wins over re-posts
    assert len(acme_sources) > 1  # duplicates were kept as extra sources
    assert acme.status == "Inbox" and acme.scores and acme.scores["total"] == 9.0
    assert acme.hook == "A hook." and acme.series == "Fraud Files"
    assert acme.scores["scored_by"] == "fake/model"
    assert any("Scored" in msg and "fake/model" in msg for _, msg in ctx.logs)
    assert len(vectors) == len(stories)  # embeddings stored for future dedup
    assert result["counts"]["news_saved"] == len(stories)
    assert any("GDELT" in e for e in result["source_errors"])  # failing source reported, not fatal
    assert any(level == "warn" and "GDELT" in msg for level, msg in ctx.logs)

    # A second run finds nothing new: everything is a duplicate of saved stories.
    second = await scout.run(Ctx({"mode": "news", "limit": 10}))  # type: ignore[arg-type]
    assert second["stories"] == []


async def test_news_run_fails_clearly_when_no_scoring_works(
    engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_news(monkeypatch, FakeRouter(fail_scoring=True))
    with pytest.raises(RuntimeError, match="Every scoring call failed"):
        await scout.run(Ctx({"mode": "news", "limit": 5}))  # type: ignore[arg-type]


def fake_wikipedia_and_youtube(monkeypatch: pytest.MonkeyPatch, calls: dict[str, int]) -> None:
    async def category(name: str, limit: int = 100, include_subcats: bool = False) -> list[Any]:
        return [
            wikipedia.CategoryMember(
                title=f"Company {name[-3:]} {i}", url=f"https://w/{name}/{i}", is_subcategory=False
            )
            for i in range(15)
        ]

    async def page_lengths(titles: list[str]) -> dict[str, int]:
        return {t: 50000 + i for i, t in enumerate(titles)}

    async def article(title: str, full: bool = False) -> wikipedia.Article:
        return wikipedia.Article(
            title=title,
            url="u",
            length_bytes=50000,
            references=60,
            summary=f"{title} was a retailer.",
        )

    async def pageviews(title: str, days: int = 60) -> wikipedia.Pageviews:
        return wikipedia.Pageviews(title=title, days=days, total=20000, daily_average=333.3)

    async def search(query: str, max_results: int = 10) -> youtube.SearchResults:
        calls["search"] += 1
        return youtube.SearchResults(query=query, video_ids=["v1", "v2"])

    async def videos(ids: list[str]) -> youtube.VideoStatsList:
        calls["videos"] += 1
        name = calls["search"]
        vids = [
            youtube.VideoStats(
                video_id="v1",
                channel_id="c",
                channel_title="C",
                title=f"Company story {name}",
                published_at="2024-01-01",
                duration_s=600,
                views=500_000,
                likes=1,
                comments=1,
                url="https://youtube.com/watch?v=v1",
            )
        ]
        return youtube.VideoStatsList(videos=vids, units_used=1)

    for mod, fn, impl in (
        (scout.wikipedia, "category", category),
        (scout.wikipedia, "page_lengths", page_lengths),
        (scout.wikipedia, "article", article),
        (scout.wikipedia, "pageviews", pageviews),
        (scout.youtube, "search", search),
        (scout.youtube, "videos", videos),
    ):
        monkeypatch.setattr(mod, fn, impl)


async def test_gap_finder_stays_within_todays_youtube_search_budget(
    engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"search": 0, "videos": 0}
    fake_wikipedia_and_youtube(monkeypatch, calls)
    monkeypatch.setattr(scout, "get_router", lambda: FakeRouter())
    monkeypatch.setattr(scout, "parallel_scorer", lambda: FakeParallel(FakeRouter()))
    # 85 of 100 search calls already used today; reserve is 10 → only 5 checks allowed.
    with Session(engine) as s:
        for _ in range(85):
            s.add(
                ProviderUsage(provider="youtube", model="search", task="search", ok=True, units=1)
            )
        s.commit()
    ctx = Ctx({"mode": "evergreen", "limit": 20})
    result = await scout.run(ctx)  # type: ignore[arg-type]

    assert calls["search"] == 5 and calls["videos"] == 5
    assert (
        calls["search"]
        <= scout.estimate({"mode": "evergreen", "limit": 20})["youtube_search_calls"]
    )
    assert result["counts"]["youtube_search_calls"] == 5
    assert any("budget allows 5" in n for n in result["notes"])
    with Session(engine) as s:
        stories = s.exec(select(Story)).all()
    assert len(stories) == 5  # only coverage-checked candidates get a gap score and are saved
    assert all(st.gap_score is not None and st.notes and "YouTube" in st.notes for st in stories)


def test_plan_estimate_reports_search_calls() -> None:
    assert scout.estimate({"mode": "news"}) == {"youtube_search_calls": 0, "youtube_units": 0}
    # Evergreen checks the top N (20) regardless of limit — the estimate must match the run.
    for params in (
        {"mode": "evergreen", "limit": 25},
        {"mode": "evergreen", "limit": 4},
        {"mode": "both", "limit": 10},
    ):
        est = scout.estimate(params)
        assert est["youtube_search_calls"] == 20 and est["youtube_units"] == 40


def test_source_excerpt_dropped_when_it_repeats_the_headline() -> None:
    src = scout.to_source(
        item(
            "Acme files for bankruptcy - Reuters",
            "https://r/1",
            snippet="Acme files for bankruptcy  Reuters",
        ),
        False,
    )
    assert src.excerpt is None
    kept = scout.to_source(
        item("Acme files", "https://r/2", snippet="The retailer owes $2B."), False
    )
    assert kept.excerpt == "The retailer owes $2B."


def test_prefilter_drops_obvious_noise() -> None:
    rules = {
        "min_title_words": 4,
        "drop_title_patterns": [r"^(how (do|can|should) i|should i)", r"\b(recipe|nfl)\b"],
        "require_business_keyword_for": ["Hacker News", "r/"],
        "business_keywords": ["company", "fraud", "sec"],
    }
    leads = [
        Lead(item("Acme charged with securities fraud by regulators", "https://1"), "Google News"),
        Lead(item("Short title", "https://2"), "Google News"),
        Lead(item("How do I price my consulting services", "https://3"), "r/Entrepreneur"),
        Lead(item("The best weeknight pasta recipe ever", "https://4"), "Google News"),
        Lead(item("Show HN: a terminal game I wrote", "https://5"), "Hacker News: shut down"),
        Lead(
            item("Second thoughts on my new keyboard layout", "https://6"), "r/business"
        ),  # 'sec' ≠ 'second'
        Lead(item("Startup company shuts down after fraud probe", "https://7"), "Hacker News: x"),
    ]
    kept, dropped = scout.prefilter(leads, rules)
    assert [k.item.url for k in kept] == ["https://1", "https://7"]
    assert dropped == {"too short": 1, "title pattern": 2, "no business keyword": 2}


def test_scout_keeps_only_figures_found_in_the_item_text() -> None:
    s = score("x")
    s.hook_figure, s.hook_caption = "$80M", "bribery scheme"
    assert scout.grounded_figure(s, "Ex-CEO indicted in $80M bribery scheme") == {
        "hook_figure": "$80M",
        "hook_caption": "bribery scheme",
    }
    s.hook_figure = "$800M"  # not in the headline: dropped, never invented
    assert scout.grounded_figure(s, "Ex-CEO indicted in $80M bribery scheme") == {
        "hook_figure": None,
        "hook_caption": None,
    }
