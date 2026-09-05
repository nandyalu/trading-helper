"""The in-progress-session bar.

While a US session is open — and for a window before it — yfinance appends a
row for that day carrying a volume but NaN prices. Every reader here takes
``.iloc[-1]``, so the NaN propagated silently rather than raising: a NaN price
was cached as the current price, a NaN close was written to a graded signal,
and NaN compares false against every threshold, so a Buy that actually won was
recorded as a loss. It reaches JSON as ``null``, not as an error, which is why
it went unnoticed until a chart refused to draw.
"""
import datetime

import pandas as pd
import pytest

from backend.services import bars, positions, watchdog
from backend.services.positions import drop_incomplete_bars


def _frame(rows):
    """rows: (date, open, high, low, close, volume)."""
    return pd.DataFrame(
        [
            {"Open": o, "High": h, "Low": lo, "Close": c, "Volume": v}
            for _, o, h, lo, c, v in rows
        ],
        index=pd.DatetimeIndex([pd.Timestamp(r[0]) for r in rows]),
    )


COMPLETE = ("2026-08-04", 100.0, 105.0, 99.0, 104.0, 1_000_000)
ALSO_COMPLETE = ("2026-08-05", 104.0, 108.0, 103.0, 107.0, 1_100_000)
# What yfinance actually returned for NVDA: volume present, prices absent.
IN_PROGRESS = ("2026-08-06", float("nan"), float("nan"), float("nan"), float("nan"), 156_378_175)


def _recent(offset_days: int) -> str:
    """A date close to today, as YYYY-MM-DD.

    **Two tests below read through code that filters bars by age**, so a fixed
    date passes for a few weeks and then fails for good. Both did: they were
    written with August dates and started failing in September, and the failure
    said "the history is empty" rather than "your fixture expired".

    The tests that call ``drop_incomplete_bars`` directly keep the fixed dates.
    That function has no clock in it, so a real date is clearer there.
    """
    return (datetime.date.today() - datetime.timedelta(days=offset_days)).isoformat()


def test_drops_the_incomplete_row():
    result = drop_incomplete_bars(_frame([COMPLETE, ALSO_COMPLETE, IN_PROGRESS]))
    assert len(result) == 2
    assert result.index[-1].date() == datetime.date(2026, 8, 5)


def test_keeps_complete_rows_untouched():
    frame = _frame([COMPLETE, ALSO_COMPLETE])
    assert len(drop_incomplete_bars(frame)) == 2


def test_empty_frame_passes_through():
    frame = _frame([])
    assert drop_incomplete_bars(frame).empty


def test_only_checks_requested_columns():
    # A missing Open must not disqualify a row when the caller only reads Close.
    partial = ("2026-08-06", float("nan"), 108.0, 103.0, 107.0, 900_000)
    frame = _frame([COMPLETE, partial])
    assert len(drop_incomplete_bars(frame, ("Close",))) == 2
    assert len(drop_incomplete_bars(frame, ("Open", "Close"))) == 1


# These three exercise the whole path now: the fetch happens inside
# bars._fetch_history, which is where drop_incomplete_bars is applied, so
# patching bars.yf_retry keeps the NaN-dropping under test rather than stubbing
# past it.


def test_price_window_never_grades_on_a_nan_close(monkeypatch, fake_bar_cache):
    """This is the one that corrupted the scorecard: last_close became NaN, so
    a graded signal stored NaN and its pass/fail came out wrong."""
    frame = _frame([COMPLETE, ALSO_COMPLETE, IN_PROGRESS])
    monkeypatch.setattr(bars, "yf_retry", lambda fn: frame)
    monkeypatch.setattr(bars.yf, "Ticker", lambda ticker: None)

    window = positions.get_price_window("NVDA", datetime.date(2026, 8, 1))
    assert window is not None
    assert window.last_close == pytest.approx(107.0)
    assert window.first_close == pytest.approx(104.0)
    assert window.high == pytest.approx(108.0)
    assert window.low == pytest.approx(99.0)


def test_price_history_drops_the_unchartable_bar(monkeypatch, fake_bar_cache):
    older, newer, today = _recent(3), _recent(2), _recent(1)
    frame = _frame([
        (older, *COMPLETE[1:]),
        (newer, *ALSO_COMPLETE[1:]),
        (today, *IN_PROGRESS[1:]),
    ])
    monkeypatch.setattr(bars, "yf_retry", lambda fn: frame)
    monkeypatch.setattr(bars.yf, "Ticker", lambda ticker: None)

    history = positions.get_price_history("NVDA", days=30)
    assert [bar.date for bar in history] == [older, newer]


def test_watchdog_skips_rather_than_alerting_on_a_nan_price(monkeypatch, fake_bar_cache):
    """Dropping the row leaves last_bar_date on the previous session, which the
    caller's freshness check treats as "no fresh bar" — quiet, not wrong."""
    older, newer, today = _recent(3), _recent(2), _recent(1)
    frame = _frame([
        (older, *COMPLETE[1:]),
        (newer, *ALSO_COMPLETE[1:]),
        (today, *IN_PROGRESS[1:]),
    ])
    monkeypatch.setattr(bars, "yf_retry", lambda fn: frame)
    monkeypatch.setattr(bars.yf, "Ticker", lambda ticker: None)
    monkeypatch.setattr(watchdog.db, "set_cached_price", lambda *a, **k: None)

    snapshot = watchdog.get_daily_snapshot("NVDA")
    assert snapshot is not None
    assert snapshot.price == pytest.approx(107.0)
    assert snapshot.last_bar_date == datetime.date.fromisoformat(newer)


def test_the_in_progress_bar_is_never_cached(monkeypatch, fake_bar_cache):
    """Caching it would freeze a mid-session snapshot and serve it as a close
    once the next reader arrives."""
    frame = _frame([COMPLETE, ALSO_COMPLETE, IN_PROGRESS])
    monkeypatch.setattr(bars, "yf_retry", lambda fn: frame)
    monkeypatch.setattr(bars.yf, "Ticker", lambda ticker: None)

    bars.refresh("NVDA", datetime.date(2026, 8, 1), today=datetime.date(2026, 8, 6))
    cached_dates = sorted(date for _, date in fake_bar_cache)
    assert datetime.date(2026, 8, 6) not in cached_dates
    assert cached_dates == [datetime.date(2026, 8, 4), datetime.date(2026, 8, 5)]
