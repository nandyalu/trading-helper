"""Unit tests for the pure aggregation in backend/services/scorecard.py (Signal rows are
constructed in memory — no DB involved)."""
import datetime

import pytest

from backend.database.models import Signal
from backend.services.scorecard import UNKNOWN_MODEL, aggregate, format_scorecard_embed


def _signal(
    ticker="NVDA",
    decision="Buy",
    outcome="pass",
    price_at_signal=100.0,
    price_at_evaluation=110.0,
    outcome_vs_benchmark=None,
    alpha_pct=None,
    price_target_hit=None,
    model=None,
):
    return Signal(
        ticker=ticker,
        signal_date=datetime.date(2026, 6, 1),
        decision=decision,
        rationale="",
        price_at_signal=price_at_signal,
        evaluation_date=datetime.date(2026, 7, 1),
        price_at_evaluation=price_at_evaluation,
        outcome=outcome,
        outcome_vs_benchmark=outcome_vs_benchmark,
        alpha_pct=alpha_pct,
        price_target_hit=price_target_hit,
        model=model,
    )


def test_empty_scorecard():
    stats = aggregate([], pending=3)
    assert stats.resolved == 0
    assert stats.pending == 3
    assert stats.avg_alpha_pct is None


def test_overall_and_by_decision_counts():
    resolved = [
        _signal(decision="Buy", outcome="pass", outcome_vs_benchmark="pass", alpha_pct=4.0),
        _signal(decision="Buy", outcome="pass", outcome_vs_benchmark="fail", alpha_pct=-2.0),
        _signal(decision="Sell", outcome="fail", price_at_evaluation=105.0),
        _signal(ticker="AAPL", decision="Hold", outcome="pass", price_at_evaluation=101.0),
    ]
    stats = aggregate(resolved, pending=2)
    assert stats.resolved == 4
    assert stats.passes == 3
    # Only the two rows that actually got a benchmark grade count there.
    assert stats.vs_benchmark_total == 2
    assert stats.vs_benchmark_passes == 1
    assert stats.avg_alpha_pct == 1.0
    assert stats.by_decision["Buy"].total == 2
    assert stats.by_decision["Buy"].passes == 2
    assert stats.by_decision["Buy"].avg_move_pct == pytest.approx(10.0)
    assert stats.by_decision["Sell"].vs_benchmark_total == 0
    assert stats.by_ticker == {"NVDA": (2, 3), "AAPL": (1, 1)}


def test_target_hit_rate_counts_only_graded_rows():
    resolved = [
        _signal(price_target_hit=True),
        _signal(price_target_hit=False),
        _signal(),  # no target — excluded from the denominator
    ]
    stats = aggregate(resolved)
    assert stats.target_total == 2
    assert stats.target_hits == 1


def test_each_model_keeps_its_own_record():
    """The point of being able to switch models: a new one's win rate has to be
    readable on its own, not blended into the incumbent's."""
    resolved = [
        _signal(model="old:latest"),
        _signal(model="old:latest", outcome="fail", price_at_evaluation=90.0),
        _signal(model="new:latest", outcome="fail", price_at_evaluation=90.0),
    ]
    stats = aggregate(resolved)

    assert stats.by_model["old:latest"].total == 2
    assert stats.by_model["old:latest"].passes == 1
    assert stats.by_model["new:latest"].total == 1
    assert stats.by_model["new:latest"].passes == 0
    assert stats.by_model["old:latest"].avg_move_pct == pytest.approx(0.0)


def test_signals_predating_the_model_column_are_named_not_dropped():
    stats = aggregate([_signal(), _signal(model="new:latest")])

    assert stats.by_model[UNKNOWN_MODEL].total == 1
    assert sum(row.total for row in stats.by_model.values()) == stats.resolved


def test_by_model_appears_in_the_embed_only_once_there_are_two():
    one_model = aggregate([_signal(model="old:latest")])
    assert "By model" not in [f.name for f in format_scorecard_embed(one_model).fields]

    two_models = aggregate([_signal(model="old:latest"), _signal(model="new:latest")])
    assert "By model" in [f.name for f in format_scorecard_embed(two_models).fields]


def test_embed_renders_without_error():
    stats = aggregate(
        [
            _signal(outcome_vs_benchmark="pass", alpha_pct=3.2, price_target_hit=True),
            _signal(decision="Sell", outcome="fail", price_at_evaluation=104.0),
        ],
        pending=1,
    )
    embed = format_scorecard_embed(stats)
    assert embed.title == "Signal Scorecard"
    field_names = [f.name for f in embed.fields]
    assert "Overall" in field_names
    assert "By decision" in field_names
    assert "By ticker" in field_names
    filtered = format_scorecard_embed(stats, ticker="NVDA")
    assert "NVDA" in filtered.title
    assert "By ticker" not in [f.name for f in filtered.fields]
