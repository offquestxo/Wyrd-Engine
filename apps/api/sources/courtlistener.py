"""CourtListener: lawsuits and bankruptcy dockets (RECAP) and court opinions.

Docs: https://wiki.free.law/c/courtlistener/help/api/rest/v4/overview (REST v4)
Anonymous search works; COURTLISTENER_TOKEN raises limits (authenticated: 5/min, 50/h, 125/day).

CLI:
  python -m apps.api.sources.courtlistener search "Circuit City Stores" --type r
"""

from __future__ import annotations

import argparse
from typing import Any

from pydantic import BaseModel

from apps.api.settings import get_settings
from apps.api.sources._http import get_json, run_cli, truncate

SOURCE = "courtlistener"
BASE = "https://www.courtlistener.com"
TYPES = {"r": "RECAP dockets (federal cases incl. bankruptcy)", "o": "opinions", "d": "dockets"}


class CourtCase(BaseModel):
    case_name: str
    court: str | None
    docket_number: str | None
    date_filed: str | None
    url: str
    snippet: str = ""


def _headers() -> dict[str, str]:
    token = get_settings().courtlistener_token
    return {"Authorization": f"Token {token}"} if token else {}


def _snippet(row: dict[str, Any]) -> str:
    if row.get("snippet"):
        return truncate(row["snippet"])
    for nested in ("opinions", "recap_documents"):
        for child in row.get(nested) or []:
            if child.get("snippet"):
                return truncate(child["snippet"])
    return ""


async def search(
    query: str,
    type_: str = "r",
    limit: int = 20,
    filed_after: str | None = None,
    filed_before: str | None = None,
) -> list[CourtCase]:
    params: dict[str, str] = {"q": query, "type": type_}
    if filed_after:
        params["filed_after"] = filed_after
    if filed_before:
        params["filed_before"] = filed_before
    data = await get_json(SOURCE, f"{BASE}/api/rest/v4/search/", params=params, headers=_headers())
    out: list[CourtCase] = []
    for row in (data.get("results") or [])[:limit]:
        path = row.get("docket_absolute_url") or row.get("absolute_url") or ""
        out.append(
            CourtCase(
                case_name=row.get("caseName") or row.get("case_name") or "",
                court=row.get("court") or row.get("court_id"),
                docket_number=row.get("docketNumber"),
                date_filed=row.get("dateFiled"),
                url=f"{BASE}{path}" if path.startswith("/") else path,
                snippet=_snippet(row),
            )
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(prog="courtlistener")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--type", dest="type_", choices=sorted(TYPES), default="r")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--filed-after")
    p.add_argument("--filed-before")
    run_cli(
        SOURCE,
        parser,
        {
            "search": lambda a: search(a.query, a.type_, a.limit, a.filed_after, a.filed_before),
        },
    )


if __name__ == "__main__":
    main()
