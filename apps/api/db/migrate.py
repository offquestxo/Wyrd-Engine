"""Plain-SQL migration runner. Files in migrations/ run once, in name order.

Usage: python -m apps.api.db.migrate [--db PATH]
"""

from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from apps.api.settings import get_settings

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(db_path: Path | str) -> sqlite3.Connection:
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply pending migrations. Returns the names applied this call."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    done = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
    applied: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if path.name in done:
            continue
        # executescript commits implicitly; wrap so a failing file leaves no partial state.
        script = path.read_text()
        stamp = datetime.now(UTC).isoformat()
        conn.executescript(
            f"BEGIN;\n{script}\n"
            f"INSERT INTO schema_migrations (name, applied_at) VALUES ('{path.name}', '{stamp}');\n"
            "COMMIT;"
        )
        applied.append(path.name)
    return applied


def migrate_path(db_path: Path | str) -> list[str]:
    conn = connect(db_path)
    try:
        return migrate(conn)
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or upgrade the SQLite database.")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args()
    db_path = args.db or get_settings().db_path
    applied = migrate_path(db_path)
    print(f"{db_path}: applied {applied or 'nothing (up to date)'}")


if __name__ == "__main__":
    main()
