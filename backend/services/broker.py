"""Webull account sync (read-only — the bot never places orders). Pulls the
real holdings from every non-crypto account via the Trade API, then:

- adds every held equity to the watchlist so the daily sweep, watchdog, and
  earnings triggers generate signals for it, and
- reconciles the bot's transaction log *additively*: unknown holdings are
  imported as a synthetic buy at broker avg cost, quantity drifts get a
  delta transaction at broker prices — but positions the bot knows that
  Webull doesn't hold are only reported, never auto-sold (they may live at
  another broker or be manually tracked).

``plan_sync`` is pure and unit-tested; ``run_sync`` does the I/O. All
blocking — call via asyncio.to_thread.
"""
import datetime
import logging
import time
from dataclasses import dataclass, field

from backend.database import db
from backend.services.positions import ESTIMATED_DATE_NOTE, compute_position
from backend.services.quotes import get_api_client

log = logging.getLogger("trading-bot.broker")

_EPSILON = 1e-6
_SYNC_NOTE = "webull sync"


@dataclass
class BrokerPosition:
    symbol: str
    quantity: float
    cost_price: float
    last_price: float | None = None
    opened_at: datetime.date | None = None  # None when the payload carries no date


@dataclass
class BrokerFill:
    """One executed order, from the Order History endpoint.

    This is where purchase dates actually live — a position snapshot carries
    none. Fields map to the documented response: ``symbol``, ``side``,
    ``filled_quantity``, ``filled_price``, ``filled_time_at``.
    """

    symbol: str
    side: str  # "buy" | "sell", normalized from BUY/SELL/SHORT
    date: datetime.date
    price: float
    quantity: float


# Order History reaches back only this far, per the API docs. A holding bought
# before it — or transferred in from another broker — has no fill to find, and
# falls back to the date-unknown path.
_ORDER_HISTORY_EPOCH = datetime.date(2018, 5, 21)

# The docs put Order History at 2 requests per 2 seconds. Pacing at exactly
# that got a 429 in practice, so leave real headroom — this runs once a day at
# most, and only when there is a holding to import.
#
# page_size is rejected outside 10..100 (HTTP 417, OAUTH_OPENAPI_PARAM_ERR).
_ORDER_HISTORY_PAGE_SIZE = 100
_ORDER_HISTORY_PAUSE = 2.5
# A guard against paging forever if the cursor ever stops advancing.
_ORDER_HISTORY_MAX_PAGES = 60


# Candidate keys for the date a position was opened.
#
# **None of these exist.** The Account Positions response is documented at
# https://developer.webull.com/apis/docs/reference/account-position.md and
# carries no acquisition date under any name — only position_id, currency,
# quantity, symbol, option_strategy, instrument_type, last_price, cost_price,
# unrealized_profit_loss, event_outcome, legs. These keys were guesses made
# before the schema was checked, so in practice every synced holding takes the
# "(date unknown)" path below.
#
# Kept because it costs nothing and a future payload may add one. The dates the
# sync actually uses come from Order History instead — see fetch_order_fills
# and reconstruct_open_lots below.
_OPENED_AT_KEYS = (
    "open_date", "position_date", "opened_at", "open_time", "created_time", "trade_date",
    # Order History does carry these two, and _parse_fill reads them through
    # the same parser so ISO strings and epoch millis are handled once.
    "filled_time_at", "filled_time",
)


def _parse_opened_at(raw: dict) -> datetime.date | None:
    """Best-effort date extraction. Accepts an ISO date/datetime string or an
    epoch in seconds or milliseconds; returns None for anything else, and for a
    date in the future (a clock or unit mix-up, not a real purchase)."""
    for key in _OPENED_AT_KEYS:
        value = raw.get(key)
        if value in (None, ""):
            continue
        parsed: datetime.date | None = None
        if isinstance(value, (int, float)) or str(value).isdigit():
            epoch = float(value)
            if epoch > 1e11:  # milliseconds
                epoch /= 1000
            try:
                parsed = datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).date()
            except (OverflowError, OSError, ValueError):
                continue
        else:
            try:
                parsed = datetime.date.fromisoformat(str(value)[:10])
            except ValueError:
                continue
        if parsed and parsed <= datetime.date.today():
            return parsed
    return None


# --- Fetch (blocking) -----------------------------------------------------------


def is_configured() -> bool:
    return get_api_client() is not None


def _parse_position(raw: dict) -> BrokerPosition | None:
    try:
        symbol = str(raw.get("symbol", "")).strip().upper()
        quantity = float(raw.get("quantity", 0))
        cost_price = float(raw.get("cost_price", 0))
        last_raw = raw.get("last_price")
        last_price = float(last_raw) if last_raw not in (None, "") else None
    except (TypeError, ValueError):
        return None
    if raw.get("instrument_type") not in (None, "EQUITY"):
        return None
    # Real US tickers are 1–5 letters; things like CVR remnants ("RGLSCVR12WB",
    # last_price 0) aren't analyzable or tradeable — skip them.
    if not symbol.isalpha() or len(symbol) > 5:
        log.info("Skipping non-standard holding %s", symbol)
        return None
    if quantity <= _EPSILON or cost_price <= 0:
        return None
    return BrokerPosition(
        symbol=symbol,
        quantity=quantity,
        cost_price=cost_price,
        last_price=last_price,
        opened_at=_parse_opened_at(raw),
    )


def _rows(response) -> list[dict]:
    """Webull answers either a bare list or ``{"data": [...]}`` depending on
    the endpoint; normalize both."""
    payload = response.json() or []
    if isinstance(payload, dict):
        payload = payload.get("data") or []
    return [row for row in payload if isinstance(row, dict)]


def _tradeable_account_ids(account_v2) -> list[str]:
    """Non-crypto account ids. Crypto accounts are skipped everywhere here —
    this app is equities-only."""
    ids = []
    for account in _rows(account_v2.get_account_list()):
        if "CRYPTO" in str(account.get("account_class", "")).upper():
            continue
        account_id = account.get("account_id") or account.get("id")
        if account_id:
            ids.append(account_id)
    return ids


def orders_in(row: dict) -> list[dict]:
    """The individual orders inside one order-history row.

    The endpoint returns *combo* wrappers, not orders: each row carries
    ``client_order_id`` / ``combo_type`` / ``combo_order_id`` and an ``orders``
    list holding the real order objects. A single-leg order is still wrapped in
    a one-element list, so there is no flat case to special-case. The docs hint
    at this only obliquely ("if they are group orders, will be returned
    together"), and reading the top level instead finds no symbol, no side and
    no quantity — every row parses to nothing.
    """
    orders = row.get("orders")
    if isinstance(orders, list):
        return [order for order in orders if isinstance(order, dict)]
    return [row] if "symbol" in row else []


def _parse_fill(raw: dict) -> BrokerFill | None:
    """One *order* (not one row — see orders_in) to a BrokerFill, or None when
    it isn't a usable equity fill. Cancelled and still-open orders carry a
    ``filled_quantity`` of 0 and are dropped; a partial fill keeps the shares
    that did execute."""
    side = str(raw.get("side", "")).strip().upper()
    if side not in ("BUY", "SELL"):
        return None  # SHORT and the rest: this app is long-only
    if raw.get("instrument_type") not in (None, "", "EQUITY"):
        return None
    symbol = str(raw.get("symbol", "")).strip().upper()
    if not symbol.isalpha() or len(symbol) > 5:
        return None
    try:
        quantity = float(raw.get("filled_quantity") or 0)
        price = float(raw.get("filled_price") or 0)
    except (TypeError, ValueError):
        return None
    if quantity <= _EPSILON or price <= 0:
        return None
    filled_at = _parse_opened_at({"filled_time_at": raw.get("filled_time_at")}) or _parse_opened_at(
        {"filled_time": raw.get("filled_time")}
    )
    if filled_at is None:
        return None  # a fill with no date is the thing we came here for
    return BrokerFill(
        symbol=symbol, side=side.lower(), date=filled_at, price=price, quantity=quantity
    )


def fetch_order_fills(start_date: datetime.date | None = None) -> list[BrokerFill] | None:
    """Executed equity orders across all non-crypto accounts, oldest first.

    This is the only place Webull exposes *when* shares were bought — a
    position snapshot carries no acquisition date at all. Without it, an
    imported holding has to be dated the day the sync ran, which anchors its
    benchmark entry on that date and inflates the vs-SPY alpha to nonsense.

    Read-only. ``OrderOperationV2`` also exposes place/cancel; nothing here
    calls them, and real order execution is a standing non-goal.

    None when the client isn't configured or the API fails — callers report
    that rather than guessing.
    """
    api_client = get_api_client()
    if api_client is None:
        return None
    start = max(start_date or _ORDER_HISTORY_EPOCH, _ORDER_HISTORY_EPOCH)
    today = datetime.date.today()
    try:
        from webull.trade.trade.v2.account_info_v2 import AccountV2
        from webull.trade.trade.v2.order_operation_v2 import OrderOperationV2

        order_v2 = OrderOperationV2(api_client)
        fills: list[BrokerFill] = []
        for account_id in _tradeable_account_ids(AccountV2(api_client)):
            cursor = None
            for page in range(_ORDER_HISTORY_MAX_PAGES):
                if page:
                    time.sleep(_ORDER_HISTORY_PAUSE)  # documented 2 requests / 2 seconds
                rows = _rows(
                    order_v2.get_order_history(
                        account_id,
                        page_size=_ORDER_HISTORY_PAGE_SIZE,
                        start_date=start.isoformat(),
                        end_date=today.isoformat(),
                        last_client_order_id=cursor,
                    )
                )
                if not rows:
                    break
                fills.extend(
                    fill
                    for row in rows
                    for order in orders_in(row)
                    if (fill := _parse_fill(order)) is not None
                )
                next_cursor = rows[-1].get("client_order_id")
                if not next_cursor or next_cursor == cursor:
                    break  # cursor stopped advancing; stop rather than loop
                cursor = next_cursor
            else:
                log.warning(
                    "Order history for account %s hit the %d-page cap; older fills ignored",
                    account_id, _ORDER_HISTORY_MAX_PAGES,
                )
        return sorted(fills, key=lambda f: (f.date, f.symbol))
    except Exception:
        log.exception("Webull order-history fetch failed")
        return None


def fetch_broker_positions() -> list[BrokerPosition] | None:
    """Merged equity positions across all non-crypto accounts; None when the
    client isn't configured or the API fails (callers report, don't guess)."""
    api_client = get_api_client()
    if api_client is None:
        return None
    try:
        from webull.trade.trade.v2.account_info_v2 import AccountV2

        account_v2 = AccountV2(api_client)
        merged: dict[str, BrokerPosition] = {}
        for account_id in _tradeable_account_ids(account_v2):
            for raw in _rows(account_v2.get_account_position(account_id)):
                position = _parse_position(raw)
                if position is None:
                    continue
                existing = merged.get(position.symbol)
                if existing is None:
                    merged[position.symbol] = position
                else:
                    total = existing.quantity + position.quantity
                    existing.cost_price = (
                        existing.cost_price * existing.quantity + position.cost_price * position.quantity
                    ) / total
                    existing.quantity = total
        return sorted(merged.values(), key=lambda p: p.symbol)
    except Exception:
        log.exception("Webull position fetch failed")
        return None


# --- Reconciliation (pure) -------------------------------------------------------


@dataclass
class SyncAction:
    ticker: str
    side: str  # "buy" | "sell"
    price: float
    quantity: float
    reason: str
    date: datetime.date | None = None  # None when the broker gave no date


@dataclass
class SyncPlan:
    watchlist_adds: list[str] = field(default_factory=list)
    transactions: list[SyncAction] = field(default_factory=list)
    bot_only: list[str] = field(default_factory=list)  # open in bot, absent at Webull

    @property
    def has_changes(self) -> bool:
        return bool(self.watchlist_adds or self.transactions or self.bot_only)


def reconstruct_open_lots(
    position: BrokerPosition, fills: list[BrokerFill]
) -> list[SyncAction]:
    """The buys that make up a holding's currently-open shares, oldest first.

    FIFO sells the oldest shares first, so what is still held is the *newest*
    buys. Walking the buy fills newest-first until they cover the broker's
    quantity reconstructs the open lots — with their real dates and their real
    fill prices, which is strictly better than one synthetic lot at the
    broker's blended average.

    Anything the fills cannot account for — shares bought before Order
    History's 2018 horizon, or transferred in from another broker — comes back
    as a single remainder lot marked date-unknown, so it is excluded from the
    benchmark comparison instead of corrupting it.

    Returns an empty list for a non-positive quantity.
    """
    remaining = position.quantity
    if remaining <= _EPSILON:
        return []

    buys = sorted(
        (f for f in fills if f.symbol == position.symbol and f.side == "buy"),
        key=lambda f: f.date,
        reverse=True,
    )

    lots: list[SyncAction] = []
    for fill in buys:
        if remaining <= _EPSILON:
            break
        take = min(fill.quantity, remaining)
        lots.append(
            SyncAction(
                position.symbol, "buy", fill.price, take, "imported fill", date=fill.date
            )
        )
        remaining -= take

    lots.reverse()  # oldest first, so the transaction log reads chronologically

    if remaining > _EPSILON:
        lots.append(
            SyncAction(
                position.symbol,
                "buy",
                position.cost_price,
                remaining,
                f"imported holding ({ESTIMATED_DATE_NOTE})",
                date=None,
            )
        )
    return lots


def plan_sync(
    broker_positions: list[BrokerPosition],
    bot_quantities: dict[str, float],
    watchlist: list[str],
    fills: list[BrokerFill] | None = None,
) -> SyncPlan:
    """``bot_quantities`` maps every ticker with transactions to its current
    open quantity (0 for fully closed).

    ``fills`` is executed order history. When supplied, a first import is
    rebuilt from the real buys behind the position rather than recorded as one
    lot dated today — see reconstruct_open_lots.
    """
    plan = SyncPlan()
    held_symbols = set()
    for position in broker_positions:
        held_symbols.add(position.symbol)
        if position.symbol not in watchlist:
            plan.watchlist_adds.append(position.symbol)
        bot_quantity = bot_quantities.get(position.symbol, 0.0)
        delta = position.quantity - bot_quantity
        if abs(delta) <= _EPSILON:
            continue
        if delta > 0:
            imported = bot_quantity <= _EPSILON
            if imported and fills is not None:
                # Real dates and real fill prices, reconstructed from history.
                plan.transactions.extend(reconstruct_open_lots(position, fills))
                continue
            reason = "imported holding" if imported else "quantity drift"
            # A first import is shares bought at some unknown past date. Say so
            # when nothing told us otherwise, rather than recording it as bought
            # today — a wrong date silently inflates the vs-SPY alpha, because
            # the benchmark gets days to move while the position is credited
            # with months of gains. Drift is genuinely new, so today is right.
            if imported and position.opened_at is None:
                reason = f"imported holding ({ESTIMATED_DATE_NOTE})"
            plan.transactions.append(
                SyncAction(
                    position.symbol,
                    "buy",
                    position.cost_price,
                    delta,
                    reason,
                    date=position.opened_at if imported else None,
                )
            )
        else:
            # Broker holds less than the bot thinks: mirror the reduction at
            # the broker's last price (best available approximation).
            price = position.last_price or position.cost_price
            plan.transactions.append(
                SyncAction(position.symbol, "sell", price, -delta, "quantity drift")
            )
    plan.bot_only = sorted(
        ticker
        for ticker, quantity in bot_quantities.items()
        if quantity > _EPSILON and ticker not in held_symbols
    )
    return plan


# --- Apply (blocking) --------------------------------------------------------------


def run_sync() -> str | None:
    """Fetch, reconcile, apply. Returns a Discord-ready summary, or None when
    the broker isn't configured/reachable."""
    positions = fetch_broker_positions()
    if positions is None:
        return None
    bot_quantities = {
        ticker: compute_position(db.get_transactions(ticker)).quantity
        for ticker in db.get_all_transaction_tickers()
    }
    # Only worth the paging cost when there is a first import to date. On a
    # steady-state sync every holding is already known and nothing would use
    # the fills, so the requests would be pure waste.
    first_imports = [
        p for p in positions if bot_quantities.get(p.symbol, 0.0) <= _EPSILON
    ]
    fills = fetch_order_fills() if first_imports else None
    if first_imports and fills is None:
        log.warning(
            "Order history unavailable; importing %d holding(s) without purchase dates",
            len(first_imports),
        )
    plan = plan_sync(positions, bot_quantities, db.get_watchlist(), fills=fills)

    for ticker in plan.watchlist_adds:
        db.add_to_watchlist(ticker)
    for action in plan.transactions:
        db.add_transaction(
            action.ticker,
            action.side,
            action.price,
            action.quantity,
            date=action.date,
            note=f"{_SYNC_NOTE}: {action.reason}",
        )

    lines = [f"🔄 Webull sync — {len(positions)} equity holding(s)."]
    if plan.watchlist_adds:
        lines.append(f"Now tracking: {', '.join(plan.watchlist_adds)}")
    for action in plan.transactions:
        lines.append(
            f"{action.side.capitalize()} {action.quantity:g} {action.ticker} "
            f"@ ${action.price:,.2f} ({action.reason})"
        )
    if plan.bot_only:
        lines.append(
            f"⚠️ In the bot but not held at Webull: {', '.join(plan.bot_only)} — "
            f"not auto-sold; close with /sell if they're really gone."
        )
    if not plan.has_changes:
        lines.append("Everything already in sync.")
    return "\n".join(lines)
