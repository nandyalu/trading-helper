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
    # When the oldest still-open lot was bought. The trade horizon is one to
    # two weeks, so a position's age is the difference between holding it and
    # forgetting about it — nothing else in the book says a thesis has expired.
    opened: datetime.date | None = None

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

    def held_days(self, today: datetime.date | None = None) -> int | None:
        if self.opened is None:
            return None
        return ((today or datetime.date.today()) - self.opened).days


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

    def weight_pct(self, holding: Holding) -> float | None:
        """What share of the whole account one position is.

        Shown to the model rather than capped, because allocation is its call —
        but it put 98% of the budget into one stock without ever being told
        that was what it was doing.
        """
        value = holding.market_value if holding.market_value is not None else holding.cost_basis
        return (value / self.equity * 100) if self.equity else None


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
            # The oldest open lot: a position topped up last week is still a
            # position opened a month ago, and the thesis is that old too.
            opened = min(
                (lot.date for lot in position.open_lots if lot.date), default=None
            )
            if isinstance(opened, str):
                opened = datetime.date.fromisoformat(opened)
            holdings.append(
                Holding(
                    ticker=ticker,
                    quantity=position.quantity,
                    avg_cost=position.avg_cost,
                    price=price_lookup(ticker) if price_lookup else None,
                    opened=opened,
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
class TradeRow:
    """One lot's life: bought, and sold or still held.

    Open and closed rows come from the same FIFO walk deliberately. Computing
    them separately is how a "still holding" table and a realized-P/L table end
    up disagreeing about the same shares.
    """

    ticker: str
    quantity: float
    entry: float
    entry_at: datetime.datetime
    exit: float | None = None
    exit_at: datetime.datetime | None = None
    signal_decision: str | None = None  # what the analyst said when it bought
    signal_id: int | None = None  # the signal the lot was opened on

    @property
    def is_open(self) -> bool:
        return self.exit is None

    @property
    def pnl(self) -> float | None:
        """None while open. An unrealized number here would be mistaken for a
        booked one — the holdings table above already shows unrealized."""
        return None if self.is_open else (self.exit - self.entry) * self.quantity

    @property
    def return_pct(self) -> float | None:
        if self.is_open or not self.entry:
            return None
        return (self.exit / self.entry - 1) * 100

    @property
    def held_days(self) -> int:
        """To the exit, or to today while it is still held."""
        end = self.exit_at.date() if self.exit_at else datetime.date.today()
        return (end - self.entry_at.date()).days

    @property
    def won(self) -> bool:
        return (self.pnl or 0) > 0


# The old name, kept because the prompt and its tests read closed rows.
ClosedTrade = TradeRow


def trade_history(trades=None, decisions: dict[int, str] | None = None) -> list[TradeRow]:
    """Every lot the agent has opened, closed ones and still-held ones, oldest
    first.

    Matching is FIFO to agree with compute_position, so the realized P/L summed
    here equals the realized P/L on the book rather than drifting from it.
    """
    rows = trades if trades is not None else db.get_agent_trades()
    decisions = decisions or {}
    # ticker -> [[remaining_qty, price, filled_at, decision, signal_id], ...]
    open_lots: dict[str, list[list]] = {}
    history: list[TradeRow] = []

    for trade in rows:
        if trade.status != "filled" or trade.price is None:
            continue
        # A resting stop or take-profit that filled is a real exit and must be
        # matched like any other sell.
        when = trade.filled_at or trade.placed_at
        if trade.side == "buy":
            open_lots.setdefault(trade.ticker, []).append(
                [trade.quantity, trade.price, when, decisions.get(trade.signal_id), trade.signal_id]
            )
            continue
        remaining = trade.quantity
        lots = open_lots.get(trade.ticker, [])
        while remaining > _QUANTITY_EPSILON and lots:
            lot = lots[0]
            matched = min(lot[0], remaining)
            history.append(
                TradeRow(
                    ticker=trade.ticker,
                    quantity=matched,
                    entry=lot[1],
                    entry_at=lot[2],
                    exit=trade.price,
                    exit_at=when,
                    signal_decision=lot[3],
                    signal_id=lot[4],
                )
            )
            lot[0] -= matched
            remaining -= matched
            if lot[0] <= _QUANTITY_EPSILON:
                lots.pop(0)

    for ticker, lots in open_lots.items():
        for quantity, price, when, decision, signal_id in lots:
            if quantity > _QUANTITY_EPSILON:
                history.append(
                    TradeRow(
                        ticker=ticker,
                        quantity=quantity,
                        entry=price,
                        entry_at=when,
                        signal_decision=decision,
                        signal_id=signal_id,
                    )
                )

    history.sort(key=lambda r: r.entry_at)
    return history


def closed_trades(trades=None, decisions: dict[int, str] | None = None) -> list[TradeRow]:
    """Completed round trips only — what the agent is shown about its own
    record. An open lot has no outcome to learn from yet."""
    return [row for row in trade_history(trades, decisions) if not row.is_open]


def trades_for_signal(signal_id: int) -> list[TradeRow]:
    """What the agent actually did with one signal's call.

    The signal's own grade answers whether the analysis was right over its
    horizon; this answers what the exit rules made of it. They are deliberately
    separate — resolving a signal the moment a stop fires would end every loser
    early and let every winner run to full term, which measures stop placement
    rather than the prediction. Seeing both is what makes a PASS beside a
    losing trade legible as "the call was right, the stop was too tight".

    Only lots opened on this signal count. A sell carries no signal_id, so the
    exit that closed the lot is found by the FIFO match rather than by id.
    """
    return [row for row in trade_history() if row.signal_id == signal_id]
