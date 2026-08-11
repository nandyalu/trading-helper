"""The agent's budget accounting.

The simulated account holds $1,000,000 and the agent is given $1,000, so every
one of these tests is really the same test: the budget is the app's number, and
nothing the broker says can raise it.

Pure — trades are constructed in memory and db.get_agent_trades is replaced.
"""
import datetime

import pytest

from backend.database.models import AgentTrade
from backend.services import agent_book


def _trade(ticker="AAPL", side="buy", quantity=2, price=100.0, status="filled", order_id=None):
    return AgentTrade(
        ticker=ticker,
        side=side,
        quantity=quantity,
        price=price,
        status=status,
        client_order_id=order_id or f"{ticker}{side}{quantity}{price}{status}",
        placed_at=datetime.datetime(2026, 8, 11, 14, 30),
        filled_at=datetime.datetime(2026, 8, 11, 14, 30) if status == "filled" else None,
    )


@pytest.fixture
def book_of(monkeypatch):
    def build(trades, budget=1000.0, prices=None):
        monkeypatch.setattr(agent_book.db, "get_agent_trades", lambda: trades)
        monkeypatch.setattr(agent_book, "get_budget", lambda: budget)
        lookup = (lambda t: (prices or {}).get(t)) if prices is not None else None
        return agent_book.build_book(price_lookup=lookup)

    return build


def test_an_empty_book_is_all_cash(book_of):
    book = book_of([])
    assert book.cash == 1000.0
    assert book.equity == 1000.0
    assert book.holdings == []


def test_a_buy_moves_cash_into_a_holding(book_of):
    book = book_of([_trade(quantity=2, price=100.0)], prices={"AAPL": 110.0})

    assert book.cash == 800.0
    assert len(book.holdings) == 1
    holding = book.holdings[0]
    assert holding.quantity == 2
    assert holding.avg_cost == 100.0
    assert holding.market_value == 220.0
    assert holding.unrealized_pnl == 20.0
    assert book.equity == 1020.0
    assert book.return_pct == pytest.approx(2.0)


def test_a_sell_returns_cash_and_realizes_pnl(book_of):
    book = book_of(
        [
            _trade(quantity=2, price=100.0, order_id="b1"),
            _trade(side="sell", quantity=2, price=120.0, order_id="s1"),
        ]
    )

    assert book.cash == pytest.approx(1040.0)
    assert book.realized_pnl == pytest.approx(40.0)
    assert book.holdings == []


def test_a_pending_order_does_not_move_cash(book_of):
    """A market order placed after the close fills at the next open. Counting
    it early would let the same dollar be spent twice in one evening."""
    book = book_of([_trade(quantity=5, price=None, status="pending")])

    assert book.cash == 1000.0
    assert book.holdings == []


def test_an_unpriced_holding_counts_at_cost_not_zero(book_of):
    """Treating it as worthless would understate equity and could talk the
    agent into selling what it can still see."""
    book = book_of([_trade(quantity=2, price=100.0)], prices={})

    assert book.holdings[0].market_value is None
    assert book.market_value == 200.0
    assert book.equity == 1000.0


def test_the_budget_is_not_the_brokers_balance(book_of):
    """The account has $1,000,000. The agent has what the setting says."""
    book = book_of([], budget=1000.0)
    assert book.cash == 1000.0


# --- validation ---------------------------------------------------------------


def _order(ticker="AAPL", side="buy", quantity=1):
    return {"ticker": ticker, "side": side, "quantity": quantity}


def test_a_buy_beyond_cash_is_refused(book_of):
    book = book_of([])
    rejection = agent_book.validate(_order(quantity=10), book, price=200.0)

    assert rejection is not None
    assert "only $1,000.00 is uninvested" in rejection.why


def test_a_buy_within_cash_is_allowed(book_of):
    book = book_of([])
    assert agent_book.validate(_order(quantity=4), book, price=200.0) is None


def test_selling_more_than_held_is_refused(book_of):
    book = book_of([_trade(quantity=2, price=100.0)])
    rejection = agent_book.validate(_order(side="sell", quantity=5), book, price=100.0)

    assert rejection is not None
    assert "no shorting" in rejection.why


def test_selling_what_is_held_is_allowed(book_of):
    book = book_of([_trade(quantity=2, price=100.0)])
    assert agent_book.validate(_order(side="sell", quantity=2), book, price=100.0) is None


def test_a_buy_with_no_price_is_refused(book_of):
    """Without a price the cost can't be checked, and an unchecked buy is how
    the budget gets exceeded."""
    book = book_of([])
    assert agent_book.validate(_order(), book, price=None) is not None


@pytest.mark.parametrize(
    "order",
    [
        {"ticker": "", "side": "buy", "quantity": 1},
        {"ticker": "AAPL", "side": "hold", "quantity": 1},
        {"ticker": "AAPL", "side": "buy", "quantity": 0},
        {"ticker": "AAPL", "side": "buy", "quantity": -2},
        {"ticker": "AAPL", "side": "buy", "quantity": 1.5},
    ],
)
def test_malformed_orders_are_refused(book_of, order):
    assert agent_book.validate(order, book_of([]), price=10.0) is not None


# --- closed round trips (what the agent learns from) ---------------------------


def test_a_buy_then_sell_becomes_one_closed_trade(monkeypatch):
    trades = [
        _trade(quantity=2, price=100.0, order_id="b1"),
        _trade(side="sell", quantity=2, price=120.0, order_id="s1"),
    ]
    closed = agent_book.closed_trades(trades)

    assert len(closed) == 1
    assert closed[0].entry == 100.0
    assert closed[0].exit == 120.0
    assert closed[0].pnl == pytest.approx(40.0)
    assert closed[0].return_pct == pytest.approx(20.0)
    assert closed[0].won


def test_an_open_position_is_not_a_closed_trade():
    assert agent_book.closed_trades([_trade(quantity=2, price=100.0)]) == []


def test_lots_are_matched_fifo_so_realized_pnl_agrees_with_the_book():
    """If this diverged from compute_position, the history shown to the model
    would contradict the realized figure shown beside it."""
    trades = [
        _trade(quantity=2, price=100.0, order_id="b1"),
        _trade(quantity=2, price=200.0, order_id="b2"),
        _trade(side="sell", quantity=3, price=150.0, order_id="s1"),
    ]
    closed = agent_book.closed_trades(trades)

    # FIFO: 2 from the $100 lot, 1 from the $200 lot.
    assert [(t.quantity, t.entry) for t in closed] == [(2.0, 100.0), (1.0, 200.0)]
    assert sum(t.pnl for t in closed) == pytest.approx(100.0 - 50.0)


def test_the_signal_decision_is_carried_from_the_buy_not_the_sell():
    """"You bought this on a Hold" is the pattern worth naming, so the decision
    has to come from the order that opened the position."""
    buy = _trade(quantity=1, price=100.0, order_id="b1")
    buy.signal_id = 7
    sell = _trade(side="sell", quantity=1, price=90.0, order_id="s1")
    sell.signal_id = 9

    closed = agent_book.closed_trades([buy, sell], decisions={7: "Hold", 9: "Sell"})

    assert closed[0].signal_decision == "Hold"


def test_pending_orders_are_not_counted_as_round_trips():
    trades = [
        _trade(quantity=2, price=100.0, order_id="b1"),
        _trade(side="sell", quantity=2, price=None, status="pending", order_id="s1"),
    ]
    assert agent_book.closed_trades(trades) == []
