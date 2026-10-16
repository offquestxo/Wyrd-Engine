"""Thumbnail figures: only from source text; confirmed only by a dossier's Key Numbers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from apps.api import hook_figures as hf
from apps.api import stories
from apps.api.db.migrate import migrate_path
from apps.api.db.models import Dossier
from apps.api.db.session import make_engine
from apps.api.providers.schemas import HookFigure

TEXT = "DoorDash Spent $1.4 Million Trying to Stop Mamdani. Workers get 3,400 back pay."


def test_ground_keeps_figures_from_the_text() -> None:
    assert hf.ground("$1.4 Million", "spent fighting Mamdani", TEXT) == (
        "$1.4 Million",
        "spent fighting Mamdani",
    )
    assert hf.ground("$1.4M", None, TEXT) == ("$1.4M", None)  # same digits, different notation
    assert hf.ground("3400", "workers paid", TEXT)[0] == "3400"  # separators don't matter


@pytest.mark.parametrize("figure", ["$2.5 billion", "100x", "$1.5 Million", "7", "", None, "lots"])
def test_ground_drops_numbers_not_in_the_text(figure: Any) -> None:
    assert hf.ground(figure, "a caption", TEXT) == (None, None)


def test_ground_drops_long_captions_but_keeps_the_figure() -> None:
    assert hf.ground("3,400", "one two three four five six", TEXT) == ("3,400", None)


def test_confirmed_by_key_numbers() -> None:
    rows = [{"figure": "$1.4 million"}, {"figure": "70 million troy ounces"}]
    assert hf.confirmed("$1.4M", rows)
    assert hf.confirmed("70 million", rows)
    assert not hf.confirmed("$61,000", rows)
    assert not hf.confirmed(None, rows) and not hf.confirmed("$1.4M", [])


@pytest.fixture
def engine(tmp_path: Path) -> Any:
    migrate_path(tmp_path / "t.db")
    return make_engine(tmp_path / "t.db")


def test_story_view_marks_figures_confirmed_by_the_latest_dossier(engine: Any) -> None:
    from sqlmodel import Session

    story = stories.create_story(
        engine,
        stories.StoryIn(title="Bre-X", hook_figure="$61,000", hook_caption="of panned gold"),
        added_by="test",
    )
    assert stories.list_stories(engine)[0]["hook_figure_verified"] is False
    with Session(engine) as s:
        s.add(
            Dossier(
                story_id=story.id or 0,
                version=1,
                markdown="x",
                data={"key_numbers": [{"figure": "$61,000"}]},
            )
        )
        s.commit()
    view = stories.list_stories(engine)[0]
    assert view["hook_figure"] == "$61,000" and view["hook_caption"] == "of panned gold"
    assert view["hook_figure_verified"] is True
    assert stories.get_story(engine, story.id or 0)["hook_figure_verified"] is True  # type: ignore[index]


async def test_backfill_keeps_only_grounded_figures(
    engine: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = stories.create_story(
        engine,
        stories.StoryIn(
            title="SEC exposes $15 million alleged scam",
            sources=[stories.SourceIn(url="https://x", excerpt="lured investors")],
        ),
        added_by="test",
    )
    bad = stories.create_story(engine, stories.StoryIn(title="WeWork collapse"), added_by="test")
    proposals = {
        good.id: HookFigure(figure="$15 million", caption="alleged scam"),
        bad.id: HookFigure(figure="$47 billion", caption="valuation"),
    }

    class FakeRouter:
        async def propose_hook_figure(self, text: str) -> HookFigure:
            return proposals[good.id] if "SEC" in text else proposals[bad.id]

    monkeypatch.setattr("apps.api.providers.router.get_router", lambda: FakeRouter())
    report = await hf.backfill(engine)
    by_id = {r["story_id"]: r for r in report}
    assert by_id[good.id]["figure"] == "$15 million"
    assert (
        by_id[bad.id]["figure"] is None and by_id[bad.id]["dropped"] == "$47 billion"
    )  # not in its text
    views = {v["id"]: v for v in stories.list_stories(engine)}
    assert views[good.id]["hook_figure"] == "$15 million" and views[bad.id]["hook_figure"] is None


def test_ground_drops_trivial_digits_and_echo_captions() -> None:
    text = "1 piece of advice changed everything; 40,000 investors lost $15 million"
    assert hf.ground("1", "piece of advice", text) == (None, None)
    assert hf.ground("$15 million", "lost $15 million", text) == ("$15 million", None)
    assert hf.ground("40,000", "investors lost everything", text)[1] == "investors lost everything"


@pytest.mark.parametrize("figure", ["1971", "in 1989", "1990s"])
def test_ground_drops_years(figure: str) -> None:
    assert hf.ground(figure, "founded", f"Founded {figure}; 84,300 employees") == (None, None)
    assert hf.ground("84,300", "employees", f"Founded {figure}; 84,300 employees")[0] == "84,300"


def test_title_exists_is_case_insensitive(engine: Any) -> None:
    stories.create_story(engine, stories.StoryIn(title="Blockbuster (retailer)"), added_by="test")
    assert stories.title_exists(engine, "blockbuster (retailer) ")
    assert not stories.title_exists(engine, "Borders (retailer)")
