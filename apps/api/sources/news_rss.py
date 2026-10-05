"""Google News RSS saved queries and generic RSS feeds (e.g. SEC / DOJ press releases).

CLI:
  python -m apps.api.sources.news_rss search "Circuit City"
  python -m apps.api.sources.news_rss feed https://www.sec.gov/news/pressreleases.rss
"""

from __future__ import annotations

import argparse

from apps.api.sources._feeds import fetch_feed
from apps.api.sources._http import run_cli
from apps.api.sources.models import SourceItem

SOURCE = "news_rss"
GOOGLE_NEWS = "https://news.google.com/rss/search"


async def google_news(query: str, limit: int = 30, when: str | None = None) -> list[SourceItem]:
    """`when` narrows recency using Google News syntax, e.g. '7d' or '1y'."""
    q = f"{query} when:{when}" if when else query
    return await fetch_feed(
        SOURCE,
        GOOGLE_NEWS,
        "Google News",
        limit,
        params={"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"},
    )


async def feed(url: str, label: str | None = None, limit: int = 50) -> list[SourceItem]:
    return await fetch_feed(SOURCE, url, label or url, limit)


def main() -> None:
    parser = argparse.ArgumentParser(prog="news_rss")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--when", help="recency window, e.g. 7d")
    p = sub.add_parser("feed")
    p.add_argument("url")
    p.add_argument("--limit", type=int, default=50)
    run_cli(
        SOURCE,
        parser,
        {
            "search": lambda a: google_news(a.query, a.limit, a.when),
            "feed": lambda a: feed(a.url, limit=a.limit),
        },
    )


if __name__ == "__main__":
    main()
