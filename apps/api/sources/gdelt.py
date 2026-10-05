"""GDELT DOC 2.0 API: global news search by keyword (rolling ~3 months by default).

Docs: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
GDELT asks for at most one request every 5 seconds (paced in sources.yaml).

CLI:
  python -m apps.api.sources.gdelt search "Circuit City" --timespan 3m
"""

from __future__ import annotations

import argparse
from datetime import datetime

from apps.api.sources._http import SourceError, request, run_cli, truncate
from apps.api.sources.models import SourceItem

SOURCE = "gdelt"
API = "https://api.gdeltproject.org/api/v2/doc/doc"


def _iso(seendate: str | None) -> str | None:
    if not seendate:
        return None
    try:
        return datetime.strptime(seendate, "%Y%m%dT%H%M%SZ").isoformat() + "Z"
    except ValueError:
        return seendate


async def search(
    query: str, timespan: str = "3m", limit: int = 50, english_only: bool = True
) -> list[SourceItem]:
    # Multi-word plain queries are searched as an exact phrase.
    if " " in query and '"' not in query and " OR " not in query:
        query = f'"{query}"'
    q = f"{query} sourcelang:english" if english_only else query
    resp = await request(
        SOURCE,
        API,
        params={
            "query": q,
            "mode": "artlist",
            "format": "json",
            "maxrecords": min(limit, 250),
            "timespan": timespan,
            "sort": "datedesc",
        },
        timeout_s=45,
    )
    if "json" not in resp.headers.get("content-type", ""):
        # GDELT returns plain-text errors (e.g. rate limits, bad query) with HTTP 200.
        raise SourceError(SOURCE, truncate(resp.text, 200))
    data = resp.json() if resp.content.strip() else {}
    return [
        SourceItem(
            title=truncate(a.get("title", ""), 300),
            url=a.get("url", ""),
            source=a.get("domain") or "GDELT",
            published_at=_iso(a.get("seendate")),
            snippet=f"{a.get('sourcecountry', '')} · {a.get('language', '')}".strip(" ·"),
        )
        for a in data.get("articles", [])
    ]


def main() -> None:
    parser = argparse.ArgumentParser(prog="gdelt")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--timespan", default="3m", help="e.g. 24h, 7d, 3m")
    p.add_argument("--limit", type=int, default=50)
    run_cli(SOURCE, parser, {"search": lambda a: search(a.query, a.timespan, a.limit)})


if __name__ == "__main__":
    main()
