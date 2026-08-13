"""Order execution against Webull's simulated (sandbox) account.

This is the only module in the app that places orders, and it refuses to do
anything unless ``quotes.is_sandbox()`` is true. That check is not a
convenience — it is the guarantee. Production credentials and sandbox
credentials are different key pairs pointing at different hosts
(api.webull.com vs api.sandbox.webull.com), so with the sandbox flag off there
is no simulated account to reach and every order would land on real money.

Two further belts, because one flag is one typo away from being wrong:

- The target account is resolved by ``account_class == INDIVIDUAL_CASH``, never
  hardcoded, and the resolver rejects any account whose number doesn't look
  like a simulated one (``DEM…``). A production individual-cash account is
  numbered 5NW31603; every sandbox account is DEM-prefixed.
- Every order goes through ``_assert_sandbox()`` immediately before the call,
  not merely at module import, so flipping the environment mid-process cannot
  leave a live client armed.

Field names come from the Place Order reference (developer.webull.com,
common-order-place), not from the SDK — the SDK passes dicts straight through
and validates nothing.
"""
import datetime
import logging
import uuid

from backend.services import quotes

log = logging.getLogger("trading-bot.sandbox_broker")

# The one account class this equities-only app trades. The sandbox also exposes
# Crypto, Futures, Events Cash, and Individual Margin accounts, none of which
# should ever receive an order from here.
_TRADEABLE_ACCOUNT_CLASS = "INDIVIDUAL_CASH"

# Every simulated account number observed on the sandbox host is DEM-prefixed.
# Treated as a required marker rather than a curiosity: if an account without
# it ever appears while the sandbox flag is on, something is wrong enough to
# stop rather than trade.
_SIMULATED_ACCOUNT_PREFIX = "DEM"

_account_id: str | None = None


class NotSandboxError(RuntimeError):
    """Raised instead of placing an order when the client isn't simulated."""


def _assert_sandbox() -> None:
    if not quotes.is_sandbox():
        raise NotSandboxError(
            "Refusing to place an order: WEBULL_SANDBOX is not set, so these "
            "credentials point at the real brokerage account."
        )


def _rows(response) -> list[dict]:
    """The list body of a Webull response, however it arrives."""
    body = response.json() if hasattr(response, "json") else response
    if isinstance(body, list):
        return [row for row in body if isinstance(row, dict)]
    if isinstance(body, dict):
        for key in ("data", "result", "list", "items"):
            value = body.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
    return []


def get_paper_account_id(*, refresh: bool = False) -> str | None:
    """The simulated individual-cash account, or None when it can't be
    resolved. Cached — the id is stable for the life of the credentials."""
    global _account_id
    if _account_id and not refresh:
        return _account_id
    _assert_sandbox()
    client = quotes.get_api_client()
    if client is None:
        return None
    from webull.trade.trade.v2.account_info_v2 import AccountV2

    for account in _rows(AccountV2(client).get_account_list()):
        if str(account.get("account_class", "")).upper() != _TRADEABLE_ACCOUNT_CLASS:
            continue
        number = str(account.get("account_number", ""))
        if not number.startswith(_SIMULATED_ACCOUNT_PREFIX):
            log.error(
                "Account %s is class %s but its number is not simulated — refusing to use it",
                number,
                _TRADEABLE_ACCOUNT_CLASS,
            )
            return None
        _account_id = str(account.get("account_id"))
        return _account_id
    log.error("No %s account found on the sandbox host", _TRADEABLE_ACCOUNT_CLASS)
    return None


def get_balance() -> dict | None:
    """Raw balance payload for the paper account. Used to reconcile, never to
    size an order — the simulated account is funded with $1,000,000 and the
    agent's budget is far smaller (see backend/services/agent_book.py)."""
    _assert_sandbox()
    client = quotes.get_api_client()
    account_id = get_paper_account_id()
    if client is None or account_id is None:
        return None
    from webull.trade.trade.v2.account_info_v2 import AccountV2

    response = AccountV2(client).get_account_balance(account_id)
    body = response.json() if hasattr(response, "json") else response
    return body if isinstance(body, dict) else None


def get_positions() -> dict[str, float] | None:
    """Symbol -> quantity actually held in the simulated account.

    The app keeps its own ledger and does not read positions to decide
    anything; this exists so the two can be compared. A disagreement means the
    ledger is wrong, which is worth knowing loudly.
    """
    _assert_sandbox()
    client = quotes.get_api_client()
    account_id = get_paper_account_id()
    if client is None or account_id is None:
        return None
    from webull.trade.trade.v2.account_info_v2 import AccountV2

    held: dict[str, float] = {}
    for row in _rows(AccountV2(client).get_account_position(account_id)):
        if str(row.get("instrument_type", "EQUITY")).upper() not in ("EQUITY", ""):
            continue
        symbol = str(row.get("symbol", "")).strip().upper()
        try:
            quantity = float(row.get("quantity", 0))
        except (TypeError, ValueError):
            continue
        if symbol and quantity:
            held[symbol] = held.get(symbol, 0.0) + quantity
    return held


def place_market_order(ticker: str, side: str, quantity: float) -> dict:
    """Place a day market order on the simulated account.

    Returns the broker's response with ``client_order_id`` echoed back, so the
    caller can tie its ledger row to the order even if the response shape
    changes. Raises rather than returning None on refusal — a silently skipped
    order would leave the ledger claiming a position that doesn't exist.
    """
    _assert_sandbox()
    side = side.upper()
    if side not in ("BUY", "SELL"):
        raise ValueError(f"side must be BUY or SELL, got {side!r}")
    if quantity <= 0:
        raise ValueError(f"quantity must be positive, got {quantity}")

    client = quotes.get_api_client()
    account_id = get_paper_account_id()
    if client is None or account_id is None:
        raise RuntimeError("No simulated account available to trade")

    from webull.trade.trade.v3.order_opration_v3 import OrderOperationV3

    # Whole shares only. The simulated venue accepts fractional quantities on
    # some symbols and rejects them on others, and a partially-supported order
    # type is not worth the reconciliation ambiguity.
    quantity_str = str(int(quantity))
    client_order_id = uuid.uuid4().hex
    order = {
        "client_order_id": client_order_id,
        "combo_type": "NORMAL",
        "instrument_type": "EQUITY",
        "entrust_type": "QTY",
        "symbol": ticker.upper().strip(),
        "market": "US",
        "side": side,
        "order_type": "MARKET",
        "time_in_force": "DAY",
        "quantity": quantity_str,
        "support_trading_session": "CORE",
    }
    log.info("Placing simulated %s %s x%s", side, order["symbol"], quantity_str)
    response = OrderOperationV3(client).place_order(account_id, [order])
    body = response.json() if hasattr(response, "json") else response
    return {
        "client_order_id": client_order_id,
        "placed_at": datetime.datetime.now(datetime.timezone.utc),
        "response": body,
    }


# How far above the market to set a bracket's entry limit. A MASTER leg cannot
# be a MARKET order (the broker answers INVALID_PARAMETER) and cannot be GTC
# either, so the entry is a marketable limit: priced through the offer, it
# behaves like a market order while capping what a fast tape can charge. A
# market order's slippage is unbounded, which on an app-enforced budget is the
# worse of the two.
ENTRY_LIMIT_BUFFER_PCT = 0.5


def place_bracket_order(
    ticker: str,
    quantity: float,
    price: float,
    stop_price: float | None = None,
    target_price: float | None = None,
) -> dict:
    """Buy, and rest the exits under it, in one submission.

    The broker holds the exits inactive until the entry fills and activates
    them itself, so there is no window in which the shares are owned and
    nothing is protecting them. Arming afterwards always had that window: on
    2026-08-13 both buys filled and neither got its exits, because the sell
    legs were validated while the account still held nothing and read as a new
    short.

    Three shapes the broker rejects, all found by testing against the sandbox
    and none of them documented:

    - a ``MASTER`` leg with ``order_type`` MARKET, or with ``time_in_force``
      GTC — hence the marketable limit above;
    - a stop at or above the entry limit (``TRADE_STOP_LOSS_PRICE_LT_OPENPRICE``),
      which is the broker's own version of the check the caller already makes;
    - **any combo at all when the cash is unsettled**
      (``CANT_USE_UNSETTLE_FUNDS_FOR_COMBO_ORDER``). A plain market order may
      be placed against unsettled proceeds; a combo may not. Selling to fund a
      buy in the same pass is something the agent is explicitly told it can do,
      so this is a routine refusal rather than an edge case, and the caller
      must have a path that still works when it happens.

    ``preview_order`` accepts every one of those, so it cannot be used to check
    a combo before placing it.

    Raises on refusal, like ``place_market_order`` — a silently skipped order
    would leave the ledger claiming a position that does not exist.
    """
    _assert_sandbox()
    if quantity <= 0:
        raise ValueError(f"quantity must be positive, got {quantity}")
    if price <= 0:
        raise ValueError(f"price must be positive, got {price}")
    if stop_price is None and target_price is None:
        raise ValueError("a bracket needs at least one exit level")

    entry_limit = round(price * (1 + ENTRY_LIMIT_BUFFER_PCT / 100), 2)
    # Both exits are read against the entry the broker will actually accept,
    # not the last trade — a stop that is under the market but over the limit
    # takes the whole combo down with it, buy included.
    if stop_price is not None and stop_price >= entry_limit:
        raise ValueError(f"stop {stop_price} is not below the entry limit {entry_limit}")
    if target_price is not None and target_price <= entry_limit:
        raise ValueError(f"target {target_price} is not above the entry limit {entry_limit}")

    client = quotes.get_api_client()
    account_id = get_paper_account_id()
    if client is None or account_id is None:
        raise RuntimeError("No simulated account available to trade")

    from webull.trade.trade.v3.order_opration_v3 import OrderOperationV3

    base = {
        "instrument_type": "EQUITY",
        "entrust_type": "QTY",
        "symbol": ticker.upper().strip(),
        "market": "US",
        "quantity": str(int(quantity)),
        "support_trading_session": "CORE",
    }
    entry = {
        **base,
        "client_order_id": uuid.uuid4().hex,
        "combo_type": "MASTER",
        "side": "BUY",
        "order_type": "LIMIT",
        "limit_price": f"{entry_limit:.2f}",
        "time_in_force": "DAY",
    }
    legs = [entry]
    if stop_price is not None:
        legs.append({
            **base,
            "client_order_id": uuid.uuid4().hex,
            "combo_type": "STOP_LOSS",
            "side": "SELL",
            "order_type": "STOP_LOSS",
            "stop_price": f"{stop_price:.2f}",
            # GTC: an exit that expired at tonight's close would protect the
            # position for an afternoon and then quietly stop existing.
            "time_in_force": "GTC",
        })
    if target_price is not None:
        legs.append({
            **base,
            "client_order_id": uuid.uuid4().hex,
            "combo_type": "STOP_PROFIT",
            "side": "SELL",
            "order_type": "LIMIT",
            "limit_price": f"{target_price:.2f}",
            "time_in_force": "GTC",
        })

    log.info(
        "Placing simulated bracket for %s x%s — entry limit %.2f, stop %s, target %s",
        base["symbol"], base["quantity"], entry_limit, stop_price, target_price,
    )
    response = OrderOperationV3(client).place_order(account_id, legs, uuid.uuid4().hex)
    body = response.json() if hasattr(response, "json") else response
    placed_at = datetime.datetime.now(datetime.timezone.utc)
    return {
        "client_order_id": entry["client_order_id"],
        "entry_limit": entry_limit,
        "placed_at": placed_at,
        "response": body,
        "exits": [
            {
                "client_order_id": leg["client_order_id"],
                "kind": "stop" if leg["order_type"] == "STOP_LOSS" else "target",
                "price": stop_price if leg["order_type"] == "STOP_LOSS" else target_price,
                "quantity": float(leg["quantity"]),
                "placed_at": placed_at,
            }
            for leg in legs[1:]
        ],
    }


def place_exit_bracket(
    ticker: str,
    quantity: float,
    stop_price: float | None = None,
    target_price: float | None = None,
) -> list[dict]:
    """Rest the exits for a position: a stop below and a take-profit above.

    Placed as one OCO combo when both levels exist, so the broker cancels the
    other leg the moment one fills. Two independent orders would leave a window
    where both are live — a gap through the target could fill the limit and
    leave a stop still trying to sell shares that are gone.

    The accepted pairing is combo_type STOP_LOSS + STOP_PROFIT, found by
    testing: OCO+OCO and MASTER+OCO are both rejected, though the docs list
    every one of those as a valid combo_type.

    Either level may be missing — the analysis states them only when it has a
    view — and whichever exists is placed on its own. Returns one entry per leg
    actually placed.
    """
    _assert_sandbox()
    if quantity <= 0:
        raise ValueError(f"quantity must be positive, got {quantity}")
    if stop_price is not None and stop_price <= 0:
        raise ValueError(f"stop price must be positive, got {stop_price}")
    if target_price is not None and target_price <= 0:
        raise ValueError(f"target price must be positive, got {target_price}")
    if stop_price is None and target_price is None:
        return []

    client = quotes.get_api_client()
    account_id = get_paper_account_id()
    if client is None or account_id is None:
        raise RuntimeError("No simulated account available to trade")

    from webull.trade.trade.v3.order_opration_v3 import OrderOperationV3

    bracket = stop_price is not None and target_price is not None
    base = {
        "instrument_type": "EQUITY",
        "entrust_type": "QTY",
        "symbol": ticker.upper().strip(),
        "market": "US",
        "side": "SELL",
        # GTC: an exit that expired at tonight's close would protect the
        # position for an afternoon and then quietly stop existing.
        "time_in_force": "GTC",
        "quantity": str(int(quantity)),
        "support_trading_session": "CORE",
    }

    legs: list[dict] = []
    if stop_price is not None:
        legs.append({
            **base,
            "client_order_id": uuid.uuid4().hex,
            "combo_type": "STOP_LOSS" if bracket else "NORMAL",
            "order_type": "STOP_LOSS",
            "stop_price": f"{stop_price:.2f}",
        })
    if target_price is not None:
        legs.append({
            **base,
            "client_order_id": uuid.uuid4().hex,
            "combo_type": "STOP_PROFIT" if bracket else "NORMAL",
            "order_type": "LIMIT",
            "limit_price": f"{target_price:.2f}",
        })

    combo_id = uuid.uuid4().hex if bracket else None
    log.info(
        "Placing simulated exits for %s x%s — stop %s, target %s",
        base["symbol"], quantity, stop_price, target_price,
    )
    if bracket:
        OrderOperationV3(client).place_order(account_id, legs, combo_id)
    else:
        OrderOperationV3(client).place_order(account_id, legs)

    placed_at = datetime.datetime.now(datetime.timezone.utc)
    return [
        {
            "client_order_id": leg["client_order_id"],
            "kind": "stop" if leg["order_type"] == "STOP_LOSS" else "target",
            "price": stop_price if leg["order_type"] == "STOP_LOSS" else target_price,
            "placed_at": placed_at,
        }
        for leg in legs
    ]


def cancel_order(client_order_id: str) -> bool:
    """Cancel a resting order. Used when a position is closed by other means —
    a stop left behind would try to sell shares that are no longer held."""
    _assert_sandbox()
    client = quotes.get_api_client()
    account_id = get_paper_account_id()
    if client is None or account_id is None:
        return False
    from webull.trade.trade.v3.order_opration_v3 import OrderOperationV3

    try:
        OrderOperationV3(client).cancel_order(account_id, client_order_id)
        return True
    except Exception:
        log.exception("Couldn't cancel %s", client_order_id)
        return False


def get_order_detail(client_order_id: str) -> dict | None:
    """The order itself, so the fill price can be recorded — placed at market,
    the price is only knowable after the fact.

    The endpoint answers with a *combo wrapper*, not an order: the status,
    price, and quantity all live inside a one-element ``orders`` list, and the
    top level carries none of them. Reading the top level finds a dict that
    looks plausible and parses to nothing, so every fill stays pending forever.
    ``broker.orders_in`` already unwraps this shape for order history; the same
    unwrapping is what this needs.
    """
    _assert_sandbox()
    client = quotes.get_api_client()
    account_id = get_paper_account_id()
    if client is None or account_id is None:
        return None
    from webull.trade.trade.v3.order_opration_v3 import OrderOperationV3

    from backend.services.broker import orders_in

    response = OrderOperationV3(client).get_order_detail(account_id, client_order_id)
    body = response.json() if hasattr(response, "json") else response
    if not isinstance(body, dict):
        return None
    orders = orders_in(body)
    return orders[0] if orders else None
