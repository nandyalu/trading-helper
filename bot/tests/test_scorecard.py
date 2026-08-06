"""Unit tests for the pure aggregation in bot/scorecard.py (Signal rows are
constructed in memory — no DB involved)."""
import datetime

import pytest

from bot.models import Signal
from bot.scorecard import aggregate, format_scorecard_embed


def _signal(
    ticker="NVDA",
    decision="Buy",
    outcome="pass",
    price_at_signal=100.0,
    price_at_evaluation=110.0,
    outcome_vs_benchmark=None,
    alpha_pct=None,
    price_target_hit=None,
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
