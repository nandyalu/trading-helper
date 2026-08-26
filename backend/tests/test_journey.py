"""Turning the book into a story.

The dashboard shows a snapshot, which is data. The interesting thing about an
experiment is its arc, and nobody can read an arc off a table of trades.

Pure — the stores are replaced.
"""
import datetime

import pytest

from backend.services import journey


class Lot:
    def __init__(self, ticker, qty, entry, entry_day, exit=None, exit_day=None, pnl=None, held=0):
        self.ticker, self.quantity, self.entry = ticker, qty, entry
        self.entry_at = datetime.datetime.fromisoformat(f"{entry_day}T14:00")
        self.exit = exit
        self.exit_at = datetime.datetime.fromisoformat(f"{exit_day}T14:00") if exit_day else None
        self.pnl, self.held_days = pnl, held


class Point:
    def __init__(self, date, equity):
        self.date, self.equity = datetime.date.fromisoformat(date), equity


class Run:
    def __init__(self, day, reasoning="", skipped=None):
        self.ran_at = datetime.datetime.fromisoformat(f"{day}T13:35")
        self.reasoning, self.skipped = reasoning, skipped


@pytest.fixture
def data(monkeypatch):
    state = {"lots": [], "runs": [], "charges": {}, "curve": []}
    monkeypatch.setattr(journey.agent_book, "trade_history", lambda: state["lots"])
    monkeypatch.setattr(journey.agent_book, "equity_curve", lambda: state["curve"])
    monkeypatch.setattr(journey.db, "get_agent_runs", lambda: state["runs"])
    monkeypatch.setattr(journey.research, "spent_by_day", lambda: state["charges"])
    return state


def test_a_day_carries_what_happened_and_why(data):
    """The agent's own words, not a paraphrase — a summary here would be this
    module's opinion of a decision it did not make."""
    data["lots"] = [Lot("NVDA", 3, 100.0, "2026-08-26")]
    data["runs"] = [Run("2026-08-26", reasoning="NVDA had the best expected value.")]
    data["curve"] = [Point("2026-08-26", 10_050.0)]

    days = journey.build(budget=10_000)

    assert len(days) == 1
    assert "bought 3 NVDA at $100.00" in days[0].opened[0]
    assert days[0].reasoning == "NVDA had the best expected value."
    assert days[0].return_pct == pytest.approx(0.5)


def test_the_first_trade_and_first_close_are_named(data):
    data["lots"] = [
        Lot("NVDA", 3, 100.0, "2026-08-26", exit=110.0, exit_day="2026-08-28", pnl=30.0, held=2),
    ]

    days = journey.build(budget=10_000)

    kinds = [m.kind for d in days for m in d.milestones]
    assert "first-trade" in kinds
    assert "first-close" in kinds
    assert "first-win" in kinds


def test_a_losing_first_close_is_named_a_loss(data):
    data["lots"] = [
        Lot("NOK", 1, 10.0, "2026-08-26", exit=9.0, exit_day="2026-08-27", pnl=-1.0, held=1),
    ]

    days = journey.build(budget=10_000)

    kinds = [m.kind for d in days for m in d.milestones]
    assert "first-loss" in kinds
    assert "first-win" not in kinds


def test_a_drawdown_is_named_once_not_every_day(data):
    """Otherwise a long slide litters the story with the same sentence."""
    data["curve"] = [
        Point("2026-08-26", 11_000.0),
        Point("2026-08-27", 10_000.0),
        Point("2026-08-28", 9_900.0),
        Point("2026-08-29", 9_800.0),
    ]

    days = journey.build(budget=10_000)

    drawdowns = [m for d in days for m in d.milestones if m.kind == "drawdown"]
    assert len(drawdowns) == 1


def test_going_back_above_the_starting_balance_is_named(data):
    data["curve"] = [
        Point("2026-08-26", 9_500.0),
        Point("2026-08-27", 10_400.0),
    ]

    days = journey.build(budget=10_000)

    assert any(m.kind == "above-water" for d in days for m in d.milestones)


def test_a_new_high_while_still_underwater_is_not_a_recovery(data):
    """A smaller loss is not a milestone."""
    data["curve"] = [Point("2026-08-26", 9_000.0), Point("2026-08-27", 9_500.0)]

    days = journey.build(budget=10_000)

    assert not any(m.kind == "above-water" for d in days for m in d.milestones)


def test_quiet_days_are_collapsed_in_the_document(data):
    """Six entries reading "nothing happened" bury the day something did, and
    "it waited six days" is the more truthful sentence anyway."""
    data["curve"] = [Point(f"2026-08-{d}", 10_000.0) for d in range(10, 16)]

    text = journey.to_markdown(journey.build(budget=10_000))

    assert "2026-08-10 to 2026-08-15" in text
    assert text.count("nothing bought or sold") == 1


def test_a_day_that_never_ran_says_so(data):
    data["runs"] = [Run("2026-08-26", skipped="The trading agent is switched off.")]

    days = journey.build(budget=10_000)

    assert days[0].skipped == "The trading agent is switched off."


def test_the_last_pass_of_a_day_wins(data):
    """An intraday trigger that re-decided is a better account of the day than
    the morning batch it superseded."""
    data["runs"] = [
        Run("2026-08-26", skipped="The US market is closed."),
        Run("2026-08-26", reasoning="Bought the dip."),
    ]

    days = journey.build(budget=10_000)

    assert days[0].reasoning == "Bought the dip."
    assert days[0].skipped is None


def test_an_empty_book_produces_a_document_rather_than_a_crash(data):
    assert "Nothing has happened yet" in journey.to_markdown(journey.build(budget=10_000))


def test_tickers_keep_their_case(data):
    """str.capitalize() lowercases everything after the first letter, which
    turns GOOG into goog."""
    data["lots"] = [Lot("GOOG", 2, 343.66, "2026-08-26")]

    text = journey.to_markdown(journey.build(budget=10_000))

    assert "GOOG" in text
    assert "goog" not in text


# --- one file per month, under a folder per year -------------------------------


def test_a_file_is_written_per_month_under_its_year(data, tmp_path):
    data["curve"] = [Point("2026-07-30", 10_000.0), Point("2026-08-03", 10_100.0)]

    written = journey.write_month_files(root=str(tmp_path), budget=10_000)

    assert (tmp_path / "2026" / "07-July.md").exists()
    assert (tmp_path / "2026" / "08-August.md").exists()
    assert len(written) == 2


def test_a_month_file_opens_with_the_month_in_numbers(data, tmp_path):
    """A post that opens on the 3rd and ends on the 28th tells a reader
    nothing about whether the month went well."""
    data["lots"] = [
        journey_lot := Lot("NVDA", 3, 100.0, "2026-08-03", exit=110.0, exit_day="2026-08-10",
                           pnl=30.0, held=7),
    ]
    data["curve"] = [Point("2026-08-03", 10_000.0), Point("2026-08-31", 10_300.0)]
    data["charges"] = {datetime.date(2026, 8, 3): 0.45}

    journey.write_month_files(root=str(tmp_path), budget=10_000)
    text = (tmp_path / "2026" / "08-August.md").read_text()

    assert "The analyst's journey — August 2026" in text
    assert "**1** position(s) opened, **1** closed" in text
    assert "$0.45** spent on research" in text
    assert "+3.0% over the month" in text


def test_rewriting_a_month_does_not_duplicate_it(data, tmp_path):
    """Appending would double every day on a re-run. The file is derived; the
    book is the source."""
    data["lots"] = [Lot("NVDA", 3, 100.0, "2026-08-03")]
    data["curve"] = [Point("2026-08-03", 10_000.0)]

    journey.write_month_files(root=str(tmp_path), budget=10_000)
    journey.write_month_files(root=str(tmp_path), budget=10_000)
    text = (tmp_path / "2026" / "08-August.md").read_text()

    assert text.count("Bought 3 NVDA") == 1


def test_the_file_says_it_is_generated(data, tmp_path):
    """A generated file that looks hand-written invites someone to edit it and
    lose the work."""
    data["curve"] = [Point("2026-08-03", 10_000.0)]

    journey.write_month_files(root=str(tmp_path), budget=10_000)
    text = (tmp_path / "2026" / "08-August.md").read_text()

    assert "Generated" in text
    assert "JOURNEY.md" in text


def test_an_unwritable_folder_does_not_raise(data, monkeypatch, tmp_path):
    """Failing to write the story must not fail the job that asked for it."""
    data["curve"] = [Point("2026-08-03", 10_000.0)]
    monkeypatch.setattr(
        journey.os, "makedirs", lambda *a, **k: (_ for _ in ()).throw(OSError("read-only"))
    )

    assert journey.write_month_files(root=str(tmp_path), budget=10_000) == []


def test_an_empty_book_writes_nothing(data, tmp_path):
    assert journey.write_month_files(root=str(tmp_path), budget=10_000) == []
    assert not (tmp_path / "2026").exists()
