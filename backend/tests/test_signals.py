"""Unit tests for the pure signal-grading logic in backend/services/signals.py."""
from backend.services.signals import (
    DEFAULT_HORIZON,
    HORIZONS,
    evaluate_outcome,
    evaluate_signal_window,
    extract_entry_price,
    extract_expected_value,
    extract_price_target,
    extract_risk_reward,
    extract_stop_loss,
    extract_win_probability,
    horizon_params,
    parse_time_horizon_days,
)

# Verbatim output of TradingAgents' render_trader_proposal() — see
# TradingAgents/tradingagents/agents/schemas.py. If the framework changes these
# labels, these tests fail rather than the extractors silently returning None
# on every live analysis.
TRADER_PLAN = """**Action**: Buy

**Reasoning**: r

**Bull Case**: b

**Bear Case**: x

**Entry Price**: 182.5

**Stop Loss**: 174.2

**Target Price**: 201.0

**Position Sizing**: 5% of portfolio

### Probability & Risk/Reward
- **Win Probability**: 65%
- **Risk/Reward Ratio**: 2.23 : 1 (potential +18.50 vs risk -8.30)
- **Expected Value**: +1.10R (favorable)
- **Breakeven Win-Rate**: 31% (current 65% is above breakeven)

FINAL TRANSACTION PROPOSAL: **BUY**"""

# What the trader emits when it gave no entry/stop/target.
TRADER_PLAN_NO_LEVELS = """**Action**: Hold

**Reasoning**: r

### Probability & Risk/Reward
- **Win Probability**: 50%
- **Risk/Reward Ratio**: n/a (needs entry / stop / target prices)

FINAL TRANSACTION PROPOSAL: **HOLD**"""


# --- Trader-plan extraction --------------------------------------------------


def test_extracts_every_trade_plan_field():
    assert extract_entry_price(TRADER_PLAN) == 182.5
    assert extract_stop_loss(TRADER_PLAN) == 174.2
    assert extract_win_probability(TRADER_PLAN) == 65.0
    assert extract_risk_reward(TRADER_PLAN) == 2.23
    assert extract_expected_value(TRADER_PLAN) == 1.10


def test_missing_levels_give_none_not_zero():
    # A stop read as 0.0 would look like a stop at $0 and could trigger a sale.
    assert extract_entry_price(TRADER_PLAN_NO_LEVELS) is None
    assert extract_stop_loss(TRADER_PLAN_NO_LEVELS) is None
    assert extract_risk_reward(TRADER_PLAN_NO_LEVELS) is None  # the "n/a" line
    assert extract_expected_value(TRADER_PLAN_NO_LEVELS) is None
    assert extract_win_probability(TRADER_PLAN_NO_LEVELS) == 50.0


def test_negative_expected_value_is_read_not_dropped():
    # An unfavorable bet is a real reading; losing its sign would invert it.
    plan = "- **Expected Value**: -0.35R (unfavorable)"
    assert extract_expected_value(plan) == -0.35


def test_empty_and_missing_input():
    for extract in (
        extract_entry_price,
        extract_stop_loss,
        extract_win_probability,
        extract_risk_reward,
        extract_expected_value,
    ):
        assert extract("") is None
        assert extract(None) is None
        assert extract("nothing relevant here") is None


def test_malformed_number_does_not_raise():
    # A model that formats badly must not abort the whole analysis.
    assert extract_stop_loss("**Stop Loss**: 17.4.2") is None
    assert extract_entry_price("**Entry Price**: .") is None
    assert extract_price_target("**Price Target**: 1.2.3") is None


def test_dollar_signs_tolerated():
    assert extract_stop_loss("**Stop Loss**: $174.20") == 174.2
    assert extract_price_target("**Price Target**: $201.00") == 201.0


def test_out_of_range_win_probability_rejected():
    # The schema bounds it 0-100; anything else means the text was misread.
    assert extract_win_probability("- **Win Probability**: 650%") is None


# --- Horizon parameters ------------------------------------------------------


def test_swing_grades_sooner_and_tighter_than_position():
    swing, position = horizon_params("swing"), horizon_params("position")
    assert swing["eval_days"] < position["eval_days"]
    assert swing["hold_band_pct"] < position["hold_band_pct"]


def test_unknown_horizon_falls_back_to_default():
    # A bad setting must not stop a signal from being graded.
    assert horizon_params("bogus") == HORIZONS[DEFAULT_HORIZON]
    assert horizon_params(None) == HORIZONS[DEFAULT_HORIZON]
    assert horizon_params("  SWING  ") == HORIZONS["swing"]


def test_swing_is_the_default_horizon():
    assert DEFAULT_HORIZON == "swing"


# --- parse_time_horizon_days -------------------------------------------------


def test_horizon_text_parsed_in_each_unit():
    assert parse_time_horizon_days("2 weeks") == 14
    assert parse_time_horizon_days("1-2 weeks") == 10  # midpoint of 7 and 14
    assert parse_time_horizon_days("10 days") == 10
    assert parse_time_horizon_days("3-6 months") == 135


def test_unparseable_horizon_uses_the_default():
    assert parse_time_horizon_days("long-term", default_days=14) == 14
    assert parse_time_horizon_days(None, default_days=14) == 14
    assert parse_time_horizon_days("", default_days=14) == 14


def test_stated_horizon_is_capped_to_what_the_run_asked_for():
    # A swing run whose model answers "3-6 months" would otherwise book a
    # 135-day evaluation; grading at the cap is closer to what was requested.
    swing = horizon_params("swing")
    days = parse_time_horizon_days(
        "3-6 months", default_days=swing["eval_days"], max_days=swing["max_eval_days"]
    )
    assert days == swing["max_eval_days"]


def test_cap_does_not_stretch_a_shorter_horizon():
    assert parse_time_horizon_days("5 days", default_days=14, max_days=21) == 5


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
