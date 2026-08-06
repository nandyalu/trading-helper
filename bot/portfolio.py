"""Real-book dashboard for /portfolio and the weekly digest: per-position
weights, concentration warnings, P&L totals, and an honest vs-SPY comparison.

The benchmark math works lot-by-lot: every open FIFO lot is compared against
putting the same dollars into SPY on the same date, then weighted by cost.
That sidesteps the usual "since inception" ambiguity with staggered buys —
no time-weighting assumptions, just "what if each purchase had bought SPY
instead". Blocking (yfinance + DB) — call via asyncio.to_thread.
"""
import datetime
from dataclasses import dataclass, field

import discord
import yfinance as yf
from tradingagents.dataflows.stockstats_utils import yf_retry

from bot import db
from bot.positions import Position, compute_position, get_current_price, signed_dollars

_CONCENTRATION_WARN_PCT = 30.0


# --- Pure math -----------------------------------------------------------------


@dataclass
class LotComparison:
    cost: float  # lot price × quantity
    value_now: float  # current price × quantity
    benchmark_entry: float | None  # SPY close on/after the lot date
    benchmark_now: float | None


@dataclass
class BookVsBenchmark:
    book_return_pct: float
    benchmark_return_pct: float
    compared_cost: float  # dollars that had benchmark data and were compared

    @property
    def alpha_pct(self) -> float:
        return self.book_return_pct - self.benchmark_return_pct


def compare_open_book(lots: list[LotComparison]) -> BookVsBenchmark | None:
    """Cost-weighted open-book return vs the same dollars in SPY on the same
    dates. Lots without benchmark data are excluded from *both* sides so the
    comparison stays apples-to-apples; None when nothing is comparable."""
    valid = [
        lot
        for lot in lots
        if lot.cost > 0 and lot.benchmark_entry and lot.benchmark_now and lot.benchmark_entry > 0
    ]
    total_cost = sum(lot.cost for lot in valid)
    if total_cost <= 0:
        return None
    book_value = sum(lot.value_now for lot in valid)
    shadow_value = sum(lot.cost * (lot.benchmark_now / lot.benchmark_entry) for lot in valid)
    return BookVsBenchmark(
        book_return_pct=(book_value / total_cost - 1) * 100,
        benchmark_return_pct=(shadow_value / total_cost - 1) * 100,
        compared_cost=total_cost,
    )


def concentration_warnings(weights_pct: dict[str, float], warn_pct: float = _CONCENTRATION_WARN_PCT) -> list[str]:
    """A single holding is trivially 100% — only warn when there's an actual
    allocation choice being made (2+ positions)."""
    if len(weights_pct) < 2:
        return []
    return [
        f"⚠️ {ticker} is {weight:.0f}% of the book"
        for ticker, weight in sorted(weights_pct.items(), key=lambda kv: -kv[1])
        if weight >= warn_pct
    ]


# --- Benchmark data --------------------------------------------------------------


def _spy_history_since(start: datetime.date):
    try:
        history = yf_retry(lambda: yf.Ticker("SPY").history(start=start.isoformat()))
        return history if len(history) else None
    except Exception:
        return None


def _close_on_or_after(history, target: datetime.date) -> float | None:
    for timestamp, close in history["Close"].items():
        if timestamp.date() >= target:
            return float(close)
    return None


# --- Embed ------------------------------------------------------------------------


@dataclass
class PortfolioPositionData:
    """One open real position, priced now. ``price``/``value``/``unrealized``/
    ``unrealized_pct``/``weight_pct`` are None when a current price couldn't
    be fetched."""

    ticker: str
    quantity: float
    avg_cost: float
    weight_pct: float | None
    price: float | None
    value: float | None
    unrealized: float | None
    unrealized_pct: float | None


@dataclass
class PortfolioData:
    """Structured equivalent of ``build_portfolio_embed`` — open positions
    plus totals and the vs-SPY comparison, reusable by both the Discord embed
    and the web API."""

    positions: list[PortfolioPositionData] = field(default_factory=list)
    total_value: float = 0.0
    total_cost: float = 0.0
    total_realized: float = 0.0
    missing_prices: list[str] = field(default_factory=list)
    comparison: "BookVsBenchmark | None" = None
    concentration: list[str] = field(default_factory=list)


def get_portfolio_positions() -> PortfolioData | None:
    """Pure data equivalent of ``build_portfolio_embed`` — None when no
    transactions exist at all."""
    tickers = db.get_all_transaction_tickers()
    if not tickers:
        return None
    positions: dict[str, Position] = {t: compute_position(db.get_transactions(t)) for t in sorted(tickers)}
    total_realized = sum(p.realized_pnl for p in positions.values())
    open_positions = {t: p for t, p in positions.items() if p.quantity > 0}

    data = PortfolioData(total_realized=total_realized)
    if not open_positions:
        return data

    prices = {t: get_current_price(t) for t in open_positions}
    priced = {t: p for t, p in open_positions.items() if prices[t] is not None}
    data.missing_prices = [t for t in open_positions if prices[t] is None]
    values = {t: prices[t] * p.quantity for t, p in priced.items()}
    total_value = sum(values.values())
    total_cost = sum(p.avg_cost * p.quantity for p in priced.values())
    weights = {t: value / total_value * 100 for t, value in values.items()} if total_value else {}

    for ticker, position in open_positions.items():
        if ticker not in priced:
            data.positions.append(PortfolioPositionData(
                ticker=ticker, quantity=position.quantity, avg_cost=position.avg_cost,
                weight_pct=None, price=None, value=None, unrealized=None, unrealized_pct=None,
            ))
            continue
        price = prices[ticker]
        value = values[ticker]
        unrealized = value - position.avg_cost * position.quantity
        unrealized_pct = (price / position.avg_cost - 1) * 100 if position.avg_cost else 0.0
        data.positions.append(PortfolioPositionData(
            ticker=ticker, quantity=position.quantity, avg_cost=position.avg_cost,
            weight_pct=weights[ticker], price=price, value=value,
            unrealized=unrealized, unrealized_pct=unrealized_pct,
        ))

    data.total_value = total_value
    data.total_cost = total_cost
    data.comparison = open_book_vs_spy(priced, prices)
    data.concentration = concentration_warnings(weights)
    return data


def build_portfolio_embed() -> discord.Embed | None:
    """Dashboard for /portfolio; None when no transactions exist at all."""
    data = get_portfolio_positions()
    if data is None:
        return None

    embed = discord.Embed(title="💼 Portfolio", color=discord.Color.blurple())
    if not data.positions:
        embed.description = "No open positions."
        embed.add_field(name="Totals", value=f"Realized to date: {signed_dollars(data.total_realized)}", inline=False)
        return embed

    for p in data.positions:
        if p.price is None:
            embed.add_field(
                name=p.ticker,
                value=f"Quantity: {p.quantity:g} @ avg ${p.avg_cost:,.2f}\nCurrent price: unavailable",
                inline=False,
            )
            continue
        embed.add_field(
            name=f"{p.ticker} — {p.weight_pct:.0f}% of book",
            value=(
                f"Quantity: {p.quantity:g} @ avg ${p.avg_cost:,.2f}\n"
                f"Now: ${p.price:,.2f} · Value: ${p.value:,.2f}\n"
                f"Unrealized: {signed_dollars(p.unrealized)} ({p.unrealized_pct:+.1f}%)"
            ),
            inline=False,
        )

    totals = [
        f"Open value: ${data.total_value:,.2f} (cost ${data.total_cost:,.2f})",
        f"Unrealized: {signed_dollars(data.total_value - data.total_cost)}",
        f"Realized to date: {signed_dollars(data.total_realized)}",
        f"Total P&L: {signed_dollars(data.total_value - data.total_cost + data.total_realized)}",
    ]

    if data.comparison is not None:
        totals.append(
            f"Open book {data.comparison.book_return_pct:+.1f}% vs SPY "
            f"{data.comparison.benchmark_return_pct:+.1f}% (alpha {data.comparison.alpha_pct:+.1f}%), "
            f"same dollars on the same dates"
        )
    if data.missing_prices:
        totals.append(f"(price unavailable for {', '.join(data.missing_prices)} — excluded)")
    embed.add_field(name="Totals", value="\n".join(totals), inline=False)

    for warning in data.concentration:
        embed.add_field(name="Concentration", value=warning, inline=False)
    return embed


def open_book_vs_spy(priced: dict[str, Position], prices: dict[str, float]) -> BookVsBenchmark | None:
    lot_dates = [
        datetime.date.fromisoformat(lot.date)
        for position in priced.values()
        for lot in position.open_lots
    ]
    if not lot_dates:
        return None
    history = _spy_history_since(min(lot_dates))
    if history is None:
        return None
    spy_now = float(history["Close"].iloc[-1])
    lots = [
        LotComparison(
            cost=lot.price * lot.quantity,
            value_now=prices[ticker] * lot.quantity,
            benchmark_entry=_close_on_or_after(history, datetime.date.fromisoformat(lot.date)),
            benchmark_now=spy_now,
        )
        for ticker, position in priced.items()
        for lot in position.open_lots
    ]
    return compare_open_book(lots)
