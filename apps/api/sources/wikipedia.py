"""Wikipedia / Wikimedia: search, article stats, category crawl, pageviews.

Docs: https://www.mediawiki.org/wiki/API:Main_page and
      https://doc.wikimedia.org/generated-data-platform/aqs/analytics-api/
Wikimedia asks for a descriptive User-Agent with contact info (we reuse SEC_USER_AGENT).

CLI:
  python -m apps.api.sources.wikipedia search "Circuit City"
  python -m apps.api.sources.wikipedia article "Circuit City"
  python -m apps.api.sources.wikipedia category "Category:Corporate scandals"
  python -m apps.api.sources.wikipedia pageviews "Circuit City" --days 60
"""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from pydantic import BaseModel

from apps.api.sources._http import SourceError, get_json, run_cli, truncate

SOURCE = "wikipedia"
API = "https://en.wikipedia.org/w/api.php"
PAGEVIEWS = (
    "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user"
)


class SearchHit(BaseModel):
    title: str
    url: str
    snippet: str
    size_bytes: int


class Article(BaseModel):
    title: str
    url: str
    length_bytes: int
    references: int
    summary: str
    text: str | None = None  # only with --full (for extraction; never stored whole)


class CategoryMember(BaseModel):
    title: str
    url: str
    is_subcategory: bool


class Pageviews(BaseModel):
    title: str
    days: int
    total: int
    daily_average: float


def page_url(title: str) -> str:
    return f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"


async def search(query: str, limit: int = 10) -> list[SearchHit]:
    data = await get_json(
        SOURCE,
        API,
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": limit,
            "format": "json",
            "formatversion": 2,
        },
    )
    return [
        SearchHit(
            title=h["title"],
            url=page_url(h["title"]),
            snippet=truncate(re.sub(r"<[^>]+>", "", h.get("snippet", ""))),
            size_bytes=h.get("size", 0),
        )
        for h in data.get("query", {}).get("search", [])
    ]


async def article(title: str, full: bool = False) -> Article:
    data = await get_json(
        SOURCE,
        API,
        params={
            "action": "query",
            "titles": title,
            "redirects": 1,
            "format": "json",
            "formatversion": 2,
            "prop": "extracts|info|revisions",
            "explaintext": 1,
            "exintro": 0 if full else 1,
            "rvprop": "content",
            "rvslots": "main",
        },
    )
    pages = data.get("query", {}).get("pages", [])
    if not pages or pages[0].get("missing"):
        raise SourceError(SOURCE, f"no article titled {title!r}")
    page = pages[0]
    wikitext = page.get("revisions", [{}])[0].get("slots", {}).get("main", {}).get("content", "")
    references = len(re.findall(r"<ref[\s>]", wikitext))
    extract = page.get("extract", "")
    return Article(
        title=page["title"],
        url=page_url(page["title"]),
        length_bytes=page.get("length", 0),
        references=references,
        summary=truncate(extract.split("\n")[0] if full else extract, 600),
        text=extract if full else None,
    )


async def category(
    name: str, limit: int = 100, include_subcats: bool = False
) -> list[CategoryMember]:
    if not name.startswith("Category:"):
        name = f"Category:{name}"
    members: list[CategoryMember] = []
    cont: dict[str, str] = {}
    while len(members) < limit:
        data = await get_json(
            SOURCE,
            API,
            params={
                "action": "query",
                "list": "categorymembers",
                "cmtitle": name,
                "cmtype": "page|subcat" if include_subcats else "page",
                "cmlimit": min(500, limit - len(members)),
                "format": "json",
                "formatversion": 2,
                **cont,
            },
        )
        for m in data.get("query", {}).get("categorymembers", []):
            if m["title"].startswith("List of"):
                continue
            members.append(
                CategoryMember(
                    title=m["title"], url=page_url(m["title"]), is_subcategory=m.get("ns") == 14
                )
            )
        if "continue" not in data:
            break
        cont = {"cmcontinue": data["continue"]["cmcontinue"]}
    return members[:limit]


async def pageviews(title: str, days: int = 60) -> Pageviews:
    end = datetime.now(UTC).date() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    url = f"{PAGEVIEWS}/{quote(title.replace(' ', '_'), safe='')}/daily/{start:%Y%m%d}/{end:%Y%m%d}"
    data = await get_json(SOURCE, url)
    total = sum(int(item.get("views", 0)) for item in data.get("items", []))
    return Pageviews(title=title, days=days, total=total, daily_average=round(total / days, 1))


def main() -> None:
    parser = argparse.ArgumentParser(prog="wikipedia")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)
    p = sub.add_parser("article")
    p.add_argument("title")
    p.add_argument("--full", action="store_true")
    p = sub.add_parser("category")
    p.add_argument("name")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--subcats", action="store_true")
    p = sub.add_parser("pageviews")
    p.add_argument("title")
    p.add_argument("--days", type=int, default=60)
    run_cli(
        SOURCE,
        parser,
        {
            "search": lambda a: search(a.query, a.limit),
            "article": lambda a: article(a.title, a.full),
            "category": lambda a: category(a.name, a.limit, a.subcats),
            "pageviews": lambda a: pageviews(a.title, a.days),
        },
    )


if __name__ == "__main__":
    main()
