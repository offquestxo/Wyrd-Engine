"""App settings stored in the `settings` table (owner preferences, not secrets)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session

from apps.api.db.models import Setting


def get_setting(engine: Engine, key: str, default: Any = None) -> Any:
    with Session(engine) as s:
        row = s.get(Setting, key)
        return default if row is None else row.value


def set_setting(engine: Engine, key: str, value: Any) -> None:
    with Session(engine) as s:
        row = s.get(Setting, key) or Setting(key=key)
        row.value = value
        s.add(row)
        s.commit()


def auto_approve_key(agent: str) -> str:
    return f"agents.{agent}.auto_approve"
