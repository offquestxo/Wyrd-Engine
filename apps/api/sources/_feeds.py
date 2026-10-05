"""RSS/Atom parsing shared by news_rss and reddit_rss."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from time import struct_time
from typing import Any

import feedparser

from apps.api.sources._http import get_text, truncate
from apps.api.sources.models import SourceItem


def _iso(parsed: struct_time | None) -> str | None:
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=UTC).isoformat()


def _strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", text or "")).replace("\xa0", " ")


async def fetch_feed(
    source: str, url: str, label: str, limit: int = 50, params: dict[str, Any] | None = None
) -> list[SourceItem]:
    body = await get_text(source, url, params=params)
    parsed = feedparser.parse(body)
    items: list[SourceItem] = []
    for entry in parsed.entries[:limit]:
        entry_source = entry.get("source")
        publisher = entry_source.get("title") if isinstance(entry_source, dict) else None
        items.append(
            SourceItem(
                title=truncate(html.unescape(entry.get("title", "")), 300),
                url=entry.get("link", ""),
                source=publisher or label,
                published_at=_iso(entry.get("published_parsed") or entry.get("updated_parsed")),
                snippet=truncate(_strip_html(entry.get("summary", ""))),
            )
        )
    return items
