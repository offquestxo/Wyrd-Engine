"""Deduplication helpers (SPEC §6.1 step 3): URL hashing, title keys, embedding similarity."""

from __future__ import annotations

import array
import hashlib
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import Engine
from sqlmodel import Session, select

from apps.api.db.models import Embedding

TRACKING_PARAMS = re.compile(r"^(utm_\w+|fbclid|gclid|mc_cid|mc_eid|ref|ref_src|cmpid|smid)$", re.I)


def normalize_url(url: str) -> str:
    """Canonical form for exact-duplicate checks: no tracking params, fragment, or www."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not TRACKING_PARAMS.match(k)])
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower() or "https", host, path, query, ""))


def url_hash(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode()).hexdigest()


def title_key(title: str) -> str:
    """Lowercased words of a headline, minus a trailing ' - Publisher' suffix."""
    head = re.sub(r"\s+[-–|]\s+[^-–|]{2,60}$", "", title.strip())
    return " ".join(re.findall(r"[a-z0-9]+", head.lower()))


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def pack(vector: Sequence[float]) -> bytes:
    return array.array("f", vector).tobytes()


def unpack(blob: bytes) -> list[float]:
    values = array.array("f")
    values.frombytes(blob)
    return values.tolist()


def load_vectors(engine: Engine, ref_type: str, model: str) -> list[tuple[int, list[float]]]:
    """Stored vectors of one model (different models' spaces aren't comparable)."""
    with Session(engine) as s:
        rows = s.exec(
            select(Embedding).where(Embedding.ref_type == ref_type, Embedding.model == model)
        ).all()
        return [(row.ref_id, unpack(row.vector)) for row in rows]


def save_vector(
    engine: Engine, ref_type: str, ref_id: int, model: str, vector: Sequence[float]
) -> None:
    with Session(engine) as s:
        existing = s.exec(
            select(Embedding).where(
                Embedding.ref_type == ref_type, Embedding.ref_id == ref_id, Embedding.model == model
            )
        ).first()
        row = existing or Embedding(ref_type=ref_type, ref_id=ref_id, model=model, vector=b"")
        row.vector = pack(vector)
        s.add(row)
        s.commit()


@dataclass
class Duplicate:
    index: int  # item that was dropped
    of_item: int | None  # kept item it duplicates, or
    of_story: int | None  # existing story it duplicates
    similarity: float


def semantic_dedupe(
    vectors: Sequence[Sequence[float]],
    existing: Sequence[tuple[int, Sequence[float]]],
    threshold: float,
) -> tuple[list[int], list[Duplicate]]:
    """Greedy pass in input order: keep an item unless it is ≥ threshold similar to an
    existing story or to an item already kept. Returns (kept indices, duplicates)."""
    kept: list[int] = []
    dupes: list[Duplicate] = []
    for i, vec in enumerate(vectors):
        best_story = max(((cosine(vec, v), sid) for sid, v in existing), default=(0.0, None))
        if best_story[0] >= threshold:
            dupes.append(Duplicate(i, None, best_story[1], round(best_story[0], 3)))
            continue
        best_item = max(((cosine(vec, vectors[k]), k) for k in kept), default=(0.0, None))
        if best_item[0] >= threshold:
            dupes.append(Duplicate(i, best_item[1], None, round(best_item[0], 3)))
            continue
        kept.append(i)
    return kept, dupes
