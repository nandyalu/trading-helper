"""Unit tests for the pure parts of backend/services/ask.py and backend/services/quotes.py."""
import datetime

from backend.services.ask import build_ask_context, strip_think
from backend.database.models import Signal
from backend.services.quotes import extract_price


def _signal(rationale="Buy it. **Price Target**: 120"):
    return Signal(
        id=1,
        ticker="NVDA",
        signal_date=datetime.date(2026, 7, 1),
        decision="Buy",
        rationale=rationale,
        price_at_signal=100.0,
        evaluation_date=datetime.date(2026, 8, 1),
    )


def test_strip_think_removes_reasoning_blocks():
    raw = "<think>let me reason\nabout this</think>The answer is 42."
    assert strip_think(raw) == "The answer is 42."
    assert strip_think("no blocks here") == "no blocks here"


def test_context_includes_rationale_and_reports_in_order():
    context = build_ask_context(
        _signal(),
        {"market_report": "RSI oversold", "news_report": "Earnings beat", "unknown_key": "ignored"},
    )
    assert "Analysis of NVDA from 2026-07-01" in context
    assert "## Final decision rationale" in context
    assert context.index("Market/technical report") < context.index("News report")
    assert "ignored" not in context


def test_context_truncates_huge_reports():
    context = build_ask_context(_signal(), {"market_report": "x" * 50_000})
    assert len(context) <= 24_000


def test_extract_price_shapes():
    assert extract_price([{"symbol": "AAPL", "price": "333.26"}]) == 333.26
    assert extract_price({"snapshots": [{"last_price": 12.5}]}) == 12.5
    assert extract_price({"data": [{"close": "9.99"}]}) == 9.99
    assert extract_price({"symbol": "AAPL", "price": 101.0}) == 101.0  # bare dict


def test_extract_price_rejects_junk():
    assert extract_price([]) is None
    assert extract_price(None) is None
    assert extract_price([{"symbol": "AAPL"}]) is None
    assert extract_price([{"price": "not-a-number"}]) is None
    assert extract_price([{"price": 0}]) is None  # zero/negative quotes are unusable
    assert extract_price("weird") is None
