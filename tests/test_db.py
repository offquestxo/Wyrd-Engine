from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlmodel import Session, SQLModel, select, text

from apps.api.db import models
from apps.api.db.migrate import connect, migrate, migrate_path
from apps.api.db.session import make_engine


def test_migrations_are_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    assert migrate_path(db) == ["0001_initial.sql", "0002_fts.sql"]
    assert migrate_path(db) == []


def test_wal_mode(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_models_match_migrated_schema() -> None:
    conn = sqlite3.connect(":memory:")
    migrate(conn)
    assert models.Story  # ensure models are registered on the metadata
    for table in SQLModel.metadata.sorted_tables:
        sql_cols = {row[1] for row in conn.execute(f'PRAGMA table_info("{table.name}")')}
        assert sql_cols, f"{table.name} missing from migrations"
        assert {c.name for c in table.columns} == sql_cols, table.name


def test_fts_tracks_inserts_updates_deletes(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    migrate_path(db)
    engine = make_engine(db)
    with Session(engine) as s:
        story = models.Story(
            slug="circuit-city",
            title="Circuit City",
            hook="A retail giant fires its best salespeople",
        )
        s.add(story)
        s.commit()
        s.refresh(story)

        def hits(q: str) -> list[int]:
            return [
                r[0]
                for r in s.exec(
                    text("SELECT rowid FROM stories_fts WHERE stories_fts MATCH :q").bindparams(q=q)
                )
            ]

        assert hits("salespeople") == [story.id]
        story.hook = "The day it laid off 3,400 experienced workers"
        s.add(story)
        s.commit()
        assert hits("salespeople") == [] and hits("workers") == [story.id]
        s.delete(story)
        s.commit()
        assert hits("workers") == []


def test_json_columns_round_trip(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    migrate_path(db)
    with Session(make_engine(db)) as s:
        run = models.AgentRun(agent="scout", params={"mode": "news", "limit": 25})
        s.add(run)
        s.commit()
        loaded = s.exec(select(models.AgentRun)).one()
        assert loaded.params == {"mode": "news", "limit": 25}
        assert loaded.status == "queued"
