"""Cross-chat memory (SPEC §5.4): FTS5 + embeddings over messages, stories and dossiers.

`search()` runs a keyword search (FTS5, bm25) and, when an embedding provider answers, a
vector search over stored vectors of the *same model* as the query vector. The two rankings
are merged with reciprocal rank fusion, so either one alone still returns useful results.

Vectors: `embeddings` rows with ref_type "message" | "story" | "dossier". Stories get theirs
from @scout; messages are embedded after they're saved (`embed_message`), and `backfill()`
catches up anything missing (e.g. after a provider outage).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Engine, text
from sqlmodel import Session, col, select

from apps.api.agents.dedup import cosine, load_vectors, save_vector
from apps.api.db.models import Chat, Dossier, Embedding, Message, Story
from apps.api.providers.base import ProviderError
from apps.api.providers.router import get_router

log = logging.getLogger(__name__)

RRF_K = 60
SNIPPET_CHARS = 280
EMBED_CHARS = 2000  # embed the start of long texts only
MIN_VECTOR_SIMILARITY = 0.25
EMBEDDED_ROLES = ("user", "assistant", "agent")

FTS = {  # ref_type → (fts table, column used for snippets)
    "message": ("messages_fts", "content"),
    "story": ("stories_fts", "title"),
    "dossier": ("dossiers_fts", "markdown"),
}


@dataclass
class Hit:
    ref_type: str
    ref_id: int
    score: float = 0.0
    keyword_rank: int | None = None
    vector_similarity: float | None = None


def fts_query(query: str) -> str:
    """User text → a safe FTS5 query: each word quoted (no operator injection), OR-joined."""
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1]
    return " OR ".join(f'"{w}"*' for w in words[:12])


def keyword_search(engine: Engine, query: str, limit: int) -> dict[str, list[int]]:
    q = fts_query(query)
    if not q:
        return {}
    out: dict[str, list[int]] = {}
    with Session(engine) as s:
        for ref_type, (table, _) in FTS.items():
            sql = (
                f"SELECT rowid FROM {table} WHERE {table} MATCH :q ORDER BY bm25({table}) LIMIT :n"
            )
            rows = s.execute(text(sql), {"q": q, "n": limit})  # table names are constants
            out[ref_type] = [int(r[0]) for r in rows]
    return out


async def vector_search(
    engine: Engine, query: str, limit: int
) -> dict[str, list[tuple[int, float]]]:
    try:
        result = await get_router().embed([query])
    except ProviderError as e:
        log.info("memory: query embedding failed, keyword search only: %s", e)
        return {}
    vec = result.vectors[0]
    out: dict[str, list[tuple[int, float]]] = {}
    for ref_type in FTS:
        scored = [(rid, cosine(vec, v)) for rid, v in load_vectors(engine, ref_type, result.model)]
        scored = [x for x in scored if x[1] >= MIN_VECTOR_SIMILARITY]
        scored.sort(key=lambda x: x[1], reverse=True)
        out[ref_type] = scored[:limit]
    return out


def _snippet(value: str | None, query: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    if len(value) <= SNIPPET_CHARS:
        return value
    words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 2]
    lower = value.lower()
    pos = min((lower.find(w) for w in words if lower.find(w) >= 0), default=0)
    start = max(0, pos - SNIPPET_CHARS // 3)
    return ("…" if start else "") + value[start : start + SNIPPET_CHARS].strip() + "…"


def _describe(s: Session, hit: Hit, query: str) -> dict[str, Any] | None:
    base: dict[str, Any] = {
        "type": hit.ref_type,
        "id": hit.ref_id,
        "score": round(hit.score, 4),
        "match": [
            m
            for m, on in (
                ("keyword", hit.keyword_rank is not None),
                ("semantic", hit.vector_similarity is not None),
            )
            if on
        ],
    }
    if hit.ref_type == "message":
        msg = s.get(Message, hit.ref_id)
        if msg is None:
            return None
        chat = s.get(Chat, msg.chat_id)
        return base | {
            "chat_id": msg.chat_id,
            "chat_title": chat.title if chat else None,
            "role": msg.role,
            "created_at": msg.created_at.isoformat(),
            "snippet": _snippet(msg.content, query),
        }
    if hit.ref_type == "story":
        story = s.get(Story, hit.ref_id)
        if story is None:
            return None
        return base | {
            "story_id": story.id,
            "title": story.title,
            "status": story.status,
            "series": story.series,
            "snippet": _snippet(story.hook or story.notes, query),
        }
    dossier = s.get(Dossier, hit.ref_id)
    if dossier is None:
        return None
    return base | {
        "story_id": dossier.story_id,
        "version": dossier.version,
        "snippet": _snippet(dossier.markdown, query),
    }


async def search(
    engine: Engine,
    query: str,
    *,
    limit: int = 8,
    types: list[str] | None = None,
    exclude_chat_id: int | None = None,
) -> dict[str, Any]:
    """Hybrid search. `exclude_chat_id` drops the current chat's own messages (the
    orchestrator already has them in context)."""
    wanted = [t for t in (types or list(FTS)) if t in FTS]
    pool = limit * 4
    keyword = keyword_search(engine, query, pool)
    vector = await vector_search(engine, query, pool)
    hits: dict[tuple[str, int], Hit] = {}
    for ref_type in wanted:
        for rank, rid in enumerate(keyword.get(ref_type, []), start=1):
            h = hits.setdefault((ref_type, rid), Hit(ref_type, rid))
            h.keyword_rank = rank
            h.score += 1 / (RRF_K + rank)
        for rank, (rid, sim) in enumerate(vector.get(ref_type, []), start=1):
            h = hits.setdefault((ref_type, rid), Hit(ref_type, rid))
            h.vector_similarity = round(sim, 3)
            h.score += 1 / (RRF_K + rank)
    ranked = sorted(hits.values(), key=lambda h: h.score, reverse=True)
    results: list[dict[str, Any]] = []
    with Session(engine) as s:
        for hit in ranked:
            item = _describe(s, hit, query)
            if item is None:
                continue
            if exclude_chat_id is not None and item.get("chat_id") == exclude_chat_id:
                continue
            results.append(item)
            if len(results) >= limit:
                break
    return {
        "query": query,
        "results": results,
        "semantic": bool(vector),  # False = embedding provider unavailable, keyword only
    }


# ---------------------------------------------------------------------------- indexing
def message_text(msg: Message) -> str:
    return msg.content[:EMBED_CHARS]


async def embed_refs(engine: Engine, ref_type: str, items: list[tuple[int, str]]) -> int:
    """Embed and store vectors; returns how many were saved. Never raises on provider errors."""
    items = [(rid, t) for rid, t in items if t.strip()]
    if not items:
        return 0
    try:
        result = await get_router().embed([t for _, t in items])
    except ProviderError as e:
        log.info("memory: embedding %d %s(s) failed, will retry later: %s", len(items), ref_type, e)
        return 0
    for (rid, _), vec in zip(items, result.vectors, strict=True):
        save_vector(engine, ref_type, rid, result.model, vec)
    return len(items)


async def embed_message(engine: Engine, message_id: int) -> None:
    with Session(engine) as s:
        msg = s.get(Message, message_id)
        if msg is None or msg.role not in EMBEDDED_ROLES:
            return
        payload = [(message_id, message_text(msg))]
    await embed_refs(engine, "message", payload)


async def backfill(engine: Engine, batch: int = 32, max_items: int = 256) -> int:
    """Embed messages, stories and dossiers that have no vector yet (any model)."""
    done = 0
    with Session(engine) as s:
        have = {(rt, rid) for rt, rid in s.exec(select(Embedding.ref_type, Embedding.ref_id)).all()}
        todo: dict[str, list[tuple[int, str]]] = {"message": [], "story": [], "dossier": []}
        for msg in s.exec(
            select(Message)
            .where(col(Message.role).in_(EMBEDDED_ROLES))
            .order_by(col(Message.id).desc())
            .limit(max_items * 2)
        ).all():
            if msg.id is not None and ("message", msg.id) not in have:
                todo["message"].append((msg.id, message_text(msg)))
        for story in s.exec(select(Story).order_by(col(Story.id).desc()).limit(max_items)).all():
            if story.id is not None and ("story", story.id) not in have:
                todo["story"].append((story.id, story_text(story)))
        for d in s.exec(select(Dossier).order_by(col(Dossier.id).desc()).limit(max_items)).all():
            if d.id is not None and ("dossier", d.id) not in have:
                todo["dossier"].append((d.id, d.markdown[:EMBED_CHARS]))
    for ref_type, items in todo.items():
        items = items[:max_items]
        for start in range(0, len(items), batch):
            saved = await embed_refs(engine, ref_type, items[start : start + batch])
            if saved == 0:
                break  # provider down: stop, try again next time
            done += saved
    return done


def story_text(story: Story) -> str:
    return " — ".join(p for p in (story.title, story.company, story.hook, story.notes) if p)[
        :EMBED_CHARS
    ]
