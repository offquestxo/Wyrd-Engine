"""Context for the run currently executing (set by the job runner, read anywhere below it).

ContextVars follow asyncio tasks, so concurrent runs never see each other's context. This lets
the provider router report retries/fallbacks into the right run's log without importing jobs.
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar
from typing import Any

RunLogger = Callable[[str, str, dict[str, Any] | None], None]  # (level, message, data)

current_run_logger: ContextVar[RunLogger | None] = ContextVar("current_run_logger", default=None)


def log_to_current_run(level: str, message: str, data: dict[str, Any] | None = None) -> None:
    logger = current_run_logger.get()
    if logger is not None:
        logger(level, message, data)
