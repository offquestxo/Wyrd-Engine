"""@outlier with a faked YouTube API (no network): Shorts rule, medians, outliers, units."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, select

from apps.api.agents import outlier
from apps.api.db.migrate import migrate_path
from apps.api.db.models import AgentRun, Channel, Story, Video
from apps.api.db.session import make_engine
from apps.api.outliers import create_story_from_outlier, list_outliers
from apps.api.providers.schemas import OutlierAnalysis, VideoForAnalysis
from apps.api.sources import youtube

CFG = {
    "shorts_max_duration_s": 180,
    "shorts_long_limit_from": "2024-10-15",
    "shorts_max_duration_before_s": 60,
}


@pytest.mark.parametrize(
    ("duration", "vertical", "published", "expected"),
    [
        (59, True, date(2025, 1, 1), True),
        (170, True, date(2025, 1, 1), True),  # 3-minute Shorts since 2024-10-15
        (170, True, date(2024, 6, 1), False),  # before that: 60 s limit
        (45, False, date(2025, 1, 1), False),  # horizontal is never a Short
        (45, None, date(2025, 1, 1), True),  # unknown shape: duration decides
        (600, True, date(2025, 1, 1), False),
    ],
)
def test_shorts_rule(duration: int, vertical: bool | None, published: date, expected: bool) -> None:
    assert outlier.is_short(duration, vertical, published, CFG) is expected


def test_units_formula() -> None:
    assert outlier.units_for(50, cached=False) == 3  # channels + 1 page uploads + 1 page stats
    assert outlier.units_for(50, cached=True) == 2
    assert outlier.units_for(120, cached=True) == 6  # 3 pages each


class Ctx:
    def __init__(self, params: dict[str, Any]) -> None:
        self.params, self.run_id, self.logs = params, 9, []

    def log(self, level: str, message: str, data: Any = None) -> None:
        self.logs.append((level, message))

    def step(self, name: str, progress: float | None = None) -> None:
        pass


NOW = datetime.now(UTC)


def channel_videos(prefix: str) -> list[youtube.VideoStats]:
    """10 long videos (~100k views, one at 1M) + 6 Shorts (~20k, one at 200k) + 1 brand-new hit."""
    out = []
    for i in range(10):
        out.append(
            youtube.VideoStats(
                video_id=f"{prefix}L{i}",
                channel_id="c",
                channel_title=prefix,
                title=f"{prefix} long {i}",
                published_at=(NOW - timedelta(days=30 + i)).isoformat(),
                duration_s=900,
                views=1_000_000 if i == 3 else 100_000 + i * 1000,
                likes=1,
                comments=1,
                url="u",
                embed_width=1000,
                embed_height=563,
            )
        )
    for i in range(6):
        out.append(
            youtube.VideoStats(
                video_id=f"{prefix}S{i}",
                channel_id="c",
                channel_title=prefix,
                title=f"{prefix} short {i}",
                published_at=(NOW - timedelta(days=20 + i)).isoformat(),
                duration_s=45,
                views=200_000 if i == 0 else 20_000,
                likes=1,
                comments=1,
                url="u",
                embed_width=563,
                embed_height=1000,
            )
        )
    out.append(
        youtube.VideoStats(
            video_id=f"{prefix}NEW",
            channel_id="c",
            channel_title=prefix,
            title="brand new",
            published_at=(NOW - timedelta(hours=10)).isoformat(),
            duration_s=900,
            views=5_000_000,
            likes=1,
            comments=1,
            url="u",
            embed_width=1000,
            embed_height=563,
        )
    )
    return out


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    migrate_path(tmp_path / "o.db")
    engine = make_engine(tmp_path / "o.db")
    with Session(engine) as s:  # videos reference the run that last scanned them
        s.add(AgentRun(id=9, agent="outlier", status="running"))
        s.commit()
    monkeypatch.setattr(outlier, "get_engine", lambda: engine)
    calls = {"channels": 0, "uploads": 0, "videos": 0, "analysed": 0}

    async def channel(handle: str) -> youtube.ChannelInfo:
        calls["channels"] += 1
        return youtube.ChannelInfo(
            handle=handle,
            channel_id=f"UC{handle}",
            name=handle.strip("@"),
            uploads_playlist_id=f"UU{handle}",
            subscribers=1,
            video_count=17,
        )

    async def uploads(playlist: str, max_results: int = 50) -> youtube.UploadList:
        calls["uploads"] += 1
        return youtube.UploadList(
            playlist_id=playlist,
            video_ids=[v.video_id for v in channel_videos(playlist)],
            units_used=max(1, -(-max_results // 50)),
        )

    async def videos(ids: list[str]) -> youtube.VideoStatsList:
        calls["videos"] += 1
        prefix = ids[0][: ids[0].index("L")] if "L" in ids[0] else ids[0]
        return youtube.VideoStatsList(
            videos=channel_videos(prefix), units_used=max(1, -(-len(ids) // 50))
        )

    class Router:
        async def analyze_outliers(self, vids: list[VideoForAnalysis]) -> list[OutlierAnalysis]:
            calls["analysed"] += len(vids)
            return [
                OutlierAnalysis(
                    video_id=v.video_id,
                    topic=f"Topic of {v.title}",
                    company_type="retailer",
                    hook_pattern="The Rise and Fall of X",
                    why_it_worked="Big name.",
                    wyrd_angle="Tell it from the employees' side.",
                )
                for v in vids
            ]

    monkeypatch.setattr(outlier.youtube, "channel", channel)
    monkeypatch.setattr(outlier.youtube, "uploads", uploads)
    monkeypatch.setattr(outlier.youtube, "videos", videos)
    monkeypatch.setattr(outlier, "get_router", lambda: Router())
    return {"engine": engine, "calls": calls}


async def test_scan_flags_outliers_per_format_and_matches_unit_estimate(
    setup: dict[str, Any],
) -> None:
    engine, calls = setup["engine"], setup["calls"]
    params = {"channels": ["@companyman", "@ModernMBA", "@MagnatesMedia"], "videos_per_channel": 50}
    estimate = outlier.estimate(params)["youtube_units"]
    result = await outlier.run(Ctx(params))  # type: ignore[arg-type]

    assert estimate == 9  # 3 channels × (1 lookup + 1 uploads page + 1 videos page)
    assert result["youtube_units"] == result["youtube_units_estimated"] == estimate
    assert calls["channels"] == 3
    ch = result["channels"][0]
    assert ch["medians"]["long"] == pytest.approx(105_500) and ch["medians"]["short"] == 20_000
    # Per channel: the 1M long video (≈9.6×) and the 200k Short (10×); the 10-hour-old 5M video
    # is too new to flag, and doesn't distort the long median.
    assert result["flagged"] == 6 and calls["analysed"] == 6
    with Session(engine) as s:
        vids = s.exec(select(Video)).all()
        new = next(v for v in vids if v.video_id.endswith("NEW"))
        short = next(v for v in vids if v.video_id.endswith("S0"))
    assert new.outlier_score and new.outlier_score > 40 and new.analysis is None
    assert short.is_short and short.outlier_score == 10.0 and short.analysis
    assert short.analysis["hook_pattern"] == "The Rise and Fall of X"

    # Second scan: channel IDs are cached, already-analysed videos aren't re-analysed.
    est2 = outlier.estimate(params)["youtube_units"]
    again = await outlier.run(Ctx(params))  # type: ignore[arg-type]
    assert est2 == 6 and again["youtube_units"] == est2 and calls["channels"] == 3
    assert again["analysed"] == 0


async def test_format_filter_and_outlier_listing(setup: dict[str, Any]) -> None:
    engine = setup["engine"]
    await outlier.run(Ctx({"channels": ["@companyman"], "format": "shorts"}))  # type: ignore[arg-type]
    shorts = list_outliers(engine, format="shorts")
    assert [v["video_id"] for v in shorts] == ["UU@companymanS0"]
    assert shorts[0]["channel_name"] == "companyman" and shorts[0]["analysis"]


async def test_create_story_from_outlier_links_back(setup: dict[str, Any]) -> None:
    engine = setup["engine"]
    await outlier.run(Ctx({"channels": ["@companyman"]}))  # type: ignore[arg-type]
    video_id = list_outliers(engine)[0]["video_id"]
    first = create_story_from_outlier(engine, video_id)
    assert first and first["created"]
    again = create_story_from_outlier(engine, video_id)
    assert again == {"story_id": first["story_id"], "created": False}
    with Session(engine) as s:
        story = s.get(Story, first["story_id"])
        video = s.exec(select(Video).where(Video.video_id == video_id)).one()
    assert story and story.outlier_ref == video.id and story.status == "Inbox"
    assert story.title.startswith("Topic of") and "From @outlier" in (story.notes or "")
    assert create_story_from_outlier(engine, "nope") is None


async def test_failed_channel_is_skipped_not_fatal(
    setup: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.sources._http import SourceError

    async def broken(handle: str) -> Any:
        raise SourceError("youtube", f"no channel for handle {handle}")

    monkeypatch.setattr(outlier.youtube, "channel", broken)
    result = await outlier.run(Ctx({"channels": ["@doesnotexist"]}))  # type: ignore[arg-type]
    assert result["channels"][0]["error"] and result["flagged"] == 0
    with Session(setup["engine"]) as s:
        assert s.exec(select(Channel)).all() == []
