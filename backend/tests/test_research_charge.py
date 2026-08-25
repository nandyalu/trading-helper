"""Charging the agent for the analyses it consumes.

Research is free to the agent today, so "what is worth looking at" is not a
decision it makes. Charging makes it one — and makes the question this app
exists to answer honest, because whether the model earns its keep should
include the cost of running the model.

Pure — the store is replaced.
"""
import datetime

import pytest

from backend.services import research


@pytest.fixture
def store(monkeypatch):
    rows = []
    settings = {}

    class Row:
        def __init__(self, id, ticker, amount_usd, charged_at):
            self.id, self.ticker = id, ticker
            self.amount_usd, self.charged_at = amount_usd, charged_at
            self.signal_id = None

    monkeypatch.setattr(research.db, "get_setting", lambda k: settings.get(k))
    monkeypatch.setattr(research.db, "set_setting", lambda k, v: settings.__setitem__(k, v))
    monkeypatch.setattr(research.db, "get_research_charges", lambda: rows)
    monkeypatch.setattr(
        research.db, "record_research_charge",
        lambda ticker, amount_usd, charged_at, note=None: (
            rows.append(Row(len(rows) + 1, ticker, amount_usd, charged_at)) or rows[-1].id
        ),
    )
    return rows


def test_research_is_free_by_default(store):
    """The live deployment has always behaved this way and must keep doing so
    while a model comparison runs next door — a research charge would move the
    agent's cash, and two variables at once make neither result clean."""
    assert research.get_price() == 0.0
    assert research.is_charging() is False
    assert research.charge("GOOG") is None
    assert store == []


def test_setting_a_price_starts_charging(store):
    research.set_price(0.05)

    assert research.charge("GOOG") is not None
    assert research.total_spent() == pytest.approx(0.05)


def test_an_analysis_that_produced_nothing_is_still_charged(store):
    """The work happened either way. Research you paid for and learned nothing
    from is the normal case, not an accounting error."""
    research.set_price(0.05)
    research.charge("DELISTED")

    assert research.total_spent() == pytest.approx(0.05)
    assert store[0].signal_id is None


def test_a_negative_price_is_refused(store):
    with pytest.raises(ValueError, match="cannot be negative"):
        research.set_price(-1)


def test_an_unparseable_price_falls_back_to_free(store, monkeypatch):
    """A bad setting must not start charging an arbitrary amount."""
    monkeypatch.setattr(research.db, "get_setting", lambda k: "not a number")

    assert research.get_price() == 0.0


def test_a_failed_charge_never_undoes_the_analysis(store, monkeypatch):
    """The alternative is a book that thinks it has more money than it does."""
    research.set_price(0.05)
    monkeypatch.setattr(
        research.db, "record_research_charge",
        lambda **kw: (_ for _ in ()).throw(RuntimeError("database is locked")),
    )

    assert research.charge("GOOG") is None  # must not raise


def test_spend_is_grouped_by_the_day_it_happened(store):
    """So the equity curve steps down on the day, rather than smearing the
    cost across the whole span."""
    research.set_price(0.05)
    research.charge("A")
    research.charge("B")
    store[0].charged_at = datetime.datetime(2026, 8, 24, 11, 0)
    store[1].charged_at = datetime.datetime(2026, 8, 25, 11, 0)

    by_day = research.spent_by_day()

    assert by_day[datetime.date(2026, 8, 24)] == pytest.approx(0.05)
    assert by_day[datetime.date(2026, 8, 25)] == pytest.approx(0.05)


def test_nine_analyses_a_day_at_five_cents(store):
    """The arithmetic the plan rests on: $0.05 x 9 x 252 is $113 a year, a
    1.13% hurdle on $10,000 — a real constraint that does not rig the game."""
    research.set_price(0.05)
    for _ in range(9):
        research.charge("X")

    daily = research.total_spent()
    assert daily == pytest.approx(0.45)
    assert daily * 252 / 10_000 * 100 == pytest.approx(1.134, abs=0.01)
