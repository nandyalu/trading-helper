"""Shared fixtures.

The daily bar cache sits between every caller and yfinance, so a test that used
to patch ``yfinance`` now has two seams to control: the network fetch and the
cache table. ``fake_bar_cache`` replaces the table with an in-memory dict so a
test never depends on what happens to be cached in the real database, and never
writes to it.
"""
import datetime

import pytest

from backend.services import bars


@pytest.fixture
def fake_bar_cache(monkeypatch):
    """In-memory stand-in for the ``dailybar`` table. Yields the backing store
    so a test can seed or inspect it."""
    store: dict[tuple[str, datetime.date], dict] = {}

    def upsert(ticker, rows):
        for row in rows:
            store[(ticker, row["date"])] = row
        return len(rows)

    def coverage(ticker):
        dates = sorted(date for cached_ticker, date in store if cached_ticker == ticker)
        return (dates[0], dates[-1]) if dates else (None, None)

    def read(ticker, start, end=None):
        return [
            type("Row", (), row)
            for (cached_ticker, date), row in sorted(store.items(), key=lambda kv: kv[0][1])
            if cached_ticker == ticker and date >= start and (end is None or date <= end)
        ]

    monkeypatch.setattr(bars.db, "upsert_daily_bars", upsert)
    monkeypatch.setattr(bars.db, "get_bar_coverage", coverage)
    monkeypatch.setattr(bars.db, "get_daily_bars", read)
    # In-process bookkeeping is module state; a leaked entry would make an
    # unrelated test skip a fetch it expects.
    monkeypatch.setattr(bars, "_last_fetch", {})
    monkeypatch.setattr(bars, "_earliest_attempt", {})
    return store
