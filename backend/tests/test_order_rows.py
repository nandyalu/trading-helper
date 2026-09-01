"""Unwrapping a Webull order-history row.

The endpoint answers with a *combo wrapper*, not an order. The symbol, side and
quantity all live inside an ``orders`` list, and the top level carries none of
them — so reading the top level finds a plausible-looking dict that parses to
nothing, and every fill stays pending forever. That is what ``orders_in``
exists to prevent.
"""
from backend.services.sandbox_broker import orders_in


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


def test_a_multi_leg_combo_yields_every_leg():
    row = {"orders": [{"symbol": "A"}, {"symbol": "B"}]}
    assert [o["symbol"] for o in orders_in(row)] == ["A", "B"]


def test_a_row_with_no_orders_list_is_empty():
    assert orders_in({"client_order_id": "x", "combo_type": "NORMAL"}) == []


def test_a_flat_order_row_still_works():
    # Defensive: if the endpoint ever stops wrapping, do not silently drop it.
    assert orders_in({"symbol": "GOOG", "side": "BUY"})[0]["symbol"] == "GOOG"
