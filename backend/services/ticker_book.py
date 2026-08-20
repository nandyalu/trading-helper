"""Everything the app knows about one ticker's money: who holds it, what is
protecting it, and every lot ever opened in it.

The ticker page could already show the analysis — signals, alerts, the chart.
What it could not show was the position. Three books can hold the same stock:
your real account, the paper book, and the auto trader. Only the first two
reached the page, and the third is the one placing real orders, so opening
INTC showed a signal's stop next to no position while the agent held three
shares of it with nothing resting underneath.

The exits are the part worth being careful about. A signal's stop and a
broker's stop are different claims — one is what the analysis said, the other
is what will execute tonight — and showing the first where the second belongs
is how a naked position looks protected.

Everything here is blocking (DB + prices) — call via asyncio.to_thread.
"""
import datetime
from dataclasses import dataclass, field

from backend.database import db
from backend.services import agent_book
from backend.services.positions import compute_position

# Shares below this are rounding noise from a fractional sale.
_QUANTITY_EPSILON = 1e-9


@dataclass
class Lot:
    """One lot's life in one book, matched FIFO.

    The same shape for all three books so the page renders one table rather
    than three that drift apart. ``book`` says which one it came from, since a
    lot's meaning depends on it: a real one spent your money, a paper one
    never existed, and an agent one was nobody's decision but the model's.
    """

    book: str  # "real" | "paper" | "agent"
    quantity: float
    entry: float
    entry_at: datetime.date
    exit: float | None = None
    exit_at: datetime.date | None = None
    signal_id: int | None = None

    @property
    def is_open(self) -> bool:
        return self.exit is None

    @property
    def pnl(self) -> float | None:
        """None while open. An unrealized figure here would read as booked."""
        return None if self.is_open else (self.exit - self.entry) * self.quantity

    @property
    def return_pct(self) -> float | None:
        if self.is_open or not self.entry:
            return None
        return (self.exit / self.entry - 1) * 100

    @property
    def held_days(self) -> int:
        return ((self.exit_at or datetime.date.today()) - self.entry_at).days


def match_lots(book: str, fills: list[dict]) -> list[Lot]:
    """FIFO-match one book's fills into lots, closed and still-open alike.

    FIFO to agree with compute_position, so the realized P/L summed from these
    rows equals the realized P/L the position tiles show. Computing the two
    separately is how a "still holding" table and a realized-P/L table end up
    disagreeing about the same shares.

    ``fills`` are dicts of side, date, price, quantity, and optionally
    signal_id, oldest first. The date may be a date or an ISO string — the two
    transaction tables return one and the agent's ledger the other — and is
    normalized here so nothing downstream has to ask which book it came from.
    """
    open_lots: list[list] = []
    lots: list[Lot] = []
    for fill in fills:
        when = fill["date"]
        if isinstance(when, str):
            when = datetime.date.fromisoformat(when)
        if fill["side"] == "buy":
            open_lots.append([fill["quantity"], fill["price"], when, fill.get("signal_id")])
            continue
        remaining = fill["quantity"]
        while remaining > _QUANTITY_EPSILON and open_lots:
            lot = open_lots[0]
            matched = min(lot[0], remaining)
            lots.append(
                Lot(
                    book=book,
                    quantity=matched,
                    entry=lot[1],
                    entry_at=lot[2],
                    exit=fill["price"],
                    exit_at=when,
                    signal_id=lot[3],
                )
            )
            lot[0] -= matched
            remaining -= matched
            if lot[0] <= _QUANTITY_EPSILON:
                open_lots.pop(0)

    for quantity, price, when, signal_id in open_lots:
        if quantity > _QUANTITY_EPSILON:
            lots.append(
                Lot(book=book, quantity=quantity, entry=price, entry_at=when, signal_id=signal_id)
            )
    return lots


def _agent_fills(ticker: str) -> list[dict]:
    """The agent's filled orders in one ticker, as fills.

    A resting stop or take-profit that triggered is a real exit and is matched
    like any other sell — it is the most common way an agent lot closes, and
    dropping it would leave the lot open forever.
    """
    fills = []
    for trade in db.get_agent_trades():
        if trade.ticker != ticker or trade.status != "filled" or trade.price is None:
            continue
        fills.append(
            {
                "side": trade.side,
                "date": (trade.filled_at or trade.placed_at).date(),
                "price": trade.price,
                "quantity": trade.quantity,
                "signal_id": trade.signal_id,
            }
        )
    fills.sort(key=lambda f: f["date"])
    return fills


def lots_for(ticker: str) -> list[Lot]:
    """Every lot in this ticker across all three books, newest entry first."""
    ticker = ticker.upper().strip()
    lots: list[Lot] = []
    lots += match_lots("real", db.get_transactions(ticker))
    lots += match_lots("paper", db.get_paper_transactions(ticker))
    lots += match_lots("agent", _agent_fills(ticker))
    lots.sort(key=lambda lot: lot.entry_at, reverse=True)
    return lots


@dataclass
class RestingExit:
    kind: str  # "stop" | "target"
    price: float
    quantity: float


@dataclass
class AgentPosition:
    """What the auto trader holds in one ticker, and what is under it."""

    quantity: float
    avg_cost: float
    price: float | None = None
    opened: datetime.date | None = None
    exits: list[RestingExit] = field(default_factory=list)

    @property
    def market_value(self) -> float | None:
        return None if self.price is None else self.quantity * self.price

    @property
    def unrealized_pct(self) -> float | None:
        if self.price is None or not self.avg_cost:
            return None
        return (self.price / self.avg_cost - 1) * 100

    @property
    def held_days(self) -> int | None:
        return None if self.opened is None else (datetime.date.today() - self.opened).days

    def level(self, kind: str) -> float | None:
        return next((e.price for e in self.exits if e.kind == kind), None)

    @property
    def unprotected(self) -> bool:
        """Held with nothing resting under it at the broker.

        Worth stating rather than leaving to be inferred from two empty cells:
        the position is live, the money is at risk, and the exit everyone
        assumes is there is not.
        """
        return self.quantity > _QUANTITY_EPSILON and not self.exits


def agent_position(ticker: str, price: float | None = None) -> AgentPosition | None:
    """The auto trader's position in one ticker, with the orders resting on it.

    The exits come from the ledger of what was actually placed, never from the
    signal. A signal's stop is what the analysis proposed; this is what the
    broker will execute. The two disagree often — a discarded level, an
    ATR-derived fallback, a bracket the broker refused — and the difference is
    the whole reason this is shown separately.
    """
    ticker = ticker.upper().strip()
    fills = _agent_fills(ticker)
    if not fills:
        return None
    position = compute_position(
        [{"side": f["side"], "date": f["date"], "price": f["price"], "quantity": f["quantity"], "note": None}
         for f in fills]
    )
    if position.quantity <= _QUANTITY_EPSILON:
        return None

    opened = min((lot.date for lot in position.open_lots if lot.date), default=None)
    if isinstance(opened, str):
        opened = datetime.date.fromisoformat(opened)

    exits = [
        RestingExit(kind=t.exit_kind, price=t.limit_price, quantity=t.quantity)
        for t in db.get_agent_trades()
        if t.ticker == ticker
        and t.status == "pending"
        and t.is_stop
        and t.exit_kind
        and t.limit_price
    ]
    return AgentPosition(
        quantity=position.quantity,
        avg_cost=position.avg_cost,
        price=price,
        opened=opened,
        exits=exits,
    )


def unprotected_positions() -> list[tuple[str, AgentPosition]]:
    """Every auto-trader holding with no exit resting under it.

    This is the state nothing used to announce. A position whose bracket the
    broker refused looks exactly like one whose bracket is working, unless
    something goes looking for the absence.
    """
    unprotected = []
    for holding in agent_book.build_book().holdings:
        position = agent_position(holding.ticker)
        if position and position.unprotected:
            unprotected.append((holding.ticker, position))
    return unprotected
