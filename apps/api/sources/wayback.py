"""Wayback Machine: historical snapshots of company websites.

Docs: https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server

CLI:
  python -m apps.api.sources.wayback snapshots circuitcity.com --from 2000 --to 2009
  python -m apps.api.sources.wayback closest circuitcity.com 20081110
"""

from __future__ import annotations

import argparse

from pydantic import BaseModel

from apps.api.sources._http import SourceError, get_json, run_cli

SOURCE = "wayback"
CDX = "https://web.archive.org/cdx/search/cdx"


class Snapshot(BaseModel):
    timestamp: str
    original_url: str
    status: str
    url: str


def snapshot_url(timestamp: str, original: str) -> str:
    return f"https://web.archive.org/web/{timestamp}/{original}"


async def snapshots(
    site: str, start: str | None = None, end: str | None = None, limit: int = 50, per: str = "month"
) -> list[Snapshot]:
    """One snapshot per month (or 'year'/'day') in range, HTML 200s only."""
    collapse = {"year": 4, "month": 6, "day": 8}[per]
    params: dict[str, str | int] = {
        "url": site,
        "output": "json",
        "limit": limit,
        "fl": "timestamp,original,statuscode",
        "filter": ["statuscode:200", "mimetype:text/html"],  # type: ignore[dict-item]
        "collapse": f"timestamp:{collapse}",
    }
    if start:
        params["from"] = start
    if end:
        params["to"] = end
    rows = await get_json(SOURCE, CDX, params=params, timeout_s=45)
    if not rows:
        return []
    return [
        Snapshot(timestamp=ts, original_url=orig, status=status, url=snapshot_url(ts, orig))
        for ts, orig, status in rows[1:]
    ]


async def closest(site: str, timestamp: str) -> Snapshot:
    # CDX closest-sort (the separate /wayback/available endpoint rate-limits aggressively).
    rows = await get_json(
        SOURCE,
        CDX,
        params={
            "url": site,
            "output": "json",
            "limit": 1,
            "closest": timestamp,
            "sort": "closest",
            "fl": "timestamp,original,statuscode",
            "filter": "statuscode:200",
        },
        timeout_s=45,
    )
    if not rows or len(rows) < 2:
        raise SourceError(SOURCE, f"no snapshot of {site} near {timestamp}")
    ts, orig, status = rows[1]
    return Snapshot(timestamp=ts, original_url=orig, status=status, url=snapshot_url(ts, orig))


def main() -> None:
    parser = argparse.ArgumentParser(prog="wayback")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("snapshots")
    p.add_argument("site")
    p.add_argument("--from", dest="start")
    p.add_argument("--to", dest="end")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--per", choices=["year", "month", "day"], default="month")
    p = sub.add_parser("closest")
    p.add_argument("site")
    p.add_argument("timestamp")
    run_cli(
        SOURCE,
        parser,
        {
            "snapshots": lambda a: snapshots(a.site, a.start, a.end, a.limit, a.per),
            "closest": lambda a: closest(a.site, a.timestamp),
        },
    )


if __name__ == "__main__":
    main()
