"""Hacker News via the Algolia search API. Docs: https://hn.algolia.com/api

CLI:
  python -m apps.api.sources.hackernews search "Circuit City"
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from apps.api.sources._http import get_json, run_cli, truncate
from apps.api.sources.models import SourceItem

SOURCE = "hackernews"
API = "https://hn.algolia.com/api/v1"


async def search(
    query: str, limit: int = 20, recent: bool = False, min_points: int = 0
) -> list[SourceItem]:
    params: dict[str, str | int] = {"query": query, "tags": "story", "hitsPerPage": limit}
    if min_points:
        params["numericFilters"] = f"points>={min_points}"
    data = await get_json(
        SOURCE, f"{API}/{'search_by_date' if recent else 'search'}", params=params
    )
    items: list[SourceItem] = []
    for hit in data.get("hits", []):
        discussion = f"https://news.ycombinator.com/item?id={hit['objectID']}"
        created = hit.get("created_at_i")
        items.append(
            SourceItem(
                title=truncate(hit.get("title") or "", 300),
                url=hit.get("url") or discussion,
                source="Hacker News",
                published_at=datetime.fromtimestamp(created, UTC).isoformat() if created else None,
                snippet=f"{hit.get('points') or 0} points · "
                f"{hit.get('num_comments') or 0} comments · {discussion}",
            )
        )
    return items


def main() -> None:
    parser = argparse.ArgumentParser(prog="hackernews")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--recent", action="store_true")
    p.add_argument("--min-points", type=int, default=0)
    run_cli(SOURCE, parser, {"search": lambda a: search(a.query, a.limit, a.recent, a.min_points)})


if __name__ == "__main__":
    main()
