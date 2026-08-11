"""The agent's budget, cash, and holdings — derived, never read from the broker.

The simulated account is funded with $1,000,000. The agent is given a few
hundred. So every number the agent is allowed to reason about has to come from
this module, computed over the orders it actually placed, and never from the
account's buying power — which would tell it that it can spend a thousand times
its budget.

Cash is ``budget − filled buys + filled sells``. Only filled rows count: a
market order placed after the close sits pending until the open, and counting
it early would let the agent spend the same dollar twice in one evening.

Holdings reuse positions.compute_position, the same FIFO the real book uses, so
realized P/L and average cost mean exactly what they mean everywhere else.
"""
import datetime
import logging
from dataclasses import dataclass, field

from backend.database import db
from backend.services.positions import compute_position

log = logging.getLogger("trading-bot.agent_book")

_BUDGET_SETTING_KEY = "agent_budget"
DEFAULT_BUDGET = 1000.0

# Cash below this can't buy a share of anything worth owning, and floating
# point makes exact-zero comparisons unreliable after a few round trips.
_CASH_EPSILON = 0.01
_QUANTITY_EPSILON = 1e-6


@dataclass
class Holding:
    ticker: str
    quantity: float
    avg_cost: float
    price: float | None = None  # current market price, None when unavailable

    @property
    def market_value(self) -> float | None:
        return None if self.price is None else self.quantity * self.price

    @property
    def cost_basis(self) -> float:
        return self.quantity * self.avg_cost

    @property
    def unrealized_pnl(self) -> float | None:
        value = self.market_value
        return None if value is None else value - self.cost_basis


@dataclass
class Book:
    budget: float
    cash: float
    realized_pnl: float
    holdings: list[Holding] = field(default_factory=list)

    @property
    def invested(self) -> float:
        return sum(h.cost_basis for h in self.holdings)

    @property
    def market_value(self) -> float:
        """Priced holdings only. An unpriced holding contributes its cost
        basis rather than zero — treating it as worthless would understate
        equity and could make the agent panic-sell what it can still see."""
        return sum(
            h.market_value if h.market_value is not None else h.cost_basis for h in self.holdings
        )

    @property
    def equity(self) -> float:
        return self.cash + self.market_value

    @property
    def return_pct(self) -> float:
        return (self.equity / self.budget - 1) * 100 if self.budget else 0.0


def get_budget() -> float:
    stored = db.get_setting(_BUDGET_SETTING_KEY)
    try:
        return float(stored) if stored else DEFAULT_BUDGET
    except (TypeError, ValueError):
        log.warning("Ignoring unparseable agent_budget %r", stored)
        return DEFAULT_BUDGET


def set_budget(budget: float) -> None:
    if budget <= 0:
        raise ValueError("Budget must be positive.")
    db.set_setting(_BUDGET_SETTING_KEY, str(float(budget)))


def _as_transactions(trades) -> dict[str, list[dict]]:
    """Filled trades grouped by ticker, in the shape compute_position wants."""
    by_ticker: dict[str, list[dict]] = {}
    for trade in trades:
        if trade.status != "filled" or trade.price is None:
            continue
        by_ticker.setdefault(trade.ticker, []).append(
            {
                "side": trade.side,
                "date": (trade.filled_at or trade.placed_at).date(),
                "price": trade.price,
                "quantity": trade.quantity,
                "note": None,
            }
        )
    return by_ticker


def build_book(price_lookup=None) -> Book:
    """The agent's current book. ``price_lookup`` is a ticker -> price|None
    callable; omitted, holdings come back unpriced, which every consumer
    already handles (an unpriced holding is counted at cost)."""
    budget = get_budget()
    trades = db.get_agent_trades()
    spent = sum(t.quantity * t.price for t in trades if t.status == "filled" and t.price and t.side == "buy")
    received = sum(t.quantity * t.price for t in trades if t.status == "filled" and t.price and t.side == "sell")

    holdings: list[Holding] = []
    realized = 0.0
    for ticker, transactions in sorted(_as_transactions(trades).items()):
        position = compute_position(transactions)
        realized += position.realized_pnl
        if position.quantity > _QUANTITY_EPSILON:
            holdings.append(
                Holding(
                    ticker=ticker,
                    quantity=position.quantity,
                    avg_cost=position.avg_cost,
                    price=price_lookup(ticker) if price_lookup else None,
                )
            )

    return Book(budget=budget, cash=budget - spent + received, realized_pnl=realized, holdings=holdings)


@dataclass
class Rejection:
    ticker: str
    side: str
    quantity: float
    why: str


def validate(order: dict, book: Book, price: float | None) -> Rejection | None:
    """Whether an order the model asked for is *possible*. Not whether it is
    wise — allocation is the model's call (see backend/services/agent.py); this
    only refuses orders that cannot be executed as stated.

    Returns None when the order is fine, or the reason it isn't.
    """
    ticker = str(order.get("ticker", "")).upper().strip()
    side = str(order.get("side", "")).lower().strip()
    try:
        quantity = float(order.get("quantity", 0))
    except (TypeError, ValueError):
        quantity = 0.0

    def no(why: str) -> Rejection:
        return Rejection(ticker=ticker, side=side, quantity=quantity, why=why)

    if not ticker:
        return no("no ticker given")
    if side not in ("buy", "sell"):
        return no(f"side must be buy or sell, got {side!r}")
    if quantity <= 0:
        return no(f"quantity must be positive, got {quantity}")
    if quantity != int(quantity):
        return no(f"whole shares only, got {quantity}")

    if side == "sell":
        held = next((h.quantity for h in book.holdings if h.ticker == ticker), 0.0)
        if quantity > held + _QUANTITY_EPSILON:
            return no(f"holds {held:g} shares, cannot sell {quantity:g} (no shorting)")
        return None

    if price is None:
        return no("no price available, so the cost can't be checked against cash")
    cost = quantity * price
    if cost > book.cash + _CASH_EPSILON:
        return no(f"costs ${cost:,.2f} but only ${book.cash:,.2f} is uninvested")
    return None


@dataclass
class ClosedTrade:
    """One completed round trip: bought, then sold."""

    ticker: str
    quantity: float
    entry: float
    exit: float
    opened: datetime.date
    closed: datetime.date
    signal_decision: str | None = None  # what the analyst said when it bought

    @property
    def pnl(self) -> float:
        return (self.exit - self.entry) * self.quantity

    @property
    def return_pct(self) -> float:
        return (self.exit / self.entry - 1) * 100 if self.entry else 0.0

    @property
    def held_days(self) -> int:
        return (self.closed - self.opened).days

    @property
    def won(self) -> bool:
        return self.pnl > 0


def closed_trades(trades=None, decisions: dict[int, str] | None = None) -> list[ClosedTrade]:
    """Completed round trips, oldest first, matched FIFO.

    The agent has no memory otherwise: every morning it wakes with a book and
    no idea that the last four things it bought on a Hold signal all lost
    money. This is the raw material for telling it — see agent.build_prompt.

    Matching is FIFO to agree with compute_position, so the realized P/L summed
    here equals the realized P/L on the book rather than diverging from it.
    """
    rows = trades if trades is not None else db.get_agent_trades()
    decisions = decisions or {}
    open_lots: dict[str, list[list]] = {}  # ticker -> [[qty, price, date, decision], ...]
    closed: list[ClosedTrade] = []

    for trade in rows:
        if trade.status != "filled" or trade.price is None:
            continue
        when = (trade.filled_at or trade.placed_at).date()
        if trade.side == "buy":
            open_lots.setdefault(trade.ticker, []).append(
                [trade.quantity, trade.price, when, decisions.get(trade.signal_id)]
            )
            continue
        remaining = trade.quantity
        lots = open_lots.get(trade.ticker, [])
        while remaining > _QUANTITY_EPSILON and lots:
            lot = lots[0]
            matched = min(lot[0], remaining)
            closed.append(
                ClosedTrade(
                    ticker=trade.ticker,
                    quantity=matched,
                    entry=lot[1],
                    exit=trade.price,
                    opened=lot[2],
                    closed=when,
                    signal_decision=lot[3],
                )
            )
            lot[0] -= matched
            remaining -= matched
            if lot[0] <= _QUANTITY_EPSILON:
                lots.pop(0)
    return closed
