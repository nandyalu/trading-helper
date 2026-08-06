"""Unit tests for the pure math in bot/portfolio.py."""
import pytest

from bot import portfolio
from bot.portfolio import LotComparison, compare_open_book, concentration_warnings


def test_open_book_vs_benchmark_weighted_by_cost():
    lots = [
        # $1000 in, now $1200 (+20%); SPY 500→550 over the window (+10%)
        LotComparison(cost=1000.0, value_now=1200.0, benchmark_entry=500.0, benchmark_now=550.0),
        # $3000 in, now $2850 (−5%); SPY 520→550 (+5.77%)
        LotComparison(cost=3000.0, value_now=2850.0, benchmark_entry=520.0, benchmark_now=550.0),
    ]
    result = compare_open_book(lots)
    assert result.book_return_pct == pytest.approx(1.25)  # 4050/4000
    assert result.benchmark_return_pct == pytest.approx(6.826, abs=0.01)
    assert result.alpha_pct == pytest.approx(-5.576, abs=0.01)
    assert result.compared_cost == 4000.0


def test_lots_without_benchmark_excluded_from_both_sides():
    lots = [
        LotComparison(cost=1000.0, value_now=1100.0, benchmark_entry=500.0, benchmark_now=550.0),
        LotComparison(cost=9000.0, value_now=90000.0, benchmark_entry=None, benchmark_now=550.0),
    ]
    result = compare_open_book(lots)
    assert result.compared_cost == 1000.0
    assert result.book_return_pct == pytest.approx(10.0)  # the 10x lot didn't leak in


def test_no_comparable_lots_returns_none():
    assert compare_open_book([]) is None
    only_bad = [LotComparison(cost=100.0, value_now=110.0, benchmark_entry=None, benchmark_now=None)]
    assert compare_open_book(only_bad) is None


def test_concentration_warns_over_threshold_only():
    warnings = concentration_warnings({"NVDA": 40.0, "AAPL": 35.0, "MSFT": 25.0})
    assert warnings == ["⚠️ NVDA is 40% of the book", "⚠️ AAPL is 35% of the book"]


def test_single_position_never_warns():
    assert concentration_warnings({"NVDA": 100.0}) == []


# --- get_portfolio_positions() — the extraction build_portfolio_embed() wraps ---


def test_no_transactions_returns_none(monkeypatch):
    monkeypatch.setattr(portfolio.db, "get_all_transaction_tickers", lambda: [])
    assert portfolio.get_portfolio_positions() is None


def test_open_positions_priced_with_weight(monkeypatch):
    monkeypatch.setattr(portfolio.db, "get_all_transaction_tickers", lambda: ["NVDA", "AAPL"])
    transactions = {
        "NVDA": [{"side": "buy", "date": "2026-01-01", "price": 100.0, "quantity": 10.0}],
        "AAPL": [{"side": "buy", "date": "2026-01-01", "price": 50.0, "quantity": 10.0}],
    }
    monkeypatch.setattr(portfolio.db, "get_transactions", lambda t: transactions[t])
    prices = {"NVDA": 120.0, "AAPL": 60.0}
    monkeypatch.setattr(portfolio, "get_current_price", lambda t: prices[t])
    monkeypatch.setattr(portfolio, "open_book_vs_spy", lambda priced, prices: None)

    data = portfolio.get_portfolio_positions()
    assert data is not None
    assert {p.ticker for p in data.positions} == {"NVDA", "AAPL"}
    nvda = next(p for p in data.positions if p.ticker == "NVDA")
    assert nvda.value == 1200.0
    assert nvda.unrealized == 200.0
    assert nvda.weight_pct == pytest.approx(1200 / 1800 * 100)
    assert data.total_value == 1800.0
    assert data.total_cost == 1500.0
    assert data.comparison is None


def test_missing_price_excluded_from_totals_but_listed(monkeypatch):
    monkeypatch.setattr(portfolio.db, "get_all_transaction_tickers", lambda: ["ZZZ"])
    monkeypatch.setattr(
        portfolio.db, "get_transactions",
        lambda t: [{"side": "buy", "date": "2026-01-01", "price": 10.0, "quantity": 5.0}],
    )
    monkeypatch.setattr(portfolio, "get_current_price", lambda t: None)
    monkeypatch.setattr(portfolio, "open_book_vs_spy", lambda priced, prices: None)

    data = portfolio.get_portfolio_positions()
    assert data.missing_prices == ["ZZZ"]
    assert data.positions[0].price is None
    assert data.total_value == 0.0
