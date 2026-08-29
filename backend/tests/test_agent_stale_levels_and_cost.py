"""Two defects the 2026-08-28 SMCI purchase exposed.

Both were invisible in the ledger and at the broker, because both produced
numbers that look entirely reasonable: a real stop from a real signal, and an
order that passed a real affordability check.
"""
import datetime

import pytest

from backend.services import agent, agent_book

class Sig:
    def __init__(self, id, ticker, day, stop, target):
        self.id, self.ticker = id, ticker
        self.signal_date = datetime.date(2026, 8, day)
        self.stop_loss, self.price_target = stop, target

def _book(cash):
    return agent_book.Book(budget=10_000.0, cash=cash, realized_pnl=0.0, holdings=[])

# --- the newest signal wins -----------------------------------------------------

class TestNewestSignalPerTicker:
    """A dict comprehension keeps the last value it sees, and the signal list
    arrives newest-first, so the oldest signal won every time a ticker had been
    analysed twice."""

    YESTERDAY = Sig(3, "SMCI", 27, 34.16, 45.21)
    TODAY = Sig(4, "SMCI", 28, 34.04, 49.51)

    def test_the_newest_signal_wins_whatever_order_it_arrives_in(self):
        for order in ([self.TODAY, self.YESTERDAY], [self.YESTERDAY, self.TODAY]):
            latest = agent._newest_signal_per_ticker(order)

            assert latest["SMCI"].id == 4
            assert latest["SMCI"].stop_loss == 34.04
            assert latest["SMCI"].price_target == 49.51

    def test_the_real_case_that_rested_a_stale_target(self):
        """The agent rested a 45.21 target on 260 shares when that morning's
        analysis had said 49.51 — $4.30 out, and nothing reported it."""
        latest = agent._newest_signal_per_ticker([self.TODAY, self.YESTERDAY])

        assert latest["SMCI"].price_target != 45.21

    def test_two_signals_on_one_day_break_the_tie_by_id(self):
        """signal_date is a date, so a ticker analysed twice in a morning ties.
        The higher id is the later row."""
        first = Sig(10, "AAPL", 28, 300.0, 340.0)
        second = Sig(11, "AAPL", 28, 305.0, 350.0)

        latest = agent._newest_signal_per_ticker([second, first])

        assert latest["AAPL"].id == 11

    def test_each_ticker_is_independent(self):
        latest = agent._newest_signal_per_ticker(
            [self.TODAY, self.YESTERDAY, Sig(5, "NVDA", 28, 200.0, 260.0)]
        )

        assert set(latest) == {"SMCI", "NVDA"}
        assert latest["NVDA"].id == 5

# --- the cost is checked at the price the order goes out at ---------------------

class TestAffordabilityUsesTheEntryLimit:
    """A buy leaves as a marketable limit through the offer, so screening the
    raw quote approves an order the account cannot pay for."""

    def test_the_limit_is_above_the_quote(self):
        assert agent_book.entry_limit_price(38.46) == pytest.approx(38.65, abs=0.01)

    def test_the_real_case_that_overspent_is_now_refused(self):
        """260 x $38.46 is $9,999.60 against $9,999.70 and passed. It filled at
        $38.49 for $10,007.40 and left the book at minus $7.70."""
        order = {"ticker": "SMCI", "side": "buy", "quantity": 260}

        rejection = agent_book.validate(order, _book(cash=9_999.70), 38.46)

        assert rejection is not None
        assert "entry limit" in rejection.why

    def test_an_order_with_room_for_the_buffer_still_passes(self):
        """The check must not refuse everything: 250 shares at the limit price
        is $9,662.50, which fits."""
        order = {"ticker": "SMCI", "side": "buy", "quantity": 250}

        assert agent_book.validate(order, _book(cash=9_999.70), 38.46) is None

    def test_it_refuses_rather_than_shrinking(self):
        """Resizing would quietly turn the model's decision into a different
        one, and the record would describe a strategy nobody chose."""
        order = {"ticker": "SMCI", "side": "buy", "quantity": 260}

        agent_book.validate(order, _book(cash=9_999.70), 38.46)

        assert order["quantity"] == 260

    def test_a_sell_is_unaffected(self):
        """Selling raises cash; there is no entry limit to allow for."""
        book = agent_book.Book(
            budget=10_000.0, cash=0.0, realized_pnl=0.0,
            holdings=[agent_book.Holding(ticker="SMCI", quantity=260, avg_cost=38.49)],
        )

        assert agent_book.validate(
            {"ticker": "SMCI", "side": "sell", "quantity": 260}, book, 38.46
        ) is None
