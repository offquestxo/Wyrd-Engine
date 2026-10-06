"""Phase 6: dossier integrity checks, rendering, save and export (no network)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, select

from apps.api.db.migrate import migrate_path
from apps.api.db.models import Dossier, Story, StorySource
from apps.api.db.session import make_engine
from apps.api.research import dossier as dmod
from apps.api.research.texts import cap_words, excerpt_in, html_to_text, normalize
from apps.api.sources._http import SourceError

TENK = "https://www.sec.gov/Archives/edgar/data/104599/000119312508093063/d10k.htm"
WIKI = "https://en.wikipedia.org/wiki/Circuit_City"
DEAD = "https://example.com/gone"

# Fixture texts (illustrative, not quotes from the real filings).
TEXTS = {
    TENK: "<html><body><p>Net sales decreased 4.4 percent to $ 11,743,700 thousand in fiscal "
    "2008.</p><p>We operated 682 Superstores at February&nbsp;29, 2008.</p></body></html>",
    WIKI: "<p>On November 10, 2008, Circuit City filed for Chapter 11 bankruptcy protection. "
    "In 2007 the company laid off about 3,400 of its highest-paid store employees.</p>",
}


async def lookup(url: str) -> str:
    if url not in TEXTS:
        raise SourceError("web", "HTTP 404")
    return html_to_text(TEXTS[url])


def make_dossier(**overrides: Any) -> dmod.DossierIn:
    base: dict[str, Any] = {
        "title": "Circuit City",
        "summary": "A retail giant that fell apart.",
        "twist": "It laid off its best salespeople to cut costs.",
        "twist_source": 2,
        "twist_excerpt": "laid off about 3,400 of its highest-paid store employees",
        "timeline": [
            {
                "date": "2008-11-10",
                "event": "Files for Chapter 11",
                "source": 2,
                "excerpt": "On November 10, 2008, Circuit City filed for Chapter 11",
            },
            {  # not in the source: must move to Open Questions
                "date": "2009-01-16",
                "event": "Announces liquidation",
                "source": 2,
                "excerpt": "Circuit City announced it would liquidate all remaining stores",
            },
        ],
        "key_people": [{"name": "Philip Schoonover", "role": "CEO"}],
        "key_numbers": [
            {
                "figure": "$11.7 billion",
                "meaning": "FY2008 net sales",
                "source": 1,
                "excerpt": "Net sales decreased 4.4 percent to $11,743,700 thousand",
            },
            {  # excerpt is real but doesn't contain the figure
                "figure": "$12.4 billion",
                "meaning": "FY2007 net sales",
                "source": 1,
                "excerpt": "Net sales decreased 4.4 percent",
            },
            {  # cited source can't be fetched
                "figure": "1,500 stores",
                "meaning": "Peak store count",
                "source": 3,
                "excerpt": "at its peak it had 1,500 stores",
            },
            {
                "figure": "682",
                "meaning": "Superstores at FY2008 year end",
                "source": 1,
                "excerpt": "We operated 682 Superstores at February 29, 2008.",
            },
        ],
        "story_beats": {
            "rise": "r",
            "peak": "p",
            "cracks": "c",
            "fall": "f",
            "aftermath": "a",
        },
        "hook_ideas": ["h1", "h2", "h3", "h4", "h5"],
        "best_short_angle": "s",
        "best_long_angle": "l",
        "open_questions": ["Why did the board approve the layoffs?"],
        "sources": [
            {"n": 1, "url": TENK, "title": "Circuit City 10-K FY2008", "kind": "10-K filing"},
            {"n": 2, "url": WIKI, "title": "Circuit City — Wikipedia"},
            {"n": 3, "url": DEAD, "title": "Gone page"},
        ],
        "second_opinion_resolutions": [
            {"claim": "liquidation date", "action": "moved_to_open_questions", "note": "no source"}
        ],
    }
    base.update(overrides)
    return dmod.DossierIn.model_validate(base)


@pytest.fixture
def engine(tmp_path: Path) -> Any:
    migrate_path(tmp_path / "r.db")
    engine = make_engine(tmp_path / "r.db")
    with Session(engine) as s:
        s.add(Story(slug="circuit-city", title="Circuit City", status="Researching"))
        s.commit()
    return engine


# ---------------------------------------------------------------------------- text checks
def test_normalize_and_excerpt_matching() -> None:
    text = html_to_text(TEXTS[TENK])
    assert "February 29, 2008" in text  # &nbsp; decoded, tags gone
    assert excerpt_in("net sales decreased 4.4 percent to $11,743,700", text)  # case, $ spacing
    assert excerpt_in("“Net sales decreased” 4.4 percent", "“Net sales decreased” 4.4 percent")
    assert excerpt_in("Net sales decreased 4.4 percent … 682 Superstores at February", text)
    assert not excerpt_in("Net sales increased 4.4 percent", text)
    assert not excerpt_in("Net ... 682", text)  # ellipsis parts must be 3+ words
    assert normalize("It’s — big") == "it's - big"


def test_cap_words() -> None:
    assert cap_words("one two three", 5) == ("one two three", False)
    assert cap_words("one two three four", 2) == ("one two", True)


@pytest.mark.parametrize(
    ("figure", "excerpt", "ok"),
    [
        ("$11.7 billion", "net sales of $11,743,700 thousand", True),  # rounding
        ("$11.74 billion", "net sales of $11,743,700 thousand", True),
        ("$12.4 billion", "net sales of $11,743,700 thousand", False),
        ("34,000 employees", "approximately 34,000 associates", True),
        ("FY2008 revenue $11.7B", "fiscal 2009 revenue of $11.7 billion", True),  # year ignored
        ("2008", "filed in 2009", False),  # only a year: it must match
        ("Chapter 11", "filed for bankruptcy", False),
        ("Liquidation", "liquidated", True),  # nothing numeric to check
    ],
)
def test_figure_supported(figure: str, excerpt: str, ok: bool) -> None:
    assert dmod.figure_supported(figure, excerpt) is ok


def test_primary_domains() -> None:
    domains = ["sec.gov", "web.archive.org", "courtlistener.com"]
    assert dmod.is_primary(TENK, domains)
    assert dmod.is_primary("https://web.archive.org/web/2007/http://circuitcity.com", domains)
    assert not dmod.is_primary(WIKI, domains)
    assert not dmod.is_primary("https://notsec.gov.example.com/x", domains)


# ---------------------------------------------------------------------------- save + export
async def test_save_moves_failed_rows_and_exports(engine: Any, tmp_path: Path) -> None:
    out = tmp_path / "research"
    result = await dmod.save_dossier(
        engine,
        1,
        make_dossier(),
        lookup,
        second_opinion={"flags": [{"claim": "x"}], "resolutions": []},
        research_dir=out,
    )
    # timeline 2 + key numbers 4 + twist 1 = 7 checked; 3 fail (timeline #2, $12.4B, dead source)
    assert result["version"] == 1
    assert result["excerpt_check"] == {
        "passed": 4,
        "failed": 3,
        "truncated": 0,
        "prose_numbers_unverified": 0,
        "support_check": "skipped (no checker configured)",
    }
    assert result["primary_sources"] == 1

    md = (out / "circuit-city" / "dossier.md").read_text()
    facts, unverified = md.split("## Open Questions / Unverified")
    assert "Files for Chapter 11" in facts and "$11.7 billion" in facts and "| 682 |" in facts
    assert "Announces liquidation" not in facts and "$12.4 billion" not in facts
    assert "Announces liquidation — excerpt not found in source [2]" in unverified
    assert "isn't in its excerpt" in unverified and "couldn't read source [3]" in unverified
    assert "Why did the board approve the layoffs?" in unverified  # the researcher's own
    assert "1. [Circuit City 10-K FY2008](" in unverified and "**(primary)**" in unverified
    assert "Excerpt check: 4 of 7 claims verified" in md

    srcs = json.loads((out / "circuit-city" / "sources.json").read_text())
    assert srcs[0]["source_type"] == "primary" and srcs[1]["source_type"] == "secondary"
    assert (srcs[0]["claims_checked"], srcs[0]["claims_verified"]) == (3, 2)

    with Session(engine) as s:
        d = s.exec(select(Dossier)).one()
        assert d.data and len(d.data["key_numbers"]) == 2 and d.checks["failed"] == 3
        assert d.second_opinion == {"flags": [{"claim": "x"}], "resolutions": []}
        added = {r.url: r for r in s.exec(select(StorySource)).all()}
    assert added[TENK].source_type == "primary" and added[TENK].added_by == "researcher"

    again = await dmod.save_dossier(engine, 1, make_dossier(), lookup, research_dir=out)
    assert again["version"] == 2
    listed = dmod.list_dossiers(engine)
    assert len(listed) == 1 and listed[0]["versions"] == [1, 2] and listed[0]["version"] == 2
    v1 = dmod.get_dossier(engine, 1, version=1)
    assert v1 and v1["version"] == 1 and v1["markdown"].startswith("# Circuit City")


async def test_unverified_twist_is_replaced(engine: Any, tmp_path: Path) -> None:
    d = make_dossier(twist_excerpt="something the source never said at all")
    await dmod.save_dossier(engine, 1, d, lookup, research_dir=tmp_path)
    md = (tmp_path / "circuit-city" / "dossier.md").read_text()
    assert "## The Twist\nUnverified: see Open Questions." in md
    assert "Twist: It laid off its best salespeople" in md


async def test_long_excerpts_are_capped_before_checking(engine: Any, tmp_path: Path) -> None:
    sentence = " ".join(f"word{i}" for i in range(60))  # a real 60-word passage

    async def long_lookup(url: str) -> str:
        return f"Intro. {sentence}. Outro." if url == WIKI else await lookup(url)

    d = make_dossier(
        timeline=[{"date": "2008", "event": "Long quote", "source": 2, "excerpt": sentence}]
    )
    result = await dmod.save_dossier(engine, 1, d, long_lookup, research_dir=tmp_path)
    assert result["excerpt_check"]["truncated"] == 1
    with Session(engine) as s:
        saved = s.exec(select(Dossier)).one().data
    assert saved and len(saved["timeline"]) == 1  # a prefix of a real quote still passes
    assert len(saved["timeline"][0]["excerpt"].split()) == 40  # scoring.yaml cap


async def test_prose_numbers_must_come_from_a_cited_source(engine: Any, tmp_path: Path) -> None:
    beats = {
        "rise": "Grew to $11.7 billion in sales",  # 11,743,700 (thousands) in the 10-K: ok
        "peak": "682 Superstores and 3,400 layoffs",  # both in sources: ok
        "cracks": "About 46,000 employees",  # in no source: flagged
        "fall": "f",
        "aftermath": "Filed in 2008",  # years aren't checked
    }
    d = make_dossier(
        story_beats=beats, hook_ideas=["$9.9 billion vanished", "h2", "h3", "h4", "h5"]
    )
    result = await dmod.save_dossier(engine, 1, d, lookup, research_dir=tmp_path)
    assert result["excerpt_check"]["prose_numbers_unverified"] == 2
    assert result["excerpt_check"]["passed"] == 4  # row counts unaffected
    md = (tmp_path / "circuit-city" / "dossier.md").read_text()
    unverified = md.split("## Open Questions / Unverified")[1]
    assert "Story Beats mentions “46,000”" in unverified
    assert "Hook Ideas mentions “$9.9 billion”" not in unverified  # written form excludes "$"
    assert "Hook Ideas mentions “9.9 billion”" in unverified
    assert "11.7 billion" not in unverified and "682" not in unverified
    assert "2 number(s) in the prose weren't found" in md


async def test_support_check_trims_or_moves_overstated_claims(engine: Any, tmp_path: Path) -> None:
    from apps.api.providers.schemas import SupportItem, SupportVerdict

    seen: list[SupportItem] = []

    async def support(items: list[SupportItem]) -> list[SupportVerdict]:
        seen.extend(items)
        out = []
        for item in items:
            if item.claim.startswith("2008-11-10"):  # trim the motive the excerpt doesn't give
                out.append(
                    SupportVerdict(
                        id=item.id,
                        supported=False,
                        unsupported_parts=["after the board lost faith"],
                        trimmed_claim="2008-11-10: Files for Chapter 11",
                    )
                )
            elif item.claim.startswith("682"):  # nothing salvageable
                out.append(
                    SupportVerdict(id=item.id, supported=False, unsupported_parts=["record high"])
                )
            else:
                out.append(SupportVerdict(id=item.id, supported=True))
        return out

    d = make_dossier()
    d.timeline[0].event = "Files for Chapter 11 after the board lost faith"
    d.key_numbers[3].meaning = "Record-high Superstore count"
    result = await dmod.save_dossier(engine, 1, d, lookup, research_dir=tmp_path, support=support)
    # Only rows that passed the excerpt check are sent: timeline 1, $11.7B, 682, twist = 4.
    assert len(seen) == 4 and {i.claim[:4] for i in seen} >= {"2008", "$11.", "682 "}
    check = result["excerpt_check"]
    assert check["support_check"] == "4 checked: 1 trimmed, 1 moved"
    assert (check["passed"], check["failed"]) == (3, 4)
    md = (tmp_path / "circuit-city" / "dossier.md").read_text()
    facts, unverified = md.split("## Open Questions / Unverified")
    assert "**2008-11-10**: Files for Chapter 11 [[2]]" in facts and "board" not in facts
    assert "| 682 |" not in facts
    assert (
        "Trimmed from “2008-11-10: Files for Chapter 11 after the board lost faith”" in unverified
    )
    assert "682 — Record-high Superstore count — excerpt doesn't support: record high" in unverified


async def test_support_check_failure_keeps_rows_and_says_so(engine: Any, tmp_path: Path) -> None:
    from apps.api.providers.base import ProviderError

    async def down(items: list[Any]) -> list[Any]:
        raise ProviderError("groq", "HTTP 503")

    result = await dmod.save_dossier(
        engine, 1, make_dossier(), lookup, research_dir=tmp_path, support=down
    )
    assert result["excerpt_check"]["passed"] == 4
    assert result["excerpt_check"]["support_check"].startswith("unavailable")


def test_spelled_numbers_and_dates() -> None:
    assert dmod.words_to_digits("eighteen months, twenty-three stores, two hundred") == (
        "18 months, 23 stores, 200"
    )
    assert dmod.parse_date("Nov 10, 2008") == dmod.TimelineDate(year=2008, month=11, day=10)
    assert dmod.parse_date("2008-11") == dmod.TimelineDate(year=2008, month=11)
    assert dmod.parse_date("circa 2008") is None
    dates = [dmod.parse_date(x) for x in ("2007-03-28", "2008-11-10", "1949", "2009")]
    known = [d for d in dates if d]
    assert dmod.duration_matches(18, "month", False, known) == (False, "about 19.4 months")
    assert dmod.duration_matches(19, "month", True, known)[0]  # "about 19 months"
    assert dmod.duration_matches(60, "year", False, known)[0]  # 1949 → 2009


async def test_prose_durations_must_match_timeline(engine: Any, tmp_path: Path) -> None:
    timeline = [
        {
            "date": "2007-03-28",
            "event": "Layoffs",
            "source": 2,
            "excerpt": "laid off about 3,400 of its highest-paid store employees",
        },
        {
            "date": "2008-11-10",
            "event": "Files for Chapter 11",
            "source": 2,
            "excerpt": "On November 10, 2008, Circuit City filed for Chapter 11",
        },
    ]
    d = make_dossier(
        timeline=timeline,
        hook_ideas=[
            "Bankrupt eighteen months later",
            "Bankrupt about 19 months later",
            "h3",
            "h4",
            "h5",
        ],
    )
    result = await dmod.save_dossier(engine, 1, d, lookup, research_dir=tmp_path)
    assert result["excerpt_check"]["prose_numbers_unverified"] == 1
    md = (tmp_path / "circuit-city" / "dossier.md").read_text()
    unverified = md.split("## Open Questions / Unverified")[1]
    assert "Hook Ideas says “18 months later”" in unverified and "19.4 months" in unverified
    assert "about 19 months" not in unverified  # matches the Timeline gap


def test_prose_number_parsing() -> None:
    found = {
        w: (v, t) for w, v, t in dmod.prose_numbers("$12.43 billion, 654 stores, in 2008, 3 CEOs")
    }
    assert found["12.43 billion"] == (12.43e9, 0.005e9) and found["654"] == (654.0, 0.5)
    assert "2008" not in found and "3" not in found
    assert dmod.number_in_text(12.43e9, 0.005e9, {12429754.0})  # filing table in thousands
    assert not dmod.number_in_text(12.43e9, 0.005e9, {12529754.0})


def test_duplicate_source_numbers_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        make_dossier(
            sources=[
                {"n": 1, "url": TENK, "title": "a"},
                {"n": 1, "url": WIKI, "title": "b"},
            ]
        )


# ---------------------------------------------------------------------------- MCP tools
from fastmcp import Client  # noqa: E402

from apps.api import mcp_server  # noqa: E402
from apps.api.providers.schemas import DocExtraction, Extract, SecondOpinion  # noqa: E402
from apps.api.research import session as rsession  # noqa: E402
from apps.api.research import tools as rtools  # noqa: E402


class ToolRouter:
    def __init__(self) -> None:
        self.extract_calls: list[dict[str, Any]] = []

    async def extract_from_document(
        self, document: str, question: str, deep: bool = False
    ) -> DocExtraction:
        self.extract_calls.append({"document": document, "question": question, "deep": deep})
        return DocExtraction(
            answer="Sales fell.",
            found=True,
            extracts=[Extract(quote="Net sales decreased 4.4 percent")],
        )

    async def check_support(self, items: list[Any]) -> list[Any]:
        from apps.api.providers.schemas import SupportVerdict

        return [SupportVerdict(id=i.id, supported=True) for i in items]

    async def second_opinion(self, markdown: str) -> SecondOpinion:
        return SecondOpinion(
            flags=[
                {
                    "claim": "liquidation",
                    "issue": "no source",
                    "severity": "high",
                    "suggestion": "move",
                }
            ],
            overall="Mostly sourced.",
        )


@pytest.fixture
def research_env(engine: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    from apps.api.db.models import AgentRun

    with Session(engine) as s:
        s.add(AgentRun(id=77, agent="researcher", status="running"))
        s.commit()
    router = ToolRouter()
    logs: list[tuple[str, str]] = []
    sess = rsession.open_session(
        rsession.ResearchSession(
            run_id=77, story_id=1, depth="standard", log=lambda lvl, msg: logs.append((lvl, msg))
        )
    )
    monkeypatch.setitem(mcp_server._services, "test_run_id", 77)
    monkeypatch.setattr(rtools, "get_router", lambda: router)
    monkeypatch.setattr(rtools, "get_engine", lambda: engine)
    monkeypatch.setattr(rtools, "fetch_text", lookup)
    monkeypatch.setattr(dmod, "RESEARCH_DIR", tmp_path / "research")
    yield {"session": sess, "router": router, "logs": logs, "tmp": tmp_path}
    rsession.close_session(77)


def research_client() -> Client:
    return Client(mcp_server.SERVERS[mcp_server.RESEARCHER])


async def test_researcher_server_only_lists_its_tools() -> None:
    async with research_client() as c:
        names = {t.name for t in await c.list_tools()}
    assert {"source_edgar", "extract_from_document", "second_opinion", "save_dossier"} <= names
    assert "propose_plan" not in names and "get_story" in names
    async with Client(mcp_server.mcp) as c:
        chat_names = {t.name for t in await c.list_tools()}
    assert "save_dossier" not in chat_names and len(chat_names) == 7


async def test_depth_limits_sources_and_known_limits_are_noted(
    research_env: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_data(*a: Any, **k: Any) -> Any:
        raise SourceError("yahoo", "no price data for CCTYQ")

    monkeypatch.setattr(rtools.yahoo, "history", no_data)
    async with research_client() as c:
        with pytest.raises(Exception, match="isn't used at depth 'standard'"):
            await c.call_tool("source_gdelt", {"query": "Circuit City"})  # deep only
        with pytest.raises(Exception, match="no price data"):
            await c.call_tool("source_yahoo", {"action": "history", "ticker": "CCTYQ"})
        with pytest.raises(Exception, match="1770–1963"):
            await c.call_tool(
                "source_loc_newspapers", {"query": "Circuit City", "start_year": 2008}
            )
    notes = research_env["session"].source_notes
    assert any("delisted" in n for n in notes) and any("1963" in n for n in notes)
    assert any("yahoo" in m and "failed" in m for _, m in research_env["logs"])


async def test_extract_keeps_document_for_excerpt_check(research_env: Any) -> None:
    async with research_client() as c:
        out = (
            await c.call_tool("extract_from_document", {"url_or_text": TENK, "question": "Sales?"})
        ).data
    assert out["extracts"][0]["quote"] == "Net sales decreased 4.4 percent"
    assert TENK in research_env["session"].texts  # reused by the excerpt check
    assert research_env["router"].extract_calls[0]["deep"] is False  # standard depth


async def test_interpretation_flags_must_be_resolved_before_saving(research_env: Any) -> None:
    async def opinion(markdown: str) -> SecondOpinion:
        assert "## Story Beats" in markdown  # prose is reviewed too
        return SecondOpinion(
            flags=[
                {
                    "claim": "missing the housing boom",
                    "issue": "cause stated as fact",
                    "severity": "medium",
                    "suggestion": "label",
                    "kind": "interpretation",
                },
                {
                    "claim": "customer service deteriorated",
                    "issue": "no source",
                    "severity": "medium",
                    "suggestion": "label",
                    "kind": "interpretation",
                },
            ],
            overall="ok",
        )

    research_env["router"].second_opinion = opinion
    payload = {"dossier": make_dossier().model_dump()}
    async with research_client() as c:
        review = (await c.call_tool("second_opinion", payload)).data
        assert [f["kind"] for f in review["flags"]] == ["interpretation", "interpretation"]
        with pytest.raises(Exception, match="2 flags, 1 resolutions"):
            await c.call_tool("save_dossier", payload)
        fixed = make_dossier().model_dump()
        fixed["second_opinion_resolutions"] += [
            {
                "claim": "missing the housing boom",
                "action": "labelled_interpretation",
                "note": "Our read: …",
            }
        ]
        saved = (await c.call_tool("save_dossier", {"dossier": fixed})).data
    assert saved["version"] == 1


def test_second_opinion_prompt_covers_prose_interpretation() -> None:
    from apps.api import prompts

    text = prompts.render("second_opinion", output_schema="{}")
    assert "interpretation" in text and "Story Beats" in text and "Our read" in text


async def test_save_requires_second_opinion_then_reports_checks(research_env: Any) -> None:
    payload = {"dossier": make_dossier().model_dump()}
    async with research_client() as c:
        with pytest.raises(Exception, match="second_opinion"):
            await c.call_tool("save_dossier", payload)
        review = (await c.call_tool("second_opinion", payload)).data
        assert review["flags"][0]["severity"] == "high"
        assert (
            review["excerpt_precheck"]["passed"] == 4
            and len(review["excerpt_precheck"]["failed"]) == 3
        )
        saved = (await c.call_tool("save_dossier", payload)).data
    assert saved["excerpt_check"] == {
        "passed": 4,
        "failed": 3,
        "truncated": 0,
        "prose_numbers_unverified": 0,
        "support_check": "4 checked: 0 trimmed, 0 moved",
    }
    assert (research_env["tmp"] / "research" / "circuit-city" / "dossier.md").exists()
    with Session(research_env_engine(research_env)) as s:
        d = s.exec(select(Dossier)).one()
    assert d.run_id == 77
    assert d.second_opinion and d.second_opinion["flags"][0]["claim"] == "liquidation"
    assert d.second_opinion["resolutions"][0]["action"] == "moved_to_open_questions"
    assert research_env["session"].saved[0]["version"] == 1


def research_env_engine(env: Any) -> Any:
    return rtools.get_engine()


# ---------------------------------------------------------------------------- runner
from apps.api.agents import orchestrator as orch  # noqa: E402
from apps.api.agents import researcher  # noqa: E402
from apps.api.db.models import ProviderUsage  # noqa: E402


class RunCtx:
    def __init__(self, run_id: int, params: dict[str, Any]) -> None:
        self.run_id, self.params = run_id, params
        self.logs: list[tuple[str, str]] = []
        self.steps: list[str] = []

    def log(self, level: str, message: str, data: Any = None) -> None:
        self.logs.append((level, message))

    def step(self, name: str, progress: float | None = None) -> None:
        self.steps.append(name)


def test_estimate_and_command_allowlist() -> None:
    est = researcher.estimate({"topic": "Circuit City", "depth": "standard"})
    assert est["claude_turns"] == 40 and est["youtube_units"] == 0 and "edgar" in est["sources"]
    deep = researcher.estimate({"topic": "Circuit City", "depth": "deep"})
    assert deep["claude_turns"] == 70 and deep["youtube_search_calls"] == 2
    cmd = researcher.build_command("claude", 5, "PROMPT", 40, "sonnet", "medium")
    assert cmd[cmd.index("--tools") + 1] == "WebSearch,WebFetch"  # no Bash/Edit/Write/Read
    allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
    assert "mcp__wyrd__save_dossier" in allowed and "mcp__wyrd__propose_plan" not in allowed
    assert not any(t in allowed for t in ("Bash", "Write", "Edit", "Read"))
    agent = json.loads(cmd[cmd.index("--agents") + 1])["researcher"]
    assert agent["maxTurns"] == 40 and agent["prompt"] == "PROMPT"
    assert agent["tools"] == ["mcp__wyrd", "WebSearch", "WebFetch"]  # from .claude/agents/
    mcp = json.loads(cmd[cmd.index("--mcp-config") + 1])["mcpServers"]["wyrd"]
    assert mcp["url"].endswith("/mcp-research/") and mcp["headers"]["x-wyrd-run"] == "5"
    assert "--no-session-persistence" in cmd and cmd[cmd.index("--agent") + 1] == "researcher"


def fake_stream(engine: Any, save: bool = True) -> Any:
    """A Claude stand-in that uses the real researcher MCP tools in-process."""

    async def stream(
        command: Any,
        cwd: Any,
        prompt: str,
        timeout_s: float,
        label: str,
        max_turns: int | None = None,
    ) -> Any:
        payload = {"dossier": make_dossier().model_dump()}
        async with research_client() as c:
            yield orch.TurnEvent("tool", tool="second_opinion", data={"input": {}})
            await c.call_tool("second_opinion", payload)
            if save:
                yield orch.TurnEvent("tool", tool="save_dossier", data={"input": {}})
                await c.call_tool("save_dossier", payload)
        yield orch.TurnEvent("text", text="Saved.")
        yield orch.TurnResult(
            text="Saved.",
            ok=True,
            session_id=None,
            duration_ms=95_000,
            turns=12,
            tokens_in=50_000,
            tokens_out=6_000,
            model="claude-sonnet",
            tools=[],
        )

    return stream


async def test_run_saves_dossier_and_logs_claude_usage(
    research_env: Any, engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(researcher, "get_engine", lambda: engine)
    monkeypatch.setattr(researcher.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(researcher, "workdir", lambda: Path("."))
    monkeypatch.setattr(researcher, "stream_claude", fake_stream(engine))
    rsession.close_session(77)  # the runner opens its own session for its run id
    with Session(engine) as s:
        s.add(Story(slug="inbox-story", title="Inbox story", status="Inbox"))
        s.commit()
    result = await researcher.run(RunCtx(77, {"story_id": 1}))  # type: ignore[arg-type]
    assert result["version"] == 1 and result["excerpt_check"]["failed"] == 3
    assert result["second_opinion"]["flags"][0]["claim"] == "liquidation"
    assert result["second_opinion"]["resolutions"][0]["action"] == "moved_to_open_questions"
    assert result["claude"]["turns"] == 12 and result["claude"]["duration_s"] == 95
    assert "excerpt check 4 passed, 3 moved to Open Questions" in result["summary"]
    with Session(engine) as s:
        usage = s.exec(select(ProviderUsage).where(ProviderUsage.provider == "claude")).one()
    assert (usage.task, usage.turns, usage.latency_ms) == ("researcher", 12, 95_000)
    assert rsession.get_session(77) is None  # closed after the run


async def test_topic_creates_story_and_unsaved_run_fails(
    research_env: Any, engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(researcher, "get_engine", lambda: engine)
    monkeypatch.setattr(researcher.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setattr(researcher, "workdir", lambda: Path("."))
    monkeypatch.setattr(researcher, "stream_claude", fake_stream(engine, save=False))
    rsession.close_session(77)
    with pytest.raises(RuntimeError, match="No dossier saved"):
        await researcher.run(RunCtx(77, {"topic": "Toys R Us"}))  # type: ignore[arg-type]
    with Session(engine) as s:
        story = s.exec(select(Story).where(Story.title == "Toys R Us")).one()
        usage = s.exec(select(ProviderUsage).where(ProviderUsage.provider == "claude")).all()
    assert story.status == "Researching" and len(usage) == 1  # usage logged even on failure


def test_existing_story_moves_to_researching(engine: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(researcher, "get_engine", lambda: engine)
    with Session(engine) as s:
        s.add(Story(slug="x", title="X Corp", status="Inbox"))
        s.add(Story(slug="y", title="Y Corp", status="Scripting"))
        s.commit()
    from apps.api.agents.params import ResearcherParams

    assert researcher.resolve_story(ResearcherParams(topic="x corp")).status == "Researching"
    assert researcher.resolve_story(ResearcherParams(topic="Y Corp")).status == "Scripting"


async def test_stream_stops_at_turn_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_chat import FakeProc

    lines = [
        {
            "type": "system",
            "subtype": "init",
            "session_id": "s",
            "model": "m",
            "mcp_servers": [{"name": "wyrd", "status": "connected"}],
        },
        *[
            {
                "type": "assistant",
                "message": {
                    "id": f"m{i}",
                    "content": [
                        {"type": "tool_use", "name": "mcp__wyrd__source_edgar", "input": {}}
                    ],
                },
            }
            for i in range(5)
        ],
    ]
    procs: list[Any] = []

    async def spawn(*cmd: str, **_: Any) -> Any:
        procs.append(FakeProc(lines))
        return procs[-1]

    monkeypatch.setattr(orch.asyncio, "create_subprocess_exec", spawn)
    out = [
        ev
        async for ev in orch.stream_claude(
            lambda a: ["claude"], Path("."), "go", 60, "t", max_turns=3
        )
    ]
    result = out[-1]
    assert isinstance(result, orch.TurnResult) and not result.ok and procs[0].killed
    assert "turn budget (3 turns)" in (result.error or "") and result.turns == 3
    assert sum(1 for e in out if getattr(e, "kind", "") == "tool") == 4  # stopped on the 4th


async def test_unreadable_links_fail_fast_with_a_note(research_env: Any) -> None:
    async with research_client() as c:
        with pytest.raises(Exception, match="redirect wrappers"):
            await c.call_tool(
                "extract_from_document",
                {"url_or_text": "https://news.google.com/rss/articles/CBMi123", "question": "q"},
            )
    assert research_env["router"].extract_calls == []  # no provider call spent
    assert any("Google News" in n for n in research_env["session"].source_notes)
