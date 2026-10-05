"""Reddit story leads via public RSS (not the authenticated API).

Reddit rate-limits unauthenticated RSS aggressively; requests are paced (sources.yaml).

CLI:
  python -m apps.api.sources.reddit_rss subreddit business --sort top
  python -m apps.api.sources.reddit_rss search "Circuit City" --subreddit business
"""

from __future__ import annotations

import argparse

from apps.api.sources._feeds import fetch_feed
from apps.api.sources._http import run_cli
from apps.api.sources.models import SourceItem

SOURCE = "reddit_rss"
BASE = "https://www.reddit.com"


async def subreddit(name: str, sort: str = "hot", limit: int = 25) -> list[SourceItem]:
    path = f"/r/{name}/.rss" if sort == "hot" else f"/r/{name}/{sort}/.rss"
    params = {"t": "month"} if sort == "top" else None
    return await fetch_feed(SOURCE, f"{BASE}{path}", f"r/{name}", limit, params=params)


async def search(query: str, sub: str | None = None, limit: int = 25) -> list[SourceItem]:
    url = f"{BASE}/r/{sub}/search.rss" if sub else f"{BASE}/search.rss"
    params = {"q": query, "sort": "relevance"}
    if sub:
        params["restrict_sr"] = "1"
    return await fetch_feed(SOURCE, url, f"r/{sub}" if sub else "Reddit", limit, params=params)


def main() -> None:
    parser = argparse.ArgumentParser(prog="reddit_rss")
    cmd = parser.add_subparsers(dest="command", required=True)
    p = cmd.add_parser("subreddit")
    p.add_argument("name")
    p.add_argument("--sort", choices=["hot", "new", "top"], default="hot")
    p.add_argument("--limit", type=int, default=25)
    p = cmd.add_parser("search")
    p.add_argument("query")
    p.add_argument("--subreddit")
    p.add_argument("--limit", type=int, default=25)
    run_cli(
        SOURCE,
        parser,
        {
            "subreddit": lambda a: subreddit(a.name, a.sort, a.limit),
            "search": lambda a: search(a.query, a.subreddit, a.limit),
        },
    )


if __name__ == "__main__":
    main()
