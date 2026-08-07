"""The daily bar cache (backend/services/bars.py).

A completed session never changes, so refetching one is pure waste and pure
rate-limit risk. Before this cache the intraday watchdog pulled roughly a month
of bars per ticker every 15 minutes to read two closes and a volume average,
and the chart, the ATR, and signal grading each refetched overlapping ranges of
the same bars independently.

The cases that matter are the ones where a naive cache silently degrades back
into "fetch every time": a ticker with less history than requested, a market
holiday, and a range the caller widens.
"""
import datetime

import pandas as pd
import pytest

from backend.services import bars

TODAY = datetime.date(2026, 8, 6)  # a Thursday
YESTERDAY = datetime.date(2026, 8, 5)


def _frame(dates: list[datetime.date]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [10.0] * len(dates),
            "High": [12.0] * len(dates),
            "Low": [9.0] * len(dates),
            "Close": [11.0] * len(dates),
            "Volume": [1000.0] * len(dates),
        },
        index=pd.to_datetime([d.isoformat() for d in dates]),
    )


@pytest.fixture
def counting_fetch(monkeypatch):
    """Records every fetch and returns a fixed two-session frame."""
    calls: list[datetime.date] = []
    frame = _frame([datetime.date(2026, 8, 4), YESTERDAY])

    def fetch(ticker, start):
        calls.append(start)
        return frame

    monkeypatch.setattr(bars, "_fetch_history", fetch)
    monkeypatch.setattr(bars, "_todays_bar", lambda ticker, today: None)
    return calls


# --- last_completed_session --------------------------------------------------


@pytest.mark.parametrize(
    "today, expected",
    [
        (datetime.date(2026, 8, 6), datetime.date(2026, 8, 5)),  # Thu -> Wed
        (datetime.date(2026, 8, 10), datetime.date(2026, 8, 7)),  # Mon -> Fri
        (datetime.date(2026, 8, 9), datetime.date(2026, 8, 7)),  # Sun -> Fri
        (datetime.date(2026, 8, 8), datetime.date(2026, 8, 7)),  # Sat -> Fri
    ],
)
def test_last_completed_session_skips_the_weekend(today, expected):
    assert bars.last_completed_session(today) == expected


# --- fetch avoidance ---------------------------------------------------------


def test_second_read_is_served_from_cache(fake_bar_cache, counting_fetch):
    bars.get_bars("NVDA", datetime.date(2026, 8, 1), today=TODAY)
    bars.get_bars("NVDA", datetime.date(2026, 8, 1), today=TODAY)
    assert len(counting_fetch) == 1


def test_a_short_history_does_not_refetch_forever(fake_bar_cache, counting_fetch):
    """The trap: the caller asks for a year, the ticker has two days, so the
    cache looks permanently incomplete. Recording the attempt is what stops it
    re-asking on every single call."""
    for _ in range(5):
        bars.get_bars("NVDA", datetime.date(2020, 1, 1), today=TODAY)
    assert len(counting_fetch) == 1


def test_widening_the_range_fetches_once_more(fake_bar_cache, counting_fetch):
    """A user switching the chart from 90 days to 365 must get the older bars
    now, not after the recheck interval."""
    bars.get_bars("NVDA", datetime.date(2026, 8, 1), today=TODAY)
    bars.get_bars("NVDA", datetime.date(2025, 1, 1), today=TODAY)
    assert len(counting_fetch) == 2
    # ...and then settles again.
    bars.get_bars("NVDA", datetime.date(2025, 1, 1), today=TODAY)
    assert len(counting_fetch) == 2


def test_a_holiday_does_not_refetch_on_every_call(fake_bar_cache, counting_fetch):
    """last_completed_session ignores holidays, so on one the cache always
    looks a day behind. The recheck throttle is what absorbs that."""
    friday = datetime.date(2026, 8, 7)
    for _ in range(5):
        bars.get_bars("NVDA", datetime.date(2026, 8, 1), today=friday)
    assert len(counting_fetch) == 1


def test_an_unknown_ticker_is_not_re_asked_on_every_call(fake_bar_cache, monkeypatch):
    calls = []

    def empty_fetch(ticker, start):
        calls.append(start)
        return pd.DataFrame()

    monkeypatch.setattr(bars, "_fetch_history", empty_fetch)
    monkeypatch.setattr(bars, "_todays_bar", lambda ticker, today: None)
    for _ in range(4):
        assert bars.get_bars("NOTREAL", datetime.date(2026, 8, 1), today=TODAY) == []
    assert len(calls) == 1


def test_a_new_session_is_picked_up(fake_bar_cache, monkeypatch):
    """The throttle must not mask a genuinely new close."""
    monkeypatch.setattr(bars, "_todays_bar", lambda ticker, today: None)
    monkeypatch.setattr(
        bars, "_fetch_history", lambda ticker, start: _frame([datetime.date(2026, 8, 4), YESTERDAY])
    )
    bars.get_bars("NVDA", datetime.date(2026, 8, 1), today=TODAY)

    # Next day, a new session has closed and the throttle has expired.
    monkeypatch.setattr(bars, "_last_fetch", {})
    monkeypatch.setattr(
        bars,
        "_fetch_history",
        lambda ticker, start: _frame([datetime.date(2026, 8, 4), YESTERDAY, TODAY]),
    )
    result = bars.get_bars("NVDA", datetime.date(2026, 8, 1), today=datetime.date(2026, 8, 7))
    assert [bar.date for bar in result][-1] == TODAY.isoformat()


# --- what gets stored --------------------------------------------------------


def test_today_is_never_stored(fake_bar_cache, monkeypatch):
    monkeypatch.setattr(
        bars,
        "_fetch_history",
        lambda ticker, start: _frame([datetime.date(2026, 8, 4), YESTERDAY, TODAY]),
    )
    bars.refresh("NVDA", datetime.date(2026, 8, 1), today=TODAY)
    assert TODAY not in {date for _, date in fake_bar_cache}


def test_todays_bar_is_appended_live_when_asked(fake_bar_cache, monkeypatch):
    from backend.services.positions import OhlcBar

    monkeypatch.setattr(
        bars, "_fetch_history", lambda ticker, start: _frame([datetime.date(2026, 8, 4), YESTERDAY])
    )
    live = OhlcBar(date=TODAY.isoformat(), open=1, high=2, low=0.5, close=1.5, volume=10)
    monkeypatch.setattr(bars, "_todays_bar", lambda ticker, today: live)

    result = bars.get_bars("NVDA", datetime.date(2026, 8, 1), include_today=True, today=TODAY)
    assert result[-1].date == TODAY.isoformat()
    # ...and it still is not written to the cache.
    assert TODAY not in {date for _, date in fake_bar_cache}


def test_a_revised_bar_replaces_the_stored_one(fake_bar_cache, monkeypatch):
    """A bar fetched moments after the close can be revised by the exchange;
    the later fetch is the better one."""
    monkeypatch.setattr(bars, "_fetch_history", lambda ticker, start: _frame([YESTERDAY]))
    bars.refresh("NVDA", datetime.date(2026, 8, 1), today=TODAY)
    assert fake_bar_cache[("NVDA", YESTERDAY)]["close"] == 11.0

    revised = _frame([YESTERDAY])
    revised.loc[revised.index[0], "Close"] = 99.0
    monkeypatch.setattr(bars, "_fetch_history", lambda ticker, start: revised)
    bars.refresh("NVDA", datetime.date(2026, 8, 1), today=TODAY)
    assert fake_bar_cache[("NVDA", YESTERDAY)]["close"] == 99.0
