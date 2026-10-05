"""Internet Archive: old annual reports, magazines, ads, films.

Docs: https://archive.org/advancedsearch.php (Advanced Search API)

CLI:
  python -m apps.api.sources.internet_archive search "Circuit City" --mediatype texts
"""

from __future__ import annotations

import argparse
from typing import Any

from pydantic import BaseModel

from apps.api.sources._http import get_json, run_cli, truncate

SOURCE = "internet_archive"
URL = "https://archive.org/advancedsearch.php"
MEDIATYPES = ["texts", "movies", "audio", "image", "web", "collection"]


class ArchiveItem(BaseModel):
    identifier: str
    title: str
    mediatype: str | None
    date: str | None
    url: str
    description: str = ""


def _first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else value


async def search(query: str, mediatype: str | None = None, limit: int = 20) -> list[ArchiveItem]:
    q = f"({query})" + (f" AND mediatype:({mediatype})" if mediatype else "")
    params: list[tuple[str, str | int]] = [
        ("q", q),
        ("rows", limit),
        ("page", 1),
        ("output", "json"),
    ]
    params += [("fl[]", f) for f in ("identifier", "title", "mediatype", "date", "description")]
    data = await get_json(SOURCE, URL, params=params, timeout_s=45)
    return [
        ArchiveItem(
            identifier=d["identifier"],
            title=str(_first(d.get("title")) or d["identifier"]),
            mediatype=d.get("mediatype"),
            date=d.get("date"),
            url=f"https://archive.org/details/{d['identifier']}",
            description=truncate(str(_first(d.get("description")) or "")),
        )
        for d in (data.get("response") or {}).get("docs", [])
    ]


def main() -> None:
    parser = argparse.ArgumentParser(prog="internet_archive")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--mediatype", choices=MEDIATYPES)
    p.add_argument("--limit", type=int, default=20)
    run_cli(SOURCE, parser, {"search": lambda a: search(a.query, a.mediatype, a.limit)})


if __name__ == "__main__":
    main()
