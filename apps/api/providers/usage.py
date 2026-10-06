"""Provider usage logging (provider_usage table) and budget checks."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, func
from sqlmodel import Session, col, select

from apps.api.config import ModelLimits
from apps.api.db.models import ProviderUsage


class UsageLog:
    def __init__(self, engine: Engine, now: Callable[[], datetime] | None = None) -> None:
        self._engine = engine
        self._now = now or (lambda: datetime.now(UTC))

    def record(
        self,
        *,
        provider: str,
        model: str | None,
        task: str | None,
        ok: bool,
        tokens_in: int = 0,
        tokens_out: int = 0,
        units: int = 0,
        latency_ms: int = 0,
        error: str | None = None,
        fallback: bool = False,
    ) -> None:
        row = ProviderUsage(
            fallback=fallback,
            provider=provider,
            model=model,
            task=task,
            ok=ok,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            units=units,
            latency_ms=latency_ms,
            error=(error or None) and error[:500],
            ts=self._now(),
        )
        with Session(self._engine) as s:
            s.add(row)
            s.commit()

    def totals(self, provider: str, model: str | None, since: datetime) -> tuple[int, int, int]:
        """(requests, tokens, units) since a time, for one provider (and model if given)."""
        stmt = select(
            func.count(col(ProviderUsage.id)),
            func.coalesce(
                func.sum(col(ProviderUsage.tokens_in) + col(ProviderUsage.tokens_out)), 0
            ),
            func.coalesce(func.sum(col(ProviderUsage.units)), 0),
        ).where(ProviderUsage.provider == provider, col(ProviderUsage.ts) >= since)
        if model:
            stmt = stmt.where(ProviderUsage.model == model)
        with Session(self._engine) as s:
            reqs, tokens, units = s.exec(stmt).one()
        return int(reqs), int(tokens), int(units)

    def usage_ratio(self, provider: str, model: str, limits: ModelLimits) -> float:
        """Highest used/limit fraction across the model's known limits (0 if none known)."""
        now = self._now()
        minute_reqs, minute_tokens, _ = self.totals(provider, model, now - timedelta(minutes=1))
        day_reqs, day_tokens, _ = self.totals(provider, model, now - timedelta(days=1))
        ratios = [
            used / limit
            for used, limit in (
                (minute_reqs, limits.rpm),
                (day_reqs, limits.rpd),
                (minute_tokens, limits.tpm),
                (day_tokens, limits.tpd),
            )
            if limit
        ]
        return max(ratios, default=0.0)

    def recent(self, provider: str, model: str, since: datetime) -> list[tuple[datetime, int]]:
        """(timestamp, tokens) of each call since a time — seeds per-minute rate limiters."""
        stmt = select(ProviderUsage.ts, ProviderUsage.tokens_in, ProviderUsage.tokens_out).where(
            ProviderUsage.provider == provider,
            ProviderUsage.model == model,
            col(ProviderUsage.ts) >= since,
        )
        with Session(self._engine) as s:
            return [(ts, int(a) + int(b)) for ts, a, b in s.exec(stmt).all()]
