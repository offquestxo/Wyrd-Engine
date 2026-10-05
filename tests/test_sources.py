"""Source modules against mocked HTTP (no network). Live checks are in test_live.py."""

from __future__ import annotations

import json
import sys
from typing import Any

import httpx
import pytest
import respx

from apps.api.sources import _http, edgar, gdelt, hackernews, news_rss, wikipedia, youtube
from apps.api.sources._http import SourceError

UA = "wyrd test contact@example.com"


@pytest.fixture(autouse=True)
def fast_pacer(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_wait(self: Any, host: str) -> None:
        return None

    monkeypatch.setattr(_http._HostPacer, "wait", no_wait)
    monkeypatch.setattr(_http._HostPacer, "interval", lambda self, host: 0.0)

    async def no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(_http.asyncio, "sleep", no_sleep)


# ------------------------------------------------------------------ EDGAR
async def test_edgar_requires_user_agent() -> None:
    with pytest.raises(SourceError, match="SEC_USER_AGENT"):
        await edgar.search_companies("Circuit City")


@respx.mock
async def test_edgar_sends_user_agent_and_builds_filing_urls(env: pytest.MonkeyPatch) -> None:
    env.setenv("SEC_USER_AGENT", UA)
    route = respx.get("https://data.sec.gov/submissions/CIK0000104599.json").respond(
        json={
            "filings": {
                "recent": {
                    "form": ["8-K", "10-K"],
                    "filingDate": ["2009-01-01", "2008-04-28"],
                    "reportDate": ["", "2008-02-29"],
                    "accessionNumber": ["0000000000-09-000001", "0001193125-08-093063"],
                    "primaryDocument": ["x.htm", "d10k.htm"],
                    "primaryDocDescription": ["", "FORM 10-K"],
                }
            }
        }
    )
    result = await edgar.filings("104599", forms=["10-K"])
    assert route.calls[0].request.headers["User-Agent"] == UA
    assert [f.url for f in result] == [
        "https://www.sec.gov/Archives/edgar/data/104599/000119312508093063/d10k.htm"
    ]


@respx.mock
async def test_edgar_facts_404_is_explained_not_raised(env: pytest.MonkeyPatch) -> None:
    env.setenv("SEC_USER_AGENT", UA)
    respx.get("https://data.sec.gov/api/xbrl/companyfacts/CIK0000104599.json").respond(404)
    result = await edgar.company_facts("104599")
    assert result.facts == [] and result.note and "XBRL" in result.note


@respx.mock
async def test_edgar_facts_keeps_latest_annual_value(env: pytest.MonkeyPatch) -> None:
    env.setenv("SEC_USER_AGENT", UA)
    row = {"end": "2024-02-03", "fy": 2024, "fp": "FY", "form": "10-K", "accn": "a"}
    respx.get("https://data.sec.gov/api/xbrl/companyfacts/CIK0000764478.json").respond(
        json={
            "entityName": "Best Buy",
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "label": "Revenues",
                        "units": {
                            "USD": [
                                {**row, "val": 1, "filed": "2024-03-01"},
                                {**row, "val": 2, "filed": "2025-03-01"},  # restated later → wins
                                {
                                    **row,
                                    "val": 9,
                                    "fp": "Q3",
                                    "form": "10-Q",
                                    "filed": "2023-12-01",
                                },  # quarterly → dropped
                            ]
                        },
                    }
                }
            },
        }
    )
    result = await edgar.company_facts("764478", ["Revenues"])
    assert [(f.value, f.filed) for f in result.facts] == [(2.0, "2025-03-01")]


# ------------------------------------------------------------------ retries / errors
@respx.mock
async def test_retries_5xx_then_succeeds() -> None:
    route = respx.get("https://hn.algolia.com/api/v1/search").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(
                200,
                json={
                    "hits": [
                        {
                            "objectID": "1",
                            "title": "Circuit City",
                            "url": None,
                            "points": 5,
                            "num_comments": 2,
                            "created_at_i": 1241527262,
                        }
                    ]
                },
            ),
        ]
    )
    items = await hackernews.search("Circuit City")
    assert route.call_count == 2
    assert items[0].url == "https://news.ycombinator.com/item?id=1"


@respx.mock
async def test_4xx_raises_source_error_without_retry() -> None:
    route = respx.get("https://hn.algolia.com/api/v1/search").respond(400, text="bad")
    with pytest.raises(SourceError, match="HTTP 400"):
        await hackernews.search("x")
    assert route.call_count == 1


@respx.mock
async def test_gdelt_plain_text_error_becomes_source_error() -> None:
    respx.get(gdelt.API).respond(
        200,
        text="Please limit requests to one every 5 seconds",
        headers={"content-type": "text/html"},
    )
    with pytest.raises(SourceError, match="limit requests"):
        await gdelt.search("Circuit City")


@respx.mock
async def test_gdelt_quotes_multiword_queries() -> None:
    route = respx.get(gdelt.API).respond(json={"articles": []})
    await gdelt.search("Circuit City")
    assert route.calls[0].request.url.params["query"] == '"Circuit City" sourcelang:english'


# ------------------------------------------------------------------ feeds / wiki
RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Circuit City &amp; the fall</title><link>https://example.com/a</link>
<pubDate>Mon, 10 Nov 2008 12:00:00 GMT</pubDate>
<description>&lt;b&gt;Bankrupt&lt;/b&gt;&amp;nbsp;today</description>
<source url="https://wsj.com">WSJ</source></item></channel></rss>"""


@respx.mock
async def test_google_news_rss_normalizes_items() -> None:
    respx.get(news_rss.GOOGLE_NEWS).respond(200, text=RSS)
    [item] = await news_rss.google_news("Circuit City")
    assert item.title == "Circuit City & the fall"
    assert item.source == "WSJ"
    assert item.published_at == "2008-11-10T12:00:00+00:00"
    assert item.snippet == "Bankrupt today"


@respx.mock
async def test_wikipedia_pageviews_sums_days() -> None:
    respx.get(url__startswith=wikipedia.PAGEVIEWS).respond(
        json={"items": [{"views": 10}, {"views": 20}]}
    )
    result = await wikipedia.pageviews("Circuit City", days=2)
    assert (result.total, result.daily_average) == (30, 15.0)


# ------------------------------------------------------------------ YouTube
@pytest.mark.parametrize(
    ("iso", "seconds"),
    [("PT59S", 59), ("PT3M", 180), ("PT1H2M3S", 3723), ("P1DT1S", 86401), ("", 0)],
)
def test_parse_duration(iso: str, seconds: int) -> None:
    assert youtube.parse_duration(iso) == seconds


@respx.mock
async def test_youtube_videos_batches_by_50_and_counts_units(env: pytest.MonkeyPatch) -> None:
    env.setenv("YOUTUBE_API_KEY", "test-key")

    def reply(request: httpx.Request) -> httpx.Response:
        ids = request.url.params["id"].split(",")
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": vid,
                        "snippet": {
                            "channelId": "c",
                            "title": vid,
                            "publishedAt": "2024-01-01T00:00:00Z",
                        },
                        "contentDetails": {"duration": "PT2M"},
                        "statistics": {"viewCount": "100"},
                    }
                    for vid in ids
                ]
            },
        )

    respx.get(f"{youtube.API}/videos").mock(side_effect=reply)
    result = await youtube.videos([f"v{i}" for i in range(120)])
    assert result.units_used == 3 and len(result.videos) == 120
    assert result.videos[0].duration_s == 120 and result.videos[0].views == 100


async def test_youtube_without_key_fails_cleanly() -> None:
    with pytest.raises(SourceError, match="YOUTUBE_API_KEY"):
        await youtube.channel("@companyman")


# ------------------------------------------------------------------ CLI contract
@respx.mock
def test_cli_prints_json_envelope(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    respx.get("https://hn.algolia.com/api/v1/search").respond(json={"hits": []})
    monkeypatch.setattr(sys, "argv", ["hackernews", "search", "Circuit City"])
    with pytest.raises(SystemExit) as exit_info:
        hackernews.main()
    out = json.loads(capsys.readouterr().out)
    assert exit_info.value.code == 0
    assert out == {"source": "hackernews", "command": "search", "ok": True, "data": []}


def test_cli_reports_errors_as_json(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["youtube", "channel", "@companyman"])
    with pytest.raises(SystemExit) as exit_info:
        youtube.main()
    out = json.loads(capsys.readouterr().out)
    assert exit_info.value.code == 1 and out["ok"] is False
