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
    levels = _trade_plan_levels(VERI_PLAN, VERI_RATIONALE, VERI_PRICE, SWING)
    assert levels["entry_price"] is None
    assert levels["stop_loss"] is None
    assert levels["price_target"] is None


def test_derived_numbers_go_out_with_their_inputs():
    """A "2.40 : 1, +1.21R" beside a trade with no levels reads as confidence
    the analysis never had. Both are computed from entry/stop/target."""
    levels = _trade_plan_levels(VERI_PLAN, VERI_RATIONALE, VERI_PRICE, SWING)
    assert levels["risk_reward"] is None
    assert levels["expected_value_r"] is None


def test_win_probability_survives():
    # It is the model's own estimate, not derived from the discarded levels.
    levels = _trade_plan_levels(VERI_PLAN, VERI_RATIONALE, VERI_PRICE, SWING)
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
    levels = _trade_plan_levels(plan, "**Price Target**: 1.55", VERI_PRICE, SWING)
    assert levels["entry_price"] == pytest.approx(1.26)
    assert levels["stop_loss"] == pytest.approx(1.15)
    assert levels["price_target"] == pytest.approx(1.55)
    assert levels["risk_reward"] == pytest.approx(2.64)
    assert levels["expected_value_r"] == pytest.approx(0.98)


def test_no_price_keeps_everything():
    # An unknown price is not evidence that the model invented the levels.
    levels = _trade_plan_levels(VERI_PLAN, VERI_RATIONALE, None, SWING)
    assert levels["entry_price"] == 4.5
    assert levels["risk_reward"] == 2.40


def test_a_plan_with_no_levels_at_all_is_not_treated_as_discarded():
    plan = "**Action**: Hold\n\n### Probability & Risk/Reward\n- **Win Probability**: 50%\n"
    levels = _trade_plan_levels(plan, "", VERI_PRICE, SWING)
    assert levels["entry_price"] is None
    assert levels["win_probability"] == 50.0
