"""FIFO position accounting derived from an append-only buy/sell transaction log.

The transaction log (backend/database/storage.py's ``state["positions"]``) is the only persisted
state — open lots, cost basis, and realized P&L are all recomputed from it here on
every read, so there's never a separately-mutated position to get out of sync.
"""
import datetime
from dataclasses import dataclass

import yfinance as yf
from tradingagents.dataflows.stockstats_utils import yf_retry

_EPSILON = 1e-9


@dataclass
class Lot:
    date: str
    price: float
    quantity: float


@dataclass
class Position:
    open_lots: list[Lot]
    quantity: float
    avg_cost: float
    realized_pnl: float


def compute_position(transactions: list[dict]) -> Position:
    open_lots: list[Lot] = []
    realized_pnl = 0.0

    for tx in transactions:
        if tx["side"] == "buy":
            open_lots.append(Lot(date=tx["date"], price=tx["price"], quantity=tx["quantity"]))
        else:
            remaining = tx["quantity"]
            while remaining > _EPSILON and open_lots:
                lot = open_lots[0]
                matched = min(lot.quantity, remaining)
                realized_pnl += (tx["price"] - lot.price) * matched
                lot.quantity -= matched
                remaining -= matched
                if lot.quantity <= _EPSILON:
                    open_lots.pop(0)

    quantity = sum(lot.quantity for lot in open_lots)
    avg_cost = sum(lot.price * lot.quantity for lot in open_lots) / quantity if quantity > _EPSILON else 0.0
    return Position(open_lots=open_lots, quantity=quantity, avg_cost=avg_cost, realized_pnl=realized_pnl)


def get_current_price(ticker: str) -> float | None:
    """Best-effort quote lookup — callers must handle None (e.g. rate-limited).
    Prefers Webull's real-time snapshot when configured (backend/services/quotes.py) and
    falls back to yfinance's delayed close."""
    from backend.services.quotes import get_realtime_price  # lazy: keeps positions import-light

    price = get_realtime_price(ticker)
    if price is not None:
        return price
    try:
        history = yf_retry(lambda: yf.Ticker(ticker).history(period="1d"))
        if history.empty:
            return None
        return float(history["Close"].iloc[-1])
    except Exception:
        return None


@dataclass
class PriceWindow:
    """Daily-bar summary of ``start`` → today, for grading a matured signal."""

    first_close: float
    last_close: float
    high: float
    low: float


def get_price_window(ticker: str, start: datetime.date) -> PriceWindow | None:
    """Best-effort like get_current_price — None on empty/failed fetch. If
    ``start`` is a non-trading day the window begins at the next session."""
    try:
        history = yf_retry(lambda: yf.Ticker(ticker).history(start=start.isoformat()))
        if history.empty:
            return None
        return PriceWindow(
            first_close=float(history["Close"].iloc[0]),
            last_close=float(history["Close"].iloc[-1]),
            high=float(history["High"].max()),
            low=float(history["Low"].min()),
        )
    except Exception:
        return None


@dataclass
class OhlcBar:
    date: str  # ISO date
    open: float
    high: float
    low: float
    close: float
    volume: float


def get_price_history(ticker: str, days: int = 90) -> list[OhlcBar]:
    """Daily OHLCV bars for the last ``days`` calendar days — chart data.

    Unlike ``get_price_window``, which collapses the same yfinance frame down
    to 4 summary scalars for signal grading, this keeps every row. Best-effort
    like the other price lookups here — empty list on a failed/empty fetch."""
    start = datetime.date.today() - datetime.timedelta(days=days)
    try:
        history = yf_retry(lambda: yf.Ticker(ticker).history(start=start.isoformat()))
        if history.empty:
            return []
    except Exception:
        return []
    return [
        OhlcBar(
            date=timestamp.date().isoformat(),
            open=float(row["Open"]),
            high=float(row["High"]),
            low=float(row["Low"]),
            close=float(row["Close"]),
            volume=float(row["Volume"]),
        )
        for timestamp, row in history.iterrows()
    ]


def signed_dollars(amount: float) -> str:
    """+$100.00 / -$50.25 — "$+100.00" (plain ``:+`` formatting) reads wrong."""
    sign = "-" if amount < 0 else "+"
    return f"{sign}${abs(amount):,.2f}"


def describe_position(ticker: str, position: Position) -> list[str]:
    """Shared line-formatting for both the /positions command and analysis embeds."""
    current_price = get_current_price(ticker)
    lines = [
        f"Quantity: {position.quantity:g}",
        f"Avg cost basis: ${position.avg_cost:,.2f}",
    ]
    if current_price is not None:
        unrealized = (current_price - position.avg_cost) * position.quantity
        unrealized_pct = (current_price / position.avg_cost - 1) * 100 if position.avg_cost else 0.0
        lines.append(f"Current price: ${current_price:,.2f}")
        lines.append(f"Unrealized P&L: ${unrealized:,.2f} ({unrealized_pct:+.1f}%)")
    else:
        lines.append("Current price: unavailable")
    if abs(position.realized_pnl) > _EPSILON:
        lines.append(f"Realized P&L to date: ${position.realized_pnl:,.2f}")
    return lines
