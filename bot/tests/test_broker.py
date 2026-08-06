"""Unit tests for the pure parts of bot/broker.py — position parsing and the
sync reconciliation plan."""
from bot.broker import BrokerPosition, _parse_position, plan_sync


def _pos(symbol="GOOG", quantity=4.5, cost_price=209.35, last_price=346.12):
    return BrokerPosition(symbol=symbol, quantity=quantity, cost_price=cost_price, last_price=last_price)


# --- parsing (matches the real payload shape: string numbers) -----------------


def test_parse_real_payload_row():
    position = _parse_position(
        {"symbol": "GOOG", "quantity": "4.5", "cost_price": "209.35",
         "last_price": "346.12", "instrument_type": "EQUITY"}
    )
    assert position == BrokerPosition("GOOG", 4.5, 209.35, 346.12)


def test_parse_skips_cvr_style_symbols():
    assert _parse_position(
        {"symbol": "RGLSCVR12WB", "quantity": "51", "cost_price": "4.65",
         "last_price": "0.00", "instrument_type": "EQUITY"}
    ) is None


def test_parse_skips_non_equity_and_junk():
    assert _parse_position({"symbol": "BTC", "quantity": "1", "cost_price": "60000",
                            "instrument_type": "CRYPTO"}) is None
    assert _parse_position({"symbol": "GOOG", "quantity": "0", "cost_price": "10"}) is None
    assert _parse_position({"symbol": "GOOG", "quantity": "nope", "cost_price": "10"}) is None


# --- reconciliation -----------------------------------------------------------


def test_new_holding_imported_and_watchlisted():
    plan = plan_sync([_pos()], bot_quantities={}, watchlist=["NVDA"])
    assert plan.watchlist_adds == ["GOOG"]
    assert len(plan.transactions) == 1
    action = plan.transactions[0]
    assert (action.ticker, action.side, action.quantity, action.price) == ("GOOG", "buy", 4.5, 209.35)
    assert action.reason == "imported holding"


def test_matching_position_is_noop():
    plan = plan_sync([_pos()], bot_quantities={"GOOG": 4.5}, watchlist=["GOOG"])
    assert not plan.has_changes


def test_positive_drift_buys_delta_at_cost():
    plan = plan_sync([_pos(quantity=10.0)], bot_quantities={"GOOG": 4.0}, watchlist=["GOOG"])
    action = plan.transactions[0]
    assert (action.side, action.quantity, action.price) == ("buy", 6.0, 209.35)
    assert action.reason == "quantity drift"


def test_negative_drift_sells_delta_at_last_price():
    plan = plan_sync([_pos(quantity=2.0)], bot_quantities={"GOOG": 4.5}, watchlist=["GOOG"])
    action = plan.transactions[0]
    assert (action.side, action.quantity, action.price) == ("sell", 2.5, 346.12)


def test_bot_only_positions_reported_not_sold():
    plan = plan_sync([_pos()], bot_quantities={"GOOG": 4.5, "NVDA": 3.0, "OLD": 0.0}, watchlist=["GOOG", "NVDA"])
    assert plan.transactions == []
    assert plan.bot_only == ["NVDA"]  # OLD is fully closed — not flagged


def test_fully_closed_bot_ticker_reimported_if_broker_holds():
    plan = plan_sync([_pos(symbol="VERI", quantity=10.0, cost_price=2.73, last_price=1.02)],
                     bot_quantities={"VERI": 0.0}, watchlist=[])
    action = plan.transactions[0]
    assert (action.side, action.quantity, action.reason) == ("buy", 10.0, "imported holding")
