"""Unit tests for paper_buy_quantity() (backend/services/paper.py).

Paper buys size the same way real ones do, so the paper equity curve is
evidence about what the real book would have done. They used to use a flat
notional, which on a small account ran a concentration the real book never
would. DB and price lookups are monkeypatched, same convention as the rest of
this suite.
"""
from backend.services import paper, sizing


def _configure(monkeypatch, equity, risk_pct=1.0, max_position_pct=20.0, atr=None):
    monkeypatch.setattr(sizing, "get_risk_settings", lambda: (equity, risk_pct))
    monkeypatch.setattr(sizing, "get_max_position_pct", lambda: max_position_pct)
    monkeypatch.setattr(sizing, "get_atr", lambda ticker: atr)


def test_uses_risk_sizing_when_equity_is_configured(monkeypatch):
    # $5,000 at 1% = $50 risk; $50 / (2 × $1.50) = 16.67 shares of a $50 stock,
    # about $833 — under the 20% ($1,000) cap, so risk sizing wins.
    _configure(monkeypatch, equity=5_000.0, atr=1.5)
    quantity, basis = paper.paper_buy_quantity("NVDA", price=50.0)
    assert quantity == 16.67
    assert "risk sizing" in basis


def test_position_cap_binds_on_a_low_volatility_name(monkeypatch):
    # $50 risk / (2 × $0.50) = 50 shares = $2,500, half the account. The cap
    # cuts it to $1,000.
    _configure(monkeypatch, equity=5_000.0, atr=0.5)
    quantity, _ = paper.paper_buy_quantity("KO", price=50.0)
    assert quantity * 50.0 == 1_000.0


def test_falls_back_to_flat_notional_without_equity(monkeypatch):
    _configure(monkeypatch, equity=None)
    monkeypatch.setattr(paper, "get_notional", lambda: 1_000.0)
    quantity, basis = paper.paper_buy_quantity("NVDA", price=50.0)
    assert quantity == 20.0
    assert "flat notional" in basis


def test_falls_back_to_flat_notional_when_atr_is_unavailable(monkeypatch):
    # A ticker too new or too thin for a 14-day ATR still gets a paper fill
    # rather than being silently skipped.
    _configure(monkeypatch, equity=5_000.0, atr=None)
    monkeypatch.setattr(paper, "get_notional", lambda: 1_000.0)
    quantity, basis = paper.paper_buy_quantity("IPO", price=50.0)
    assert quantity == 20.0
    assert "flat notional" in basis


def test_falls_back_when_atr_makes_a_stop_impossible(monkeypatch):
    # ATR comparable to price → suggest_position returns None (the stop would
    # be at or below zero), so the flat notional takes over.
    _configure(monkeypatch, equity=5_000.0, atr=30.0)
    monkeypatch.setattr(paper, "get_notional", lambda: 1_000.0)
    quantity, basis = paper.paper_buy_quantity("MEME", price=50.0)
    assert quantity == 20.0
    assert "flat notional" in basis
