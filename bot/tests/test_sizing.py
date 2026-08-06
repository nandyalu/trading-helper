"""Unit tests for the pure ATR/sizing math in bot/sizing.py."""
import pytest

from bot.sizing import SizingSuggestion, compute_atr, format_sizing_field, suggest_position


def test_atr_simple_case():
    # Constant $2 daily range, no gaps: ATR == 2.
    highs = [101.0] * 20
    lows = [99.0] * 20
    closes = [100.0] * 20
    assert compute_atr(highs, lows, closes) == pytest.approx(2.0)


def test_atr_uses_gap_over_range():
    # Day 2 gaps up: TR = max(1, |h-prev_close|) = 10.
    highs = [101.0, 110.0]
    lows = [99.0, 109.0]
    closes = [100.0, 109.5]
    assert compute_atr(highs, lows, closes, period=14) == pytest.approx(10.0)


def test_atr_needs_two_bars():
    assert compute_atr([100.0], [99.0], [99.5]) is None
    assert compute_atr([], [], []) is None
    assert compute_atr([1.0, 2.0], [1.0], [1.0, 2.0]) is None  # mismatched lengths


def test_suggestion_math():
    # $650 entry, ATR $10 → stop $630; 1% of $50k = $500 risk → 25 shares.
    suggestion = suggest_position(price=650.0, atr=10.0, equity=50_000.0, risk_pct=1.0)
    assert suggestion.stop == pytest.approx(630.0)
    assert suggestion.shares == pytest.approx(25.0)
    assert suggestion.risk_dollars == pytest.approx(500.0)
    assert suggestion.capped is False


def test_suggestion_caps_at_full_equity():
    # Tiny ATR would suggest a position bigger than the account.
    suggestion = suggest_position(price=100.0, atr=0.1, equity=10_000.0, risk_pct=1.0)
    assert suggestion.capped is True
    assert suggestion.shares == pytest.approx(100.0)  # 10k / 100


def test_no_equity_gives_stop_only():
    suggestion = suggest_position(price=100.0, atr=3.0, equity=None)
    assert suggestion.stop == pytest.approx(94.0)
    assert suggestion.shares is None
    text = format_sizing_field(suggestion, risk_pct=1.0, equity=None)
    assert "Stop: $94.00" in text
    assert "/risk" in text


def test_huge_atr_rejected():
    assert suggest_position(price=10.0, atr=6.0, equity=1000.0) is None  # stop would be < 0
    assert suggest_position(price=0.0, atr=1.0, equity=1000.0) is None


def test_field_text_with_equity():
    suggestion = SizingSuggestion(price=650.0, atr=10.0, stop=630.0, shares=25.0, risk_dollars=500.0)
    text = format_sizing_field(suggestion, risk_pct=1.0, equity=50_000.0)
    assert "Stop: $630.00" in text
    assert "25 shares" in text
    assert "$16,250" in text  # 25 × 650
    assert "risking ~$500 (1% of $50,000)" in text
