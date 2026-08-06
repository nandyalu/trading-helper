"""Unit tests for the pure signal-grading logic in bot/signals.py."""
from bot.signals import evaluate_outcome, evaluate_signal_window


# --- evaluate_outcome (absolute rule, unchanged behavior) ---------------------


def test_buy_passes_on_any_gain():
    assert evaluate_outcome("Buy", 100.0, 100.01) == "pass"
    assert evaluate_outcome("Overweight", 100.0, 99.99) == "fail"


def test_sell_passes_on_any_drop():
    assert evaluate_outcome("Sell", 100.0, 99.0) == "pass"
    assert evaluate_outcome("Underweight", 100.0, 101.0) == "fail"


def test_hold_uses_band():
    assert evaluate_outcome("Hold", 100.0, 109.0) == "pass"
    assert evaluate_outcome("Hold", 100.0, 111.0) == "fail"
    assert evaluate_outcome("Hold", 100.0, 91.0) == "pass"


# --- evaluate_signal_window (benchmark-relative + target hit) -----------------


def test_buy_must_beat_benchmark():
    # Ticker +2%, SPY +5%: absolute pass, relative fail.
    result = evaluate_signal_window(
        "Buy", 100.0, 102.0, benchmark_price_at_signal=500.0, benchmark_price_now=525.0
    )
    assert result.outcome == "pass"
    assert result.outcome_vs_benchmark == "fail"
    assert round(result.alpha_pct, 2) == -3.0
    assert round(result.benchmark_pct_change, 2) == 5.0


def test_sell_passes_when_ticker_lags_benchmark():
    # Ticker +2%, SPY +5%: the Sell was wrong absolutely, right relatively.
    result = evaluate_signal_window(
        "Sell", 100.0, 102.0, benchmark_price_at_signal=500.0, benchmark_price_now=525.0
    )
    assert result.outcome == "fail"
    assert result.outcome_vs_benchmark == "pass"


def test_hold_graded_on_alpha_band():
    within = evaluate_signal_window(
        "Hold", 100.0, 108.0, benchmark_price_at_signal=500.0, benchmark_price_now=510.0
    )
    assert within.outcome_vs_benchmark == "pass"  # alpha +6%, inside ±10
    outside = evaluate_signal_window(
        "Hold", 100.0, 115.0, benchmark_price_at_signal=500.0, benchmark_price_now=500.0
    )
    assert outside.outcome_vs_benchmark == "fail"  # alpha +15%


def test_no_benchmark_leaves_relative_fields_none():
    result = evaluate_signal_window("Buy", 100.0, 105.0)
    assert result.outcome == "pass"
    assert result.outcome_vs_benchmark is None
    assert result.alpha_pct is None
    assert result.benchmark_pct_change is None


def test_target_above_entry_hit_via_window_high():
    result = evaluate_signal_window(
        "Buy", 100.0, 103.0, price_target=110.0, window_high=111.0, window_low=95.0
    )
    assert result.price_target_hit is True
    missed = evaluate_signal_window(
        "Buy", 100.0, 103.0, price_target=110.0, window_high=108.0, window_low=95.0
    )
    assert missed.price_target_hit is False


def test_target_below_entry_hit_via_window_low():
    result = evaluate_signal_window(
        "Sell", 100.0, 96.0, price_target=90.0, window_high=101.0, window_low=89.0
    )
    assert result.price_target_hit is True


def test_no_target_leaves_hit_none():
    result = evaluate_signal_window("Buy", 100.0, 103.0, window_high=104.0, window_low=99.0)
    assert result.price_target_hit is None


def test_zero_entry_price_does_not_crash():
    result = evaluate_signal_window("Buy", 0.0, 103.0)
    assert result.pct_change == 0.0
    assert result.outcome == "fail"
