"""Library of Congress historical newspapers (Chronicling America, via the loc.gov API).

Since 2025 Chronicling America is served only through the loc.gov JSON API:
https://www.loc.gov/apis/additional-apis/chronicling-america-api/
Coverage is mostly 1770s–1963, so it suits founding-era stories, not 2000s collapses.

CLI:
  python -m apps.api.sources.loc_newspapers search "Wards Company" --start-year 1949 --end-year 1963
"""

from __future__ import annotations

import argparse

from pydantic import BaseModel

from apps.api.sources._http import get_json, run_cli, truncate

SOURCE = "loc_newspapers"
URL = "https://www.loc.gov/collections/chronicling-america/"


class NewspaperPage(BaseModel):
    title: str
    newspaper: str | None
    date: str | None
    location: str | None
    url: str
    snippet: str = ""


async def search(
    query: str, start_year: int | None = None, end_year: int | None = None, limit: int = 20
) -> list[NewspaperPage]:
    params: dict[str, str | int] = {"q": query, "fo": "json", "c": min(limit, 100), "at": "results"}
    if start_year or end_year:
        params["dates"] = f"{start_year or 1770}/{end_year or 1963}"
    data = await get_json(SOURCE, URL, params=params, timeout_s=45)
    out: list[NewspaperPage] = []
    for row in (data.get("results") or [])[:limit]:
        desc = row.get("description") or [""]
        locations = row.get("location_city") or row.get("location") or []
        partof = row.get("partof_title") or []
        out.append(
            NewspaperPage(
                title=truncate(row.get("title", ""), 200),
                newspaper=partof[0] if partof else None,
                date=row.get("date"),
                location=locations[0] if locations else None,
                url=row.get("url") or row.get("id") or "",
                # OCR text is noisy and long — keep only a short excerpt.
                snippet=truncate(desc[0] if isinstance(desc, list) and desc else str(desc), 240),
            )
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(prog="loc_newspapers")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--start-year", type=int)
    p.add_argument("--end-year", type=int)
    p.add_argument("--limit", type=int, default=20)
    run_cli(
        SOURCE, parser, {"search": lambda a: search(a.query, a.start_year, a.end_year, a.limit)}
    )


if __name__ == "__main__":
    main()
