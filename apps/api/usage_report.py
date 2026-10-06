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
from sqlmodel import Session, col, select

from apps.api.agents.registry import AGENTS
from apps.api.config import EngineConfig, ProvidersConfig
from apps.api.db.models import AgentRun, ProviderUsage

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
        meters.append(_claude_meter(s, since_day, providers))
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


def _claude_meter(s: Session, since: datetime, providers: ProvidersConfig) -> dict[str, Any]:
    claude_agents = [n for n, a in AGENTS.items() if a.uses_claude]
    count = s.exec(
        select(func.count(col(AgentRun.id))).where(
            col(AgentRun.agent).in_(claude_agents), col(AgentRun.started_at) >= since
        )
    ).one()
    limits = providers.providers["claude"].limits if "claude" in providers.providers else {}
    return {
        "provider": "claude",
        "label": "Claude",
        "status": "set",
        "used": int(count),
        "limit": limits.get("daily_soft_cap_runs"),
        "unit": "runs",
        "requests": int(count),
        "tokens": 0,
        "errors": 0,
        "fallbacks": 0,
        "models": [],
    }
