"""Rejecting trade-plan levels the model invented.

`gemma4-e2b` reasons acceptably in prose but does not reliably carry concrete
figures into structured numeric fields. Two VERI runs on 2026-08-06, same stock
priced at ~$1.26, both with correct ticker-specific reasoning around them:

    signal 1: entry $4.50, stop $4.25, target $3.90
    signal 6: entry $30.00, stop $31.50, target $28.00

Entries 24x apart on the same day. The market analyst's own report had the
right prices (10 EMA 1.15, 50 SMA 1.37), so this is invention at the trader
stage, not bad data and not another ticker's figures bleeding in.

A fabricated stop is worse than no stop: it arms a watchdog alert at a price
the stock may never reach, or fires one the instant it is stored.
"""
import pytest

from backend.services.analysis import _trade_plan_levels
from backend.services.signals import horizon_params, plausible_level

SWING = horizon_params("swing")
POSITION = horizon_params("position")

# Verbatim from the stored signal.
VERI_PLAN = """**Action**: Sell

**Entry Price**: 4.5

**Stop Loss**: 4.25

**Target Price**: 3.9

### Probability & Risk/Reward
- **Win Probability**: 65%
- **Risk/Reward Ratio**: 2.40 : 1 (potential +0.60 vs risk -0.25)
- **Expected Value**: +1.21R (favorable)
"""
VERI_RATIONALE = "**Price Target**: 3.90\n**Time Horizon**: 2 weeks"
VERI_PRICE = 1.265


# --- plausible_level ---------------------------------------------------------


def test_level_near_the_price_is_kept():
    assert plausible_level(1.20, 1.265, 35.0) == 1.20
    assert plausible_level(1.40, 1.265, 35.0) == 1.40


def test_the_actual_hallucinated_levels_are_rejected():
    for invented in (4.5, 4.25, 3.9, 30.0, 31.5, 28.0):
        assert plausible_level(invented, VERI_PRICE, SWING["max_level_deviation_pct"]) is None


def test_boundary_is_inclusive():
    # Exactly at the limit is kept; a hair beyond is not.
    assert plausible_level(135.0, 100.0, 35.0) == 135.0
    assert plausible_level(135.1, 100.0, 35.0) is None


def test_rejection_is_symmetric():
    assert plausible_level(65.0, 100.0, 35.0) == 65.0
    assert plausible_level(64.0, 100.0, 35.0) is None


def test_position_horizon_is_more_forgiving():
    # A six-month thesis may legitimately target further out than a two-week one.
    assert plausible_level(150.0, 100.0, SWING["max_level_deviation_pct"]) is None
    assert plausible_level(150.0, 100.0, POSITION["max_level_deviation_pct"]) == 150.0


def test_missing_inputs_give_none():
    assert plausible_level(None, 100.0, 35.0) is None
    assert plausible_level(100.0, None, 35.0) is None
    assert plausible_level(100.0, 0.0, 35.0) is None  # percent-away-from-zero is meaningless
    assert plausible_level(100.0, -5.0, 35.0) is None


# --- _trade_plan_levels ------------------------------------------------------


def test_the_veri_signal_stores_no_levels():
    levels = _trade_plan_levels(VERI_PLAN, VERI_RATIONALE, VERI_PRICE, "Sell", SWING)
    assert levels["entry_price"] is None
    assert levels["stop_loss"] is None
    assert levels["price_target"] is None


def test_derived_numbers_go_out_with_their_inputs():
    """A "2.40 : 1, +1.21R" beside a trade with no levels reads as confidence
    the analysis never had. Both are computed from entry/stop/target."""
    levels = _trade_plan_levels(VERI_PLAN, VERI_RATIONALE, VERI_PRICE, "Sell", SWING)
    assert levels["risk_reward"] is None
    assert levels["expected_value_r"] is None


def test_win_probability_survives():
    # It is the model's own estimate, not derived from the discarded levels.
    levels = _trade_plan_levels(VERI_PLAN, VERI_RATIONALE, VERI_PRICE, "Sell", SWING)
    assert levels["win_probability"] == 65.0


def test_a_grounded_plan_is_kept_whole():
    plan = """**Entry Price**: 1.26

**Stop Loss**: 1.15

**Target Price**: 1.55

### Probability & Risk/Reward
- **Win Probability**: 60%
- **Risk/Reward Ratio**: 2.64 : 1
- **Expected Value**: +0.98R (favorable)
"""
    levels = _trade_plan_levels(plan, "**Price Target**: 1.55", VERI_PRICE, "Sell", SWING)
    assert levels["entry_price"] == pytest.approx(1.26)
    assert levels["stop_loss"] == pytest.approx(1.15)
    assert levels["price_target"] == pytest.approx(1.55)
    assert levels["risk_reward"] == pytest.approx(2.64)
    assert levels["expected_value_r"] == pytest.approx(0.98)


def test_no_price_keeps_everything():
    # An unknown price is not evidence that the model invented the levels.
    levels = _trade_plan_levels(VERI_PLAN, VERI_RATIONALE, None, "Sell", SWING)
    assert levels["entry_price"] == 4.5
    assert levels["risk_reward"] == 2.40


def test_a_plan_with_no_levels_at_all_is_not_treated_as_discarded():
    plan = "**Action**: Hold\n\n### Probability & Risk/Reward\n- **Win Probability**: 50%\n"
    levels = _trade_plan_levels(plan, "", VERI_PRICE, "Sell", SWING)
    assert levels["entry_price"] is None
    assert levels["win_probability"] == 50.0


# --- the target must come from the same plan as the numbers derived from it ----

# ADT on 2026-08-12, as the model actually produced it. The trader proposed a
# 7.31 target and computed 0.08 risk/reward from it; the portfolio manager
# overrode the decision to Hold and stated 6.80. Taking the target from the
# manager while taking the arithmetic from the trader stored a row whose
# risk/reward could not be explained by the levels printed beside it.
ADT_PLAN = """**Action**: Sell

**Entry Price**: 7.28

**Stop Loss**: 6.9

**Target Price**: 7.31

### Probability & Risk/Reward
- **Win Probability**: 65%
- **Risk/Reward Ratio**: 0.08 : 1 (potential +0.03 vs risk -0.38)
- **Expected Value**: -0.30R (unfavorable)
"""
ADT_RATIONALE = "**Rating**: Hold\n\n**Price Target**: 6.8\n\n**Time Horizon**: 1-2 weeks"
ADT_PRICE = 7.31


def test_the_target_comes_from_the_trader_not_the_final_decision():
    levels = _trade_plan_levels(ADT_PLAN, ADT_RATIONALE, ADT_PRICE, "Sell", SWING)

    assert levels["price_target"] == 7.31, "the manager's 6.80 does not belong with the trader's math"
    assert levels["entry_price"] == 7.28
    assert levels["stop_loss"] == 6.9


def test_the_stored_risk_reward_is_explainable_by_the_stored_levels():
    """0.08 is (7.31 - 7.28) / (7.28 - 6.90). With a 6.80 target stored instead
    the ratio described a trade that was not on the row."""
    levels = _trade_plan_levels(ADT_PLAN, ADT_RATIONALE, ADT_PRICE, "Sell", SWING)

    entry, stop, target = levels["entry_price"], levels["stop_loss"], levels["price_target"]
    implied = (target - entry) / (entry - stop)
    assert implied == pytest.approx(levels["risk_reward"], abs=0.01)


def test_the_final_decision_still_supplies_a_target_the_trader_omitted():
    """The manager is the fallback, not the default — a plan with no target of
    its own should still record the one the decision states."""
    plan = "**Action**: Buy\n\n**Entry Price**: 7.28\n\n**Stop Loss**: 6.9\n"

    levels = _trade_plan_levels(plan, "**Price Target**: 8.50", ADT_PRICE, "Buy", SWING)

    assert levels["price_target"] == 8.50


# --- levels on the wrong side of the traded price ------------------------------

# ZBH on 2026-08-12, verbatim. Every level is within 8% of the traded price, so
# the deviation check kept all three — and the target was under the market from
# the moment it was written. The auto trader bought at $98.41 that afternoon
# with a stored target of $92.00.
ZBH_PLAN = """**Action**: Buy

**Entry Price**: 91.0

**Stop Loss**: 90.76

**Target Price**: 92.0

### Probability & Risk/Reward
- **Win Probability**: 60%
- **Risk/Reward Ratio**: 4.17 : 1 (potential +1.00 vs risk -0.24)
- **Expected Value**: +1.10R (favorable)
"""
ZBH_PRICE = 97.89


def test_a_target_the_price_has_already_passed_is_dropped():
    """A pullback plan for a pullback that never came. The entry the levels
    were drawn around is $7 below the market, so the target is reached the
    instant it is stored.

    The stop stays: at $90.76 it is still under the traded price, so it is a
    real floor — merely a distant one — and the watchdog can watch it.
    """
    levels = _trade_plan_levels(ZBH_PLAN, "", ZBH_PRICE, "Buy", POSITION)

    assert levels["price_target"] is None
    assert levels["stop_loss"] == 90.76


def test_a_stop_the_price_is_already_under_is_dropped():
    """It would fire the moment it was stored. Nulling it also hands the signal
    to the ATR fallback, which is how a Buy still ends up with a usable exit."""
    plan = ZBH_PLAN.replace("**Stop Loss**: 90.76", "**Stop Loss**: 99.10")

    levels = _trade_plan_levels(plan, "", ZBH_PRICE, "Buy", POSITION)

    assert levels["stop_loss"] is None


def test_the_derived_numbers_go_out_with_a_wrong_side_level():
    """4.17 : 1 beside no levels at all reads as a good bet nobody can check."""
    levels = _trade_plan_levels(ZBH_PLAN, "", ZBH_PRICE, "Buy", POSITION)

    assert levels["risk_reward"] is None
    assert levels["expected_value_r"] is None
    # The model's own estimate survives, as it does everywhere else — it is not
    # derived from the levels.
    assert levels["win_probability"] == 60.0


def test_the_unreached_entry_itself_is_kept():
    """It is the one number that is still true: this is the price the model
    wanted to pay, and it says plainly why the rest was dropped."""
    levels = _trade_plan_levels(ZBH_PLAN, "", ZBH_PRICE, "Buy", POSITION)

    assert levels["entry_price"] == 91.0


def test_a_target_level_with_the_price_exactly_on_it_is_dropped():
    """ADT, whose stored decision was Hold at $7.31 with a $7.31 target. There
    is no move left to watch for."""
    levels = _trade_plan_levels(ADT_PLAN, ADT_RATIONALE, ADT_PRICE, "Hold", SWING)

    assert levels["price_target"] is None


def test_a_coherent_plan_is_untouched():
    """GOOG the same day: stop below, target above, both kept."""
    plan = """**Action**: Buy

**Entry Price**: 342.37

**Stop Loss**: 315.04

**Target Price**: 377.09

### Probability & Risk/Reward
- **Win Probability**: 65%
- **Risk/Reward Ratio**: 1.27 : 1
- **Expected Value**: +0.48R (favorable)
"""
    levels = _trade_plan_levels(plan, "", 342.37, "Overweight", POSITION)

    assert levels["stop_loss"] == 315.04
    assert levels["price_target"] == 377.09
    assert levels["risk_reward"] == 1.27


def test_a_sell_signal_keeps_levels_that_point_downward():
    """This app is long-only and takes no action on a Sell, so its levels are
    left as stated rather than screened against a direction it never trades."""
    levels = _trade_plan_levels(VERI_PLAN, VERI_RATIONALE, 4.60, "Sell", SWING)

    assert levels["price_target"] == 3.9
    assert levels["stop_loss"] == 4.25
