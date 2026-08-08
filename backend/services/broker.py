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
# Kept because it costs nothing and a future payload may add one. The real fix
# is the Order History endpoint (docs/reference/order-history.md), which has
# symbol / side / filled_quantity / filled_price / filled_time_at going back to
# 2018 — see CLAUDE.md. Until that exists, backend/scripts/fix_import_dates.py
# is how a real date gets set.
_OPENED_AT_KEYS = ("open_date", "position_date", "opened_at", "open_time", "created_time", "trade_date")


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


def fetch_broker_positions() -> list[BrokerPosition] | None:
    """Merged equity positions across all non-crypto accounts; None when the
    client isn't configured or the API fails (callers report, don't guess)."""
    api_client = get_api_client()
    if api_client is None:
        return None
    try:
        from webull.trade.trade.v2.account_info_v2 import AccountV2

        account_v2 = AccountV2(api_client)
        accounts = account_v2.get_account_list().json() or []
        if isinstance(accounts, dict):
            accounts = accounts.get("data") or []
        merged: dict[str, BrokerPosition] = {}
        for account in accounts:
            if "CRYPTO" in str(account.get("account_class", "")).upper():
                continue
            account_id = account.get("account_id") or account.get("id")
            if not account_id:
                continue
            rows = account_v2.get_account_position(account_id).json() or []
            if isinstance(rows, dict):
                rows = rows.get("data") or []
            for raw in rows:
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


def plan_sync(
    broker_positions: list[BrokerPosition],
    bot_quantities: dict[str, float],
    watchlist: list[str],
) -> SyncPlan:
    """``bot_quantities`` maps every ticker with transactions to its current
    open quantity (0 for fully closed)."""
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
            reason = "imported holding" if imported else "quantity drift"
            # A first import is shares bought at some unknown past date. Say so
            # when the broker didn't tell us, rather than recording it as bought
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
    plan = plan_sync(positions, bot_quantities, db.get_watchlist())

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
