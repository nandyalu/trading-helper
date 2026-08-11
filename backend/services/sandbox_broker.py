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


def get_order_detail(client_order_id: str) -> dict | None:
    """Look one order up so the fill price can be recorded. The order is placed
    at market, so the price is only knowable after the fact."""
    _assert_sandbox()
    client = quotes.get_api_client()
    account_id = get_paper_account_id()
    if client is None or account_id is None:
        return None
    from webull.trade.trade.v3.order_opration_v3 import OrderOperationV3

    response = OrderOperationV3(client).get_order_detail(account_id, client_order_id)
    body = response.json() if hasattr(response, "json") else response
    return body if isinstance(body, dict) else None
