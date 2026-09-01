"""Unit tests for the pure ATR/sizing math in backend/services/sizing.py."""
import pytest

from backend.services.sizing import compute_atr, suggest_position


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


def test_the_stop_sits_two_atr_below_the_price():
    suggestion = suggest_position(price=650.0, atr=10.0)
    assert suggestion.stop == pytest.approx(630.0)


def test_a_stop_below_zero_is_refused():
    """An ATR comparable to the price puts the stop under zero. That says
    nothing about where the trade is wrong, so no stop is better than one."""
    assert suggest_position(price=10.0, atr=6.0) is None
    assert suggest_position(price=0.0, atr=1.0) is None
    assert suggest_position(price=100.0, atr=0.0) is None


def test_the_multiple_can_be_widened():
    assert suggest_position(price=100.0, atr=5.0, stop_mult=1.0).stop == pytest.approx(95.0)
