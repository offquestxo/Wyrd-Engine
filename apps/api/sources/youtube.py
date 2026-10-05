"""YouTube Data API v3: channel/video stats for @outlier and coverage checks for the gap finder.

Docs: https://developers.google.com/youtube/v3/docs and /determine_quota_cost
Quota: 10,000 units/day; channels/playlistItems/videos.list cost 1 unit;
search.list costs 1 unit but is capped separately at 100 calls/day. Every result reports
the units/search calls it used so callers can budget.

CLI:
  python -m apps.api.sources.youtube channel @companyman
  python -m apps.api.sources.youtube uploads UU... --max 50
  python -m apps.api.sources.youtube videos VIDEO_ID [VIDEO_ID ...]
  python -m apps.api.sources.youtube search "Circuit City collapse" --max 10
"""

from __future__ import annotations

import argparse
import re
from typing import Any

from pydantic import BaseModel

from apps.api.settings import get_settings
from apps.api.sources._http import SourceError, get_json, run_cli

SOURCE = "youtube"
API = "https://www.googleapis.com/youtube/v3"
_DURATION = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


class ChannelInfo(BaseModel):
    handle: str
    channel_id: str
    name: str
    uploads_playlist_id: str
    subscribers: int | None
    video_count: int | None
    units_used: int = 1


class UploadList(BaseModel):
    playlist_id: str
    video_ids: list[str]
    units_used: int


class VideoStats(BaseModel):
    video_id: str
    channel_id: str
    channel_title: str
    title: str
    published_at: str
    duration_s: int
    views: int | None
    likes: int | None
    comments: int | None
    url: str


class VideoStatsList(BaseModel):
    videos: list[VideoStats]
    units_used: int


class SearchResults(BaseModel):
    query: str
    video_ids: list[str]
    search_calls_used: int = 1
    units_used: int = 1


def parse_duration(iso: str) -> int:
    match = _DURATION.fullmatch(iso or "")
    if not match:
        return 0
    days, hours, minutes, seconds = (int(g or 0) for g in match.groups())
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _key() -> str:
    key = get_settings().youtube_api_key
    if not key:
        raise SourceError(SOURCE, "YOUTUBE_API_KEY is not set")
    return key


def _int(value: Any) -> int | None:
    return int(value) if value is not None else None


async def _get(path: str, params: dict[str, Any]) -> Any:
    return await get_json(SOURCE, f"{API}/{path}", params={**params, "key": _key()})


async def channel(handle: str) -> ChannelInfo:
    handle = handle if handle.startswith("@") else f"@{handle}"
    data = await _get(
        "channels", {"part": "snippet,contentDetails,statistics", "forHandle": handle}
    )
    items = data.get("items") or []
    if not items:
        raise SourceError(SOURCE, f"no channel for handle {handle}")
    item = items[0]
    stats = item.get("statistics") or {}
    return ChannelInfo(
        handle=handle,
        channel_id=item["id"],
        name=item["snippet"]["title"],
        uploads_playlist_id=item["contentDetails"]["relatedPlaylists"]["uploads"],
        subscribers=None
        if stats.get("hiddenSubscriberCount")
        else _int(stats.get("subscriberCount")),
        video_count=_int(stats.get("videoCount")),
    )


async def uploads(playlist_id: str, max_results: int = 50) -> UploadList:
    ids: list[str] = []
    page_token: str | None = None
    units = 0
    while len(ids) < max_results:
        params: dict[str, Any] = {
            "part": "contentDetails",
            "playlistId": playlist_id,
            "maxResults": min(50, max_results - len(ids)),
        }
        if page_token:
            params["pageToken"] = page_token
        data = await _get("playlistItems", params)
        units += 1
        ids += [row["contentDetails"]["videoId"] for row in data.get("items", [])]
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return UploadList(playlist_id=playlist_id, video_ids=ids[:max_results], units_used=units)


async def videos(video_ids: list[str]) -> VideoStatsList:
    out: list[VideoStats] = []
    units = 0
    for start in range(0, len(video_ids), 50):
        batch = video_ids[start : start + 50]
        data = await _get(
            "videos",
            {"part": "snippet,contentDetails,statistics", "id": ",".join(batch), "maxResults": 50},
        )
        units += 1
        for item in data.get("items", []):
            stats, snippet = item.get("statistics") or {}, item["snippet"]
            out.append(
                VideoStats(
                    video_id=item["id"],
                    channel_id=snippet["channelId"],
                    channel_title=snippet.get("channelTitle", ""),
                    title=snippet["title"],
                    published_at=snippet["publishedAt"],
                    duration_s=parse_duration(item["contentDetails"].get("duration", "")),
                    views=_int(stats.get("viewCount")),
                    likes=_int(stats.get("likeCount")),
                    comments=_int(stats.get("commentCount")),
                    url=f"https://www.youtube.com/watch?v={item['id']}",
                )
            )
    return VideoStatsList(videos=out, units_used=units)


async def search(query: str, max_results: int = 10) -> SearchResults:
    """One search.list call (counts toward the 100 searches/day cap)."""
    data = await _get(
        "search",
        {
            "part": "id",
            "q": query,
            "type": "video",
            "maxResults": min(50, max_results),
            "order": "relevance",
        },
    )
    ids = [
        row["id"]["videoId"] for row in data.get("items", []) if row.get("id", {}).get("videoId")
    ]
    return SearchResults(query=query, video_ids=ids)


def main() -> None:
    parser = argparse.ArgumentParser(prog="youtube")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("channel")
    p.add_argument("handle")
    p = sub.add_parser("uploads")
    p.add_argument("playlist_id")
    p.add_argument("--max", type=int, default=50)
    p = sub.add_parser("videos")
    p.add_argument("video_ids", nargs="+")
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--max", type=int, default=10)
    run_cli(
        SOURCE,
        parser,
        {
            "channel": lambda a: channel(a.handle),
            "uploads": lambda a: uploads(a.playlist_id, a.max),
            "videos": lambda a: videos(a.video_ids),
            "search": lambda a: search(a.query, a.max),
        },
    )


async def test_connection() -> tuple[bool, str]:
    """Cheapest authenticated call (1 unit)."""
    try:
        info = await channel("@YouTube")
    except SourceError as e:
        return False, str(e)
    return True, f"connected (resolved {info.name})"


if __name__ == "__main__":
    main()
