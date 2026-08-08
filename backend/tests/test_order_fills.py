"""Rebuilding an imported holding from real order history.

A Webull position snapshot carries no acquisition date — confirmed against the
documented schema, which is why broker._parse_opened_at never matches anything.
Without a date, an imported holding was recorded as bought on the day the sync
ran, and each lot's benchmark entry was anchored there: SPY got a few days to
move while the position was credited with months of gains, so the vs-SPY alpha
came out enormous and meaningless.

Order History does carry it. These tests cover the two halves of using it —
turning a raw order row into a fill, and turning fills back into the lots that
are still open.
"""
import datetime

import pytest

from backend.services.broker import (
    BrokerFill,
    BrokerPosition,
    _parse_fill,
    orders_in,
    plan_sync,
    reconstruct_open_lots,
)
from backend.services.positions import ESTIMATED_DATE_NOTE, compute_position


def _fill(symbol="GOOG", side="buy", day="2026-03-14", price=200.0, quantity=5.0):
    return BrokerFill(
        symbol=symbol,
        side=side,
        date=datetime.date.fromisoformat(day),
        price=price,
        quantity=quantity,
    )


def _row(**overrides):
    row = {
        "symbol": "GOOG",
        "side": "BUY",
        "filled_quantity": "4.5",
        "filled_price": "209.35",
        "filled_time_at": "2026-03-14T15:30:00Z",
        "instrument_type": "EQUITY",
    }
    row.update(overrides)
    return row


# --- orders_in ---------------------------------------------------------------
#
# Captured verbatim from the live endpoint on 2026-08-07. The rows are combo
# wrappers, not orders — reading the top level finds no symbol, no side and no
# quantity, so every row would parse to nothing. The documentation only hints
# at this ("if they are group orders, will be returned together").

LIVE_ROW = {
    "client_order_id": "6a74b7e8691b4e7ecde586ef",
    "combo_type": "NORMAL",
    "combo_order_id": "F8JMNT15KKA3755FQEOONT85PB",
    "orders": [
        {
            "symbol": "VERI",
            "side": "SELL",
            "status": "FILLED",
            "client_order_id": "6a74b7e8691b4e7ecde586ef",
            "order_type": "LIMIT",
            "instrument_type": "EQUITY",
            "total_quantity": "10",
            "filled_quantity": "10",
            "place_time_at": "2026-08-06T16:36:01.429Z",
            "filled_time": "1786034161476",
            "filled_time_at": "2026-08-06T16:36:01.476Z",
            "filled_price": "1.221",
        }
    ],
}


def test_orders_are_unwrapped_from_the_combo_row():
    orders = orders_in(LIVE_ROW)
    assert len(orders) == 1
    assert orders[0]["symbol"] == "VERI"


def test_a_live_row_parses_end_to_end():
    fill = _parse_fill(orders_in(LIVE_ROW)[0])
    assert fill == BrokerFill("VERI", "sell", datetime.date(2026, 8, 6), 1.221, 10.0)


def test_a_multi_leg_combo_yields_every_leg():
    row = {"orders": [{"symbol": "A"}, {"symbol": "B"}]}
    assert [o["symbol"] for o in orders_in(row)] == ["A", "B"]


def test_a_row_with_no_orders_list_is_empty():
    assert orders_in({"client_order_id": "x", "combo_type": "NORMAL"}) == []


def test_a_flat_order_row_still_works():
    # Defensive: if the endpoint ever stops wrapping, do not silently drop it.
    assert orders_in({"symbol": "GOOG", "side": "BUY"})[0]["symbol"] == "GOOG"


# --- _parse_fill -------------------------------------------------------------


def test_parses_a_filled_equity_buy():
    fill = _parse_fill(_row())
    assert fill == BrokerFill("GOOG", "buy", datetime.date(2026, 3, 14), 209.35, 4.5)


def test_accepts_an_epoch_timestamp():
    fill = _parse_fill(_row(filled_time_at=None, filled_time=1773446400000))
    assert fill is not None and fill.date == datetime.date(2026, 3, 14)


def test_drops_an_unfilled_order():
    # A cancelled or still-open order reports filled_quantity 0.
    assert _parse_fill(_row(filled_quantity="0")) is None


def test_drops_a_short_because_this_app_is_long_only():
    assert _parse_fill(_row(side="SHORT")) is None


def test_drops_non_equity():
    assert _parse_fill(_row(instrument_type="OPTION")) is None


def test_drops_a_fill_with_no_date():
    # A dated fill is the entire reason for calling this endpoint.
    assert _parse_fill(_row(filled_time_at=None)) is None


def test_drops_a_cvr_style_symbol():
    assert _parse_fill(_row(symbol="RGLSCVR12WB")) is None


# --- reconstruct_open_lots ---------------------------------------------------


def test_a_single_buy_becomes_one_dated_lot():
    position = BrokerPosition("GOOG", 4.5, 209.35)
    lots = reconstruct_open_lots(position, [_fill(quantity=4.5, price=209.35)])
    assert len(lots) == 1
    assert lots[0].date == datetime.date(2026, 3, 14)
    assert lots[0].quantity == pytest.approx(4.5)
    assert lots[0].price == pytest.approx(209.35)
    assert lots[0].reason == "imported fill"


def test_open_lots_are_the_newest_buys():
    """FIFO sells the oldest shares first, so what is still held is the newest
    buys. Taking the oldest instead would date the position years too early."""
    position = BrokerPosition("GOOG", 6.0, 200.0)
    fills = [
        _fill(day="2024-01-10", quantity=10.0, price=100.0),  # long since sold
        _fill(day="2026-02-01", quantity=4.0, price=180.0),
        _fill(day="2026-03-14", quantity=2.0, price=220.0),
    ]
    lots = reconstruct_open_lots(position, fills)
    assert [(lot.date.isoformat(), lot.quantity) for lot in lots] == [
        ("2026-02-01", 4.0),
        ("2026-03-14", 2.0),
    ]


def test_lots_come_back_oldest_first():
    position = BrokerPosition("GOOG", 9.0, 200.0)
    fills = [_fill(day="2026-03-14", quantity=5.0), _fill(day="2026-01-05", quantity=5.0)]
    lots = reconstruct_open_lots(position, fills)
    assert [lot.date.isoformat() for lot in lots] == ["2026-01-05", "2026-03-14"]


def test_a_partial_lot_is_split():
    position = BrokerPosition("GOOG", 3.0, 200.0)
    lots = reconstruct_open_lots(position, [_fill(day="2026-03-14", quantity=10.0)])
    assert len(lots) == 1
    assert lots[0].quantity == pytest.approx(3.0)


def test_shares_the_history_cannot_explain_are_marked_unknown():
    """Bought before Order History's 2018 horizon, or transferred in. Better
    excluded from the benchmark than given an invented date."""
    position = BrokerPosition("GOOG", 10.0, 150.0)
    lots = reconstruct_open_lots(position, [_fill(day="2026-03-14", quantity=4.0, price=220.0)])
    assert len(lots) == 2
    dated, remainder = lots
    assert dated.quantity == pytest.approx(4.0)
    assert remainder.date is None
    assert remainder.quantity == pytest.approx(6.0)
    assert ESTIMATED_DATE_NOTE in remainder.reason
    assert remainder.price == pytest.approx(150.0)  # broker's blended average


def test_no_fills_at_all_falls_back_entirely():
    position = BrokerPosition("GOOG", 4.5, 209.35)
    lots = reconstruct_open_lots(position, [])
    assert len(lots) == 1
    assert lots[0].date is None
    assert ESTIMATED_DATE_NOTE in lots[0].reason


def test_other_tickers_and_sells_are_ignored():
    position = BrokerPosition("GOOG", 2.0, 200.0)
    fills = [
        _fill(symbol="NVDA", quantity=99.0),
        _fill(side="sell", quantity=99.0),
        _fill(day="2026-03-14", quantity=2.0),
    ]
    lots = reconstruct_open_lots(position, fills)
    assert len(lots) == 1
    assert lots[0].quantity == pytest.approx(2.0)


# --- plan_sync integration ---------------------------------------------------


def test_first_import_uses_fills_when_available():
    position = BrokerPosition("GOOG", 6.0, 200.0)
    fills = [_fill(day="2026-02-01", quantity=4.0), _fill(day="2026-03-14", quantity=2.0)]
    plan = plan_sync([position], {}, [], fills=fills)
    assert [a.reason for a in plan.transactions] == ["imported fill", "imported fill"]
    assert all(a.date is not None for a in plan.transactions)


def test_without_fills_the_old_behavior_stands():
    plan = plan_sync([BrokerPosition("GOOG", 6.0, 200.0)], {}, [], fills=None)
    assert len(plan.transactions) == 1
    assert ESTIMATED_DATE_NOTE in plan.transactions[0].reason


def test_drift_is_never_rebuilt_from_history():
    """Drift is genuinely new shares. Dating them from an old fill would be its
    own lie, and the position is already known so nothing needs reconstructing."""
    position = BrokerPosition("GOOG", 10.0, 200.0)
    fills = [_fill(day="2026-02-01", quantity=10.0)]
    plan = plan_sync([position], {"GOOG": 6.0}, ["GOOG"], fills=fills)
    assert len(plan.transactions) == 1
    action = plan.transactions[0]
    assert action.quantity == pytest.approx(4.0)
    assert action.reason == "quantity drift"
    assert action.date is None  # add_transaction defaults to today


def test_the_rebuilt_lots_reproduce_the_broker_quantity():
    """End to end: the transactions the plan emits, run through the same FIFO
    math the app uses everywhere, must add back up to what Webull holds."""
    position = BrokerPosition("GOOG", 6.0, 200.0)
    fills = [_fill(day="2026-02-01", quantity=4.0, price=180.0), _fill(day="2026-03-14", quantity=2.0, price=220.0)]
    plan = plan_sync([position], {}, [], fills=fills)

    transactions = [
        {"side": a.side, "date": a.date.isoformat(), "price": a.price, "quantity": a.quantity, "note": None}
        for a in plan.transactions
    ]
    rebuilt = compute_position(transactions)
    assert rebuilt.quantity == pytest.approx(6.0)
    # Blended cost from the real fills: (4x180 + 2x220) / 6 = 193.33
    assert rebuilt.avg_cost == pytest.approx(193.333, abs=0.01)
    assert all(not lot.date_estimated for lot in rebuilt.open_lots)
