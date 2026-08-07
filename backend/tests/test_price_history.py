"""Unit tests for get_price_history() (backend/services/positions.py) — the full OHLCV
series used for charts, as opposed to get_price_window()'s 4-scalar summary
used for signal grading.

Both now read through the daily bar cache, so these patch bars._fetch_history —
the one place the app talks to yfinance — rather than yfinance itself. Bar dates
are relative to today so the tests do not need to freeze the clock. The
``fake_bar_cache`` fixture lives in conftest.py.
"""
import datetime

import pandas as pd
import pytest

from backend.services import bars, positions

TODAY = datetime.date.today()
DAY_ONE = TODAY - datetime.timedelta(days=8)
DAY_TWO = TODAY - datetime.timedelta(days=7)

FRAME = pd.DataFrame(
    {
        "Open": [10.0, 11.0],
        "High": [12.0, 13.0],
        "Low": [9.0, 10.0],
        "Close": [11.0, 12.0],
        "Volume": [1000.0, 1500.0],
    },
    index=pd.to_datetime([DAY_ONE.isoformat(), DAY_TWO.isoformat()]),
)


@pytest.fixture(autouse=True)
def _no_live_today_bar(monkeypatch):
    """Today's bar is a separate live call; these tests cover the cached part."""
    monkeypatch.setattr(bars, "_todays_bar", lambda ticker, today: None)


def test_serializes_full_frame(monkeypatch, fake_bar_cache):
    monkeypatch.setattr(bars, "_fetch_history", lambda ticker, start: FRAME)

    result = positions.get_price_history("NVDA", days=30)
    assert len(result) == 2
    assert result[0].date == DAY_ONE.isoformat()
    assert result[0].open == 10.0
    assert result[0].high == 12.0
    assert result[0].low == 9.0
    assert result[0].close == 11.0
    assert result[0].volume == 1000.0
    assert result[1].date == DAY_TWO.isoformat()


def test_empty_frame_returns_empty_list(monkeypatch, fake_bar_cache):
    monkeypatch.setattr(bars, "_fetch_history", lambda ticker, start: pd.DataFrame())
    assert positions.get_price_history("ZZZ") == []


def test_failed_fetch_returns_empty_list(monkeypatch, fake_bar_cache):
    # _fetch_history swallows the network error and reports None; nothing
    # downstream should raise.
    monkeypatch.setattr(bars, "_fetch_history", lambda ticker, start: None)
    assert positions.get_price_history("ZZZ") == []


def test_a_second_call_does_not_refetch(monkeypatch, fake_bar_cache):
    """The whole point of the cache: past sessions are fetched once."""
    calls = []

    def counting_fetch(ticker, start):
        calls.append(ticker)
        return FRAME

    monkeypatch.setattr(bars, "_fetch_history", counting_fetch)
    positions.get_price_history("NVDA", days=30)
    positions.get_price_history("NVDA", days=30)
    assert len(calls) == 1
