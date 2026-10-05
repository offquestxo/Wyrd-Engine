"""Shared source result models."""

from __future__ import annotations

from pydantic import BaseModel


class SourceItem(BaseModel):
    """Normalized lead/item shape used by @scout (SPEC §6.1 step 2)."""

    title: str
    url: str
    source: str
    published_at: str | None = None
    snippet: str = ""
