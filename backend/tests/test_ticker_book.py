"""One ticker's money: who holds it, what is protecting it, and every lot.

The case these exist for: opening INTC on 2026-08-20 showed a signal's stop of
$84.63 and no position at all, while the auto trader held three shares at
$91.84 with nothing resting at the broker. The page showed a number that looked
like protection next to a position it did not know about.

Pure — fills are constructed in memory.
"""
import datetime

import pytest

from backend.services import ticker_book


def _fill(side, day, price, quantity, signal_id=None):
    return {
        "side": side,
        "date": day,
        "price": price,
        "quantity": quantity,
        "signal_id": signal_id,
    }


# --- FIFO lot matching ---------------------------------------------------------


def test_a_closed_lot_carries_its_result():
    lots = ticker_book.match_lots("agent", [
        _fill("buy", "2026-08-13", 98.41, 3),
        _fill("sell", "2026-08-19", 101.50, 3),
    ])

    assert len(lots) == 1
    assert lots[0].pnl == pytest.approx((101.50 - 98.41) * 3)
    assert lots[0].held_days == 6
    assert not lots[0].is_open


def test_an_open_lot_has_no_profit_yet():
    """An unrealized figure in this column would read as booked."""
    lots = ticker_book.match_lots("agent", [_fill("buy", "2026-08-13", 98.41, 3)])

    assert lots[0].pnl is None
    assert lots[0].return_pct is None
    assert lots[0].is_open


def test_selling_part_of_a_position_splits_it():
    """The shares sold get their own result; the rest stays open. Both come
    from one walk, so the two can never disagree about the same shares."""
    lots = ticker_book.match_lots("real", [
        _fill("buy", "2026-08-13", 100.0, 5),
        _fill("sell", "2026-08-14", 110.0, 2),
    ])

    closed = [lot for lot in lots if not lot.is_open]
    still_open = [lot for lot in lots if lot.is_open]
    assert [lot.quantity for lot in closed] == [2]
    assert [lot.quantity for lot in still_open] == [3]


def test_the_oldest_lot_is_sold_first():
    """FIFO, to agree with compute_position — realized P/L summed from these
    rows has to equal the realized P/L the position tiles show."""
    lots = ticker_book.match_lots("real", [
        _fill("buy", "2026-08-10", 10.0, 1),
        _fill("buy", "2026-08-11", 20.0, 1),
        _fill("sell", "2026-08-12", 30.0, 1),
    ])

    closed = [lot for lot in lots if not lot.is_open][0]
    assert closed.entry == 10.0


def test_iso_dates_and_date_objects_both_work():
    """The two transaction tables return ISO strings and the agent's ledger
    returns dates, so the arithmetic has to survive either."""
    lots = ticker_book.match_lots("paper", [
        _fill("buy", datetime.date(2026, 8, 13), 100.0, 1),
        _fill("sell", "2026-08-15", 105.0, 1),
    ])

    assert lots[0].held_days == 2


# --- the unprotected flag ------------------------------------------------------


def test_a_position_with_no_resting_exit_is_flagged():
    """INTC, exactly. A bracket the broker refused looks the same as one that
    worked unless something goes looking for the absence."""
    position = ticker_book.AgentPosition(quantity=3, avg_cost=91.84, price=92.80, exits=[])

    assert position.unprotected is True


def test_a_position_with_one_exit_is_not_flagged():
    """Half a bracket is still an exit — the analysis states a level only when
    it has a view, and one that exists is placed on its own."""
    position = ticker_book.AgentPosition(
        quantity=3, avg_cost=91.84, exits=[ticker_book.RestingExit("stop", 88.0, 3)]
    )

    assert position.unprotected is False
    assert position.level("stop") == 88.0
    assert position.level("target") is None


def test_holding_nothing_is_not_unprotected():
    assert ticker_book.AgentPosition(quantity=0, avg_cost=0, exits=[]).unprotected is False
