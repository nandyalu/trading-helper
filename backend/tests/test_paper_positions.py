"""Unit tests for get_paper_positions() (backend/services/paper.py) — the data function
build_paper_embed() now wraps. DB and price lookups are monkeypatched, same
convention as the rest of this suite (no real DB/network in unit tests)."""
import pytest

from backend.services import paper


def test_no_paper_tickers_returns_none(monkeypatch):
    monkeypatch.setattr(paper.db, "get_all_paper_tickers", lambda: [])
    assert paper.get_paper_positions() is None


def test_open_position_priced(monkeypatch):
    monkeypatch.setattr(paper.db, "get_all_paper_tickers", lambda: ["NVDA"])
    monkeypatch.setattr(
        paper.db, "get_paper_transactions",
        lambda ticker: [{"side": "buy", "date": "2026-01-01", "price": 100.0, "quantity": 10.0}],
    )
    monkeypatch.setattr(paper, "get_current_price", lambda ticker: 120.0)

    data = paper.get_paper_positions()
    assert data is not None
    assert len(data.positions) == 1
    pos = data.positions[0]
    assert pos.ticker == "NVDA"
    assert pos.quantity == 10.0
    assert pos.avg_cost == 100.0
    assert pos.price == 120.0
    assert pos.value == 1200.0
    assert pos.unrealized == 200.0
    assert pos.unrealized_pct == pytest.approx(20.0)
    assert data.total_value == 1200.0
    assert data.total_cost == 1000.0
    assert data.total_unrealized == 200.0
    assert data.missing_prices == []


def test_missing_price_tracked_separately(monkeypatch):
    monkeypatch.setattr(paper.db, "get_all_paper_tickers", lambda: ["ZZZ"])
    monkeypatch.setattr(
        paper.db, "get_paper_transactions",
        lambda ticker: [{"side": "buy", "date": "2026-01-01", "price": 10.0, "quantity": 5.0}],
    )
    monkeypatch.setattr(paper, "get_current_price", lambda ticker: None)

    data = paper.get_paper_positions()
    assert data.missing_prices == ["ZZZ"]
    assert data.positions[0].price is None
    assert data.total_value == 0.0


def test_closed_position_excluded_but_realized_counted(monkeypatch):
    monkeypatch.setattr(paper.db, "get_all_paper_tickers", lambda: ["AAPL"])
    monkeypatch.setattr(
        paper.db, "get_paper_transactions",
        lambda ticker: [
            {"side": "buy", "date": "2026-01-01", "price": 100.0, "quantity": 5.0},
            {"side": "sell", "date": "2026-01-05", "price": 110.0, "quantity": 5.0},
        ],
    )
    monkeypatch.setattr(paper, "get_current_price", lambda ticker: 999.0)  # shouldn't be called

    data = paper.get_paper_positions()
    assert data.positions == []  # fully closed, no open position
    assert data.total_realized == 50.0
