"""Shared fixtures.

The daily bar cache sits between every caller and yfinance, so a test that used
to patch ``yfinance`` now has two seams to control: the network fetch and the
cache table. ``fake_bar_cache`` replaces the table with an in-memory dict so a
test never depends on what happens to be cached in the real database, and never
writes to it.
"""
import datetime

import pytest

from backend.database.models import TickerStatus
from backend.services import bars, listings


@pytest.fixture(autouse=True)
def isolated_ticker_status(monkeypatch):
    """Keep ticker status in memory for every test.

    Autouse and unconditional, because this state is written from deep inside
    the fetch path — bars.refresh records whether a ticker still trades — so a
    test that never mentions listings can still persist a row. One did: a
    "NOTREAL" symbol got marked inactive in the developer's real database, and
    the next run of that same test saw it, skipped the fetch it was asserting
    on, and failed. A test must not be able to reach the real database at all.
    """
    store: dict[str, TickerStatus] = {}

    def get_status(ticker):
        return store.get(ticker)

    def set_status(ticker, inactive=None, reason=None, last_bar_date=None, manual=None):
        row = store.setdefault(ticker, TickerStatus(ticker=ticker))
        if inactive is not None:
            row.inactive = inactive
            row.reason = reason
        if last_bar_date is not None:
            row.last_bar_date = last_bar_date
        if manual is not None:
            row.manual = manual
        row.checked_at = datetime.datetime.now(datetime.timezone.utc)

    def inactive_rows():
        return [row for row in store.values() if row.inactive]

    monkeypatch.setattr(listings.db, "get_ticker_status", get_status)
    monkeypatch.setattr(listings.db, "set_ticker_status", set_status)
    monkeypatch.setattr(listings.db, "get_inactive_tickers", inactive_rows)
    return store


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


@pytest.fixture(autouse=True)
def never_reach_the_live_broker(monkeypatch):
    """Fail any test that would send an order to Webull.

    On 2026-08-27 a test run placed real bracket orders on the sandbox account
    for ``AAA`` — the fixture ticker — at a $10.05 limit, which is the $10.00
    fixture price with ``ENTRY_LIMIT_BUFFER_PCT`` applied. They sat unfilled
    until the market closed and Webull cancelled them, which arrived as a
    pile of cancellation notices hours later. Nothing in the app recorded
    them, because the app never placed them: the suite did.

    The account is a sandbox, so the money was never real. What was real is
    that a test reached the internet and put an order on a broker, and the
    only reason anyone noticed was the notifications.

    Patching at ``get_api_client`` covers every path at once — placing,
    cancelling, quotes, positions, order history — so a new test cannot open a
    route this fixture does not know about. A test that genuinely needs broker
    behaviour must patch the specific function it needs, which is what every
    existing one already does.
    """
    def refuse(*args, **kwargs):
        raise AssertionError(
            "This test tried to reach the live Webull API. Tests must never "
            "place, cancel, or read real orders — patch the broker function "
            "the test needs instead. See never_reach_the_live_broker."
        )

    for module in ("backend.services.quotes", "backend.services.broker",
                   "backend.services.sandbox_broker"):
        try:
            monkeypatch.setattr(f"{module}.get_api_client", refuse, raising=False)
        except Exception:
            pass
