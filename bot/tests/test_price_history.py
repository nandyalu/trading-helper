"""Unit tests for get_price_history() (bot/positions.py) — the full OHLCV
series used for charts, as opposed to get_price_window()'s 4-scalar summary
used for signal grading."""
import pandas as pd

from bot import positions


class _FakeTicker:
    def __init__(self, frame):
        self._frame = frame

    def history(self, **kwargs):
        return self._frame


def test_get_price_history_serializes_full_frame(monkeypatch):
    frame = pd.DataFrame(
        {
            "Open": [10.0, 11.0],
            "High": [12.0, 13.0],
            "Low": [9.0, 10.0],
            "Close": [11.0, 12.0],
            "Volume": [1000.0, 1500.0],
        },
        index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
    )
    monkeypatch.setattr(positions.yf, "Ticker", lambda ticker: _FakeTicker(frame))

    bars = positions.get_price_history("NVDA", days=30)
    assert len(bars) == 2
    assert bars[0].date == "2026-01-01"
    assert bars[0].open == 10.0
    assert bars[0].high == 12.0
    assert bars[0].low == 9.0
    assert bars[0].close == 11.0
    assert bars[0].volume == 1000.0
    assert bars[1].date == "2026-01-02"


def test_get_price_history_empty_frame_returns_empty_list(monkeypatch):
    monkeypatch.setattr(positions.yf, "Ticker", lambda ticker: _FakeTicker(pd.DataFrame()))
    assert positions.get_price_history("ZZZ") == []


def test_get_price_history_exception_returns_empty_list(monkeypatch):
    def _raise(ticker):
        raise ConnectionError("boom")

    monkeypatch.setattr(positions.yf, "Ticker", _raise)
    assert positions.get_price_history("ZZZ") == []
