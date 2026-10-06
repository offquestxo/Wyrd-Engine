"""@outlier — YouTube outlier research (SPEC §6.2).

For each competitor channel: resolve handle → channel ID (cached), list recent uploads
(uploads playlist), fetch stats/duration/aspect ratio (videos.list, 50 per call), classify
Shorts vs long-form, compute each format's median views, and score outliers = views ÷ median.
Flagged videos (≥ threshold) get an analysis (topic, hook pattern, why it worked, wyrd.exe
angle) through the router's `analyze_outliers` task.

YouTube cost per channel = 1 (channels.list, only if the ID isn't cached) + ceil(n/50)
playlistItems.list + ceil(n/50) videos.list. `estimate()` uses the same formula and the run
reports estimate vs. actual.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlmodel import Session, select

from apps.api.agents.params import OutlierParams
from apps.api.config import load_channels, load_scoring
from apps.api.db.models import Channel, Video, utcnow
from apps.api.db.session import get_engine
from apps.api.providers.base import ProviderError
from apps.api.providers.router import get_router
from apps.api.providers.schemas import VideoForAnalysis
from apps.api.sources import youtube
from apps.api.sources._http import SourceError

if TYPE_CHECKING:
    from apps.api.jobs import RunContext

PAGE = 50  # playlistItems/videos.list page size


# ---------------------------------------------------------------------------- classification
def is_short(
    duration_s: int, vertical: bool | None, published: date | None, cfg: dict[str, Any]
) -> bool:
    """YouTube's rule: square/vertical and ≤ 3 min (≤ 60 s for uploads before 2024-10-15).

    If the aspect ratio is unknown, fall back to duration alone."""
    cutoff = date.fromisoformat(str(cfg.get("shorts_long_limit_from", "2024-10-15")))
    limit = int(cfg.get("shorts_max_duration_s", 180))
    if published is not None and published < cutoff:
        limit = int(cfg.get("shorts_max_duration_before_s", 60))
    if duration_s <= 0 or duration_s > limit:
        return False
    return vertical is not False


def parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------- estimate
def channel_handles(params: OutlierParams) -> list[str]:
    handles = params.channels or [c.handle for c in load_channels().channels]
    return [h if h.startswith("@") else f"@{h}" for h in handles]


def units_for(n_videos: int, cached: bool) -> int:
    pages = max(1, math.ceil(n_videos / PAGE))
    return (0 if cached else 1) + pages + pages


def estimate(params: dict[str, Any]) -> dict[str, Any]:
    """Plan-card estimate. Exact for channels with at least `videos_per_channel` uploads;
    a channel with fewer uploads (or a failed lookup) uses less."""
    p = OutlierParams.model_validate(params)
    handles = channel_handles(p)
    with Session(get_engine()) as s:
        cached = {c.handle.lower() for c in s.exec(select(Channel)).all() if c.channel_id}
    units = sum(units_for(p.videos_per_channel, h.lower() in cached) for h in handles)
    return {
        "youtube_search_calls": 0,
        "youtube_units": units,
        "note": f"{len(handles)} channels × {p.videos_per_channel} videos",
    }


# ---------------------------------------------------------------------------- run
@dataclass
class ChannelScan:
    handle: str
    name: str = ""
    videos: list[Video] = field(default_factory=list)
    medians: dict[str, float] = field(default_factory=dict)  # "short"/"long" → median views
    flagged: list[Video] = field(default_factory=list)
    units: int = 0
    error: str | None = None


async def run(ctx: RunContext) -> dict[str, Any]:
    p = OutlierParams.model_validate(ctx.params)
    cfg = load_scoring().outlier
    engine = get_engine()
    handles = channel_handles(p)
    estimated = estimate(ctx.params)["youtube_units"]
    ctx.log(
        "info",
        f"Scanning {len(handles)} channels × {p.videos_per_channel} videos "
        f"(estimated {estimated} YouTube units)",
    )
    scans: list[ChannelScan] = []
    for i, handle in enumerate(handles, start=1):
        ctx.step(f"Scanning {handle} ({i}/{len(handles)})", 0.05 + 0.6 * (i - 1) / len(handles))
        scan = await scan_channel(ctx, engine, handle, p, cfg)
        scans.append(scan)
    units = sum(s.units for s in scans)

    flagged = sorted(
        (v for s in scans for v in s.flagged), key=lambda v: v.outlier_score or 0, reverse=True
    )
    ctx.log(
        "info",
        f"{len(flagged)} outliers ≥ {p.threshold}× across {len(scans)} channels; "
        f"YouTube units used {units} (estimated {estimated})",
    )

    ctx.step("Analysing outliers", 0.7)
    analysed = await analyse(ctx, engine, flagged, scans, cfg)

    ctx.step("Done", 1.0)
    top = [
        {
            "video_id": v.video_id,
            "title": v.title,
            "outlier_score": v.outlier_score,
            "views": v.views,
            "is_short": v.is_short,
            "channel": next(s.name for s in scans if v in s.flagged),
        }
        for v in flagged[:10]
    ]
    summary = (
        f"Outlier scan: {len(flagged)} videos ≥ {p.threshold}× their channel median "
        f"across {sum(1 for s in scans if not s.error)} channels · {units} YouTube units"
    )
    return {
        "summary": summary,
        "youtube_units": units,
        "youtube_units_estimated": estimated,
        "channels": [
            {
                "handle": s.handle,
                "name": s.name,
                "videos": len(s.videos),
                "medians": s.medians,
                "flagged": len(s.flagged),
                "units": s.units,
                "error": s.error,
            }
            for s in scans
        ],
        "flagged": len(flagged),
        "analysed": analysed,
        "top": top,
    }


async def scan_channel(
    ctx: RunContext, engine: Any, handle: str, p: OutlierParams, cfg: dict[str, Any]
) -> ChannelScan:
    scan = ChannelScan(handle=handle)
    with Session(engine) as s:
        channel = s.exec(select(Channel).where(Channel.handle == handle)).first()
    try:
        if channel is None or not channel.channel_id or not channel.uploads_playlist_id:
            info = await youtube.channel(handle)
            scan.units += 1
            with Session(engine) as s:
                channel = s.exec(
                    select(Channel).where(Channel.handle == handle)
                ).first() or Channel(handle=handle)
                channel.channel_id = info.channel_id
                channel.name = info.name
                channel.uploads_playlist_id = info.uploads_playlist_id
                channel.subscribers = info.subscribers
                s.add(channel)
                s.commit()
                s.refresh(channel)
            subs = f"{info.subscribers:,} subscribers" if info.subscribers else "subscribers hidden"
            ctx.log(
                "info",
                f"Resolved {handle} → {info.name} ({info.channel_id}, {subs}, "
                f"{info.video_count or 0:,} videos)",
            )
        assert channel is not None and channel.uploads_playlist_id and channel.id is not None
        scan.name = channel.name or handle
        uploads = await youtube.uploads(channel.uploads_playlist_id, p.videos_per_channel)
        scan.units += uploads.units_used
        stats = await youtube.videos(uploads.video_ids)
        scan.units += stats.units_used
    except SourceError as e:
        scan.error = str(e)
        ctx.log("warn", f"{handle}: scan failed, skipped: {e}")
        return scan

    now = datetime.now(UTC)
    min_age = timedelta(days=int(cfg.get("min_age_days", 3)))
    rows: list[Video] = []
    with Session(engine) as s:
        for v in stats.videos:
            published = parse_published(v.published_at)
            row = s.exec(select(Video).where(Video.video_id == v.video_id)).first() or Video(
                channel_id=channel.id, video_id=v.video_id, title=v.title
            )
            row.channel_id = channel.id
            row.title = v.title
            row.published_at = published
            row.duration_s = v.duration_s
            row.vertical = v.vertical
            row.is_short = is_short(
                v.duration_s, v.vertical, published.date() if published else None, cfg
            )
            row.views, row.likes, row.comments = v.views, v.likes, v.comments
            row.thumbnail_url = v.thumbnail_url
            row.scanned_at = utcnow()
            row.last_run_id = ctx.run_id
            s.add(row)
            rows.append(row)
        s.commit()
        for row in rows:
            s.refresh(row)

        # Medians per format, from videos old enough to have settled.
        mature = [
            r
            for r in rows
            if r.published_at and now - r.published_at >= min_age and r.views is not None
        ]
        for fmt, want_short in (("short", True), ("long", False)):
            pool = [r.views or 0 for r in mature if r.is_short == want_short]
            if len(pool) >= int(cfg.get("min_videos_for_median", 5)):
                scan.medians[fmt] = float(statistics.median(pool))
        for r in rows:
            fmt = "short" if r.is_short else "long"
            median = scan.medians.get(fmt)
            r.channel_median = median
            r.outlier_score = round((r.views or 0) / median, 2) if median else None
            s.add(r)
            wanted = p.format == "both" or (p.format == "shorts") == bool(r.is_short)
            if (
                wanted
                and r in mature
                and r.outlier_score is not None
                and r.outlier_score >= p.threshold
            ):
                scan.flagged.append(r)
        channel.last_scanned_at = utcnow()
        s.add(channel)
        s.commit()
        for r in rows:
            s.refresh(r)
    scan.videos = rows
    shorts = sum(1 for r in rows if r.is_short)
    ctx.log(
        "info",
        f"{scan.name}: {len(rows)} videos ({shorts} Shorts, {len(rows) - shorts} long); "
        f"medians {', '.join(f'{k} {v:,.0f}' for k, v in scan.medians.items()) or 'n/a'}; "
        f"{len(scan.flagged)} outliers; {scan.units} units",
    )
    skipped = [fmt for fmt in ("short", "long") if fmt not in scan.medians]
    if skipped:
        ctx.log(
            "info",
            f"{scan.name}: not enough {'/'.join(skipped)} videos for a median "
            f"(need {cfg.get('min_videos_for_median', 5)} older than {min_age.days} days)",
        )
    return scan


async def analyse(
    ctx: RunContext,
    engine: Any,
    flagged: list[Video],
    scans: list[ChannelScan],
    cfg: dict[str, Any],
) -> int:
    todo = [v for v in flagged if not v.analysis][: int(cfg.get("analyze_max", 25))]
    if not todo:
        ctx.log("info", "No new outliers to analyse")
        return 0
    channel_name = {v.video_id: s.name for s in scans for v in s.flagged}
    batch_size = int(cfg.get("analyze_batch", 8))
    router = get_router()
    done = 0
    for start in range(0, len(todo), batch_size):
        chunk = todo[start : start + batch_size]
        payload = [
            VideoForAnalysis(
                video_id=v.video_id,
                channel=channel_name.get(v.video_id, ""),
                title=v.title,
                views=v.views or 0,
                outlier_score=v.outlier_score or 0,
                is_short=bool(v.is_short),
                published_at=v.published_at.date().isoformat() if v.published_at else None,
            )
            for v in chunk
        ]
        try:
            results = await router.analyze_outliers(payload)
        except ProviderError as e:
            ctx.log("warn", f"Analysis of {len(chunk)} outliers failed, left for next run: {e}")
            continue
        by_id = {r.video_id: r for r in results}
        with Session(engine) as s:
            for v in chunk:
                result = by_id.get(v.video_id)
                if result is None:
                    continue
                row = s.exec(select(Video).where(Video.video_id == v.video_id)).one()
                row.analysis = result.model_dump(exclude={"video_id"})
                s.add(row)
                done += 1
            s.commit()
        ctx.step(f"Analysed {done}/{len(todo)} outliers", 0.7 + 0.28 * done / len(todo))
    ctx.log("info", f"Analysed {done} outliers")
    return done
