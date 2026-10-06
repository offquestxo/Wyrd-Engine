"""Quota meters for the dashboard, built from `provider_usage` and `agent_runs` (SPEC §4.2, §9).

"Today" starts at midnight in `engine.yaml` usage.day_reset_timezone (Google resets at midnight
Pacific). Per-minute figures cover the last 60 seconds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, func
from sqlalchemy import select as sa_select
from sqlmodel import Session, col

from apps.api.config import EngineConfig, ProvidersConfig
from apps.api.db.models import ProviderUsage
from apps.api.settings_store import get_setting

LABELS = {
    "groq": "Groq",
    "gemini": "Gemini",
    "nvidia": "NVIDIA",
    "mistral": "Mistral",
    "openrouter": "OpenRouter",
    "youtube": "YouTube",
    "claude": "Claude",
}


def day_start(tz_name: str, now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    local = now.astimezone(ZoneInfo(tz_name))
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(UTC)


def _aggregate(s: Session, since: datetime, provider: str) -> dict[str | None, dict[str, int]]:
    tokens = col(ProviderUsage.tokens_in) + col(ProviderUsage.tokens_out)
    rows = s.execute(
        sa_select(
            col(ProviderUsage.model),
            func.count(col(ProviderUsage.id)),
            func.coalesce(func.sum(tokens), 0),
            func.coalesce(func.sum(col(ProviderUsage.units)), 0),
            func.coalesce(func.sum(1 - col(ProviderUsage.ok)), 0),
            func.coalesce(func.sum(col(ProviderUsage.fallback)), 0),
        )
        .where(col(ProviderUsage.provider) == provider, col(ProviderUsage.ts) >= since)
        .group_by(col(ProviderUsage.model))
    ).all()
    return {
        model: {
            "requests": int(n),
            "tokens": int(t),
            "units": int(u),
            "errors": int(e),
            "fallbacks": int(f),
        }
        for model, n, t, u, e, f in rows
    }


def build_report(
    engine: Engine,
    providers: ProvidersConfig,
    engine_cfg: EngineConfig,
    key_status: dict[str, str],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    since_day = day_start(engine_cfg.usage.day_reset_timezone, now)
    since_min = now - timedelta(minutes=1)
    meters: list[dict[str, Any]] = []
    with Session(engine) as s:
        for name, pc in providers.providers.items():
            if pc.kind == "quota_only":
                continue
            day = _aggregate(s, since_day, name)
            minute = _aggregate(s, since_min, name)
            models = []
            for alias, m in pc.models.items():
                d = day.get(m.id, {})
                mm = minute.get(m.id, {})
                models.append(
                    {
                        "alias": alias,
                        "id": m.id,
                        "requests": d.get("requests", 0),
                        "tokens": d.get("tokens", 0),
                        "errors": d.get("errors", 0),
                        "fallbacks": d.get("fallbacks", 0),
                        "requests_last_min": mm.get("requests", 0),
                        "tokens_last_min": mm.get("tokens", 0),
                        "limits": m.limits.model_dump(),
                    }
                )
            meters.append(_llm_meter(name, models, key_status.get(name, "missing")))
        meters.append(_youtube_meter(s, since_day, providers, key_status.get("youtube", "missing")))
        meters.append(_claude_meter(s, engine, since_day, engine_cfg))
    return {
        "since": since_day.isoformat(),
        "timezone": engine_cfg.usage.day_reset_timezone,
        "meters": meters,
    }


def _llm_meter(name: str, models: list[dict[str, Any]], status: str) -> dict[str, Any]:
    # Headline = the model/limit pair closest to its cap (daily if known, else per minute).
    best: tuple[float, int, int | None, str] = (-1.0, 0, None, "requests")
    for m in models:
        lim = m["limits"]
        for used, limit, unit in (
            (m["requests"], lim["rpd"], "requests"),
            (m["tokens"], lim["tpd"], "tokens"),
            (m["requests_last_min"], lim["rpm"], "requests/min"),
            (m["tokens_last_min"], lim["tpm"], "tokens/min"),
        ):
            if limit:
                ratio = used / limit
                if ratio > best[0]:
                    best = (ratio, used, limit, unit)
    total = {k: sum(m[k] for m in models) for k in ("requests", "tokens", "errors", "fallbacks")}
    if best[2] is None:
        best = (0.0, total["requests"], None, "requests")
    return {
        "provider": name,
        "label": LABELS.get(name, name),
        "status": status,
        "used": best[1],
        "limit": best[2],
        "unit": best[3],
        **total,
        "models": models,
    }


def _youtube_meter(
    s: Session, since: datetime, providers: ProvidersConfig, status: str
) -> dict[str, Any]:
    limits = providers.providers["youtube"].limits if "youtube" in providers.providers else {}
    day = _aggregate(s, since, "youtube")
    units = sum(v["units"] for v in day.values())
    searches = day.get("search", {}).get("requests", 0)
    return {
        "provider": "youtube",
        "label": "YouTube",
        "status": status,
        "used": units,
        "limit": limits.get("units_per_day"),
        "unit": "units",
        "requests": sum(v["requests"] for v in day.values()),
        "tokens": 0,
        "errors": sum(v["errors"] for v in day.values()),
        "fallbacks": 0,
        "search_calls": searches,
        "search_limit": limits.get("search_calls_per_day"),
        "models": [],
    }


CLAUDE_CAP_KEY = "claude.daily_soft_cap"
CLAUDE_RATE_KEY = "claude.rate_limit"


def claude_soft_cap(engine: Engine, engine_cfg: EngineConfig) -> int:
    """Settings override, else engine.yaml orchestrator.daily_soft_cap."""
    value = get_setting(engine, CLAUDE_CAP_KEY)
    return (
        int(value)
        if isinstance(value, int | float) and value > 0
        else (engine_cfg.orchestrator.daily_soft_cap)
    )


def _claude_meter(
    s: Session, engine: Engine, since: datetime, engine_cfg: EngineConfig
) -> dict[str, Any]:
    """Claude calls today: one provider_usage row per orchestrator chat turn and per Claude
    agent run (e.g. @researcher). Pro plan usage isn't exposed, so this is a local count
    against a soft cap.
    `rate_limit` is the last status Claude Code itself reported (allowed / warning / rejected)."""
    turns_row = s.execute(
        sa_select(
            func.count(col(ProviderUsage.id)),
            func.coalesce(func.sum(col(ProviderUsage.latency_ms)), 0),
            func.coalesce(func.sum(col(ProviderUsage.turns)), 0),
            func.coalesce(func.sum(1 - col(ProviderUsage.ok)), 0),
            func.coalesce(
                func.sum(col(ProviderUsage.tokens_in) + col(ProviderUsage.tokens_out)), 0
            ),
        ).where(col(ProviderUsage.provider) == "claude", col(ProviderUsage.ts) >= since)
    ).one()
    used, duration_ms, turns, errors, tokens = (int(v) for v in turns_row)
    by_task: dict[str | None, int] = {
        task: int(n)
        for task, n in s.execute(
            sa_select(col(ProviderUsage.task), func.count(col(ProviderUsage.id)))
            .where(col(ProviderUsage.provider) == "claude", col(ProviderUsage.ts) >= since)
            .group_by(col(ProviderUsage.task))
        ).all()
    }
    chat_calls = int(by_task.get("orchestrator", 0))
    agent_runs = used - chat_calls  # @researcher runs (and future Claude agents)
    cap = claude_soft_cap(engine, engine_cfg)
    ratio = used / cap if cap else 0.0
    return {
        "provider": "claude",
        "label": "Claude",
        "status": "set",
        "used": used,
        "limit": cap,
        "unit": "calls",
        "requests": used,
        "tokens": tokens,
        "errors": errors,
        "fallbacks": 0,
        "models": [],
        "claude": {
            "chat_turns": chat_calls,
            "agent_runs": agent_runs,
            "duration_s": round(duration_ms / 1000),
            "turns": turns,
            "soft_cap": cap,
            "warn": ratio >= engine_cfg.orchestrator.warn_ratio,
            "over": used >= cap,
            "rate_limit": get_setting(engine, CLAUDE_RATE_KEY),
        },
    }


def youtube_used_today(
    engine: Engine, engine_cfg: EngineConfig, now: datetime | None = None
) -> tuple[int, int]:
    """(units, search.list calls) used since today's quota reset."""
    since = day_start(engine_cfg.usage.day_reset_timezone, now)
    with Session(engine) as s:
        day = _aggregate(s, since, "youtube")
    units = sum(v["units"] for v in day.values())
    return units, day.get("search", {}).get("requests", 0)
