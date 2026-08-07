"""Unit tests for the pure ATR/sizing math in backend/services/sizing.py."""
import pytest

from backend.services.sizing import SizingSuggestion, compute_atr, format_sizing_field, suggest_position


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
    # 25 × $650 = $16,250, under the 40% cap of $20,000, so risk sizing wins.
    suggestion = suggest_position(
        price=650.0, atr=10.0, equity=50_000.0, risk_pct=1.0, max_position_pct=40.0
    )
    assert suggestion.stop == pytest.approx(630.0)
    assert suggestion.shares == pytest.approx(25.0)
    assert suggestion.risk_dollars == pytest.approx(500.0)
    assert suggestion.capped is False


def test_position_cap_binds_when_volatility_is_low():
    # The case the cap exists for: a small risk budget divided by a tiny ATR
    # produces a share count worth several times the whole account.
    # 1% of $10k = $100 risk; $100 / (2 × $0.10) = 500 shares = $50,000.
    suggestion = suggest_position(
        price=100.0, atr=0.1, equity=10_000.0, risk_pct=1.0, max_position_pct=20.0
    )
    assert suggestion.capped is True
    assert suggestion.shares == pytest.approx(20.0)  # $2,000 cap / $100
    assert suggestion.max_position_value == pytest.approx(2_000.0)


def test_position_cap_on_a_small_account():
    # $5,000 account, 1% risk = $50. A $50 stock with a $0.50 ATR sizes to
    # 50 shares ($2,500, half the account) on risk alone; the 20% cap cuts it
    # to $1,000.
    suggestion = suggest_position(
        price=50.0, atr=0.5, equity=5_000.0, risk_pct=1.0, max_position_pct=20.0
    )
    assert suggestion.capped is True
    assert suggestion.shares * suggestion.price == pytest.approx(1_000.0)


def test_default_cap_is_twenty_percent():
    # Callers that pass no cap still get one — the default must not be 100%.
    suggestion = suggest_position(price=100.0, atr=0.1, equity=10_000.0, risk_pct=1.0)
    assert suggestion.capped is True
    assert suggestion.shares * suggestion.price == pytest.approx(2_000.0)


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
