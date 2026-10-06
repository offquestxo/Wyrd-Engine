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
    assert result["excerpt_check"] == {"passed": 4, "failed": 3, "truncated": 0}
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


def test_duplicate_source_numbers_rejected() -> None:
    with pytest.raises(ValueError, match="unique"):
        make_dossier(
            sources=[
                {"n": 1, "url": TENK, "title": "a"},
                {"n": 1, "url": WIKI, "title": "b"},
            ]
        )
