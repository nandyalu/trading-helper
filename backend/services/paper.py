"""Reaction-driven paper trading: reacting ✅ to a posted analysis embed
executes that signal into a virtual portfolio (papertransaction table),
priced at reaction time — an honest fill, since you can't trade at the price
the analysis saw. Buys are sized to a fixed notional; Sell signals close the
whole open position (no shorting). Reuses backend/services/positions.py's FIFO math.

Everything here is blocking (yfinance + DB) — call via asyncio.to_thread.
"""
import datetime
from dataclasses import dataclass, field

import discord

from backend.database import db
from backend.database.models import Signal
from backend.services.portfolio import open_book_vs_spy
from backend.services.positions import Position, compute_position, get_current_price, signed_dollars
from backend.services.signals import BUYISH_DECISIONS, SELLISH_DECISIONS

PAPER_EMOJI = "✅"

_DEFAULT_NOTIONAL = 1000.0
_NOTIONAL_SETTING_KEY = "paper_notional"


_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def sparkline(series: list[float], width: int = 20) -> str:
    """Unicode mini-chart of a numeric series, downsampled evenly to ``width``."""
    if not series:
        return ""
    if len(series) > width:
        step = (len(series) - 1) / (width - 1)
        series = [series[round(i * step)] for i in range(width)]
    low, high = min(series), max(series)
    if high == low:
        return _SPARK_CHARS[3] * len(series)
    scale = len(_SPARK_CHARS) - 1
    return "".join(_SPARK_CHARS[round((value - low) / (high - low) * scale)] for value in series)


def max_drawdown(series: list[float]) -> float:
    """Largest peak-to-trough drop, in the series' own units (dollars here)."""
    peak = float("-inf")
    worst = 0.0
    for value in series:
        peak = max(peak, value)
        worst = max(worst, peak - value)
    return worst


def get_notional() -> float:
    raw = db.get_setting(_NOTIONAL_SETTING_KEY)
    try:
        return float(raw) if raw else _DEFAULT_NOTIONAL
    except ValueError:
        return _DEFAULT_NOTIONAL


def set_notional(amount: float) -> None:
    db.set_setting(_NOTIONAL_SETTING_KEY, str(amount))


def _close_all(ticker: str, signal_id: int | None, note: str) -> str | None:
    """Sell the entire open paper position at the current price. Returns the
    reply text, or None when there's nothing open to close."""
    before = compute_position(db.get_paper_transactions(ticker))
    if before.quantity <= 0:
        return None
    price = get_current_price(ticker)
    if price is None:
        return f"Couldn't fetch a price for {ticker} — try again shortly."
    db.add_paper_transaction(ticker, "sell", price, before.quantity, signal_id=signal_id, note=note)
    after = compute_position(db.get_paper_transactions(ticker))
    realized_delta = after.realized_pnl - before.realized_pnl
    pct = (price / before.avg_cost - 1) * 100 if before.avg_cost else 0.0
    return (
        f"📄 Paper sell: closed {before.quantity:g} {ticker} @ ${price:,.2f} — "
        f"realized {signed_dollars(realized_delta)} ({pct:+.1f}%)."
    )


def execute_signal_reaction(signal: Signal) -> str:
    """Turn a ✅ reaction on a signal's message into a paper trade; returns
    the reply to post in the channel."""
    if db.has_paper_transaction_for_signal(signal.id):
        return f"That {signal.ticker} signal is already executed as a paper trade."

    if signal.decision in BUYISH_DECISIONS:
        price = get_current_price(signal.ticker)
        if price is None:
            return f"Couldn't fetch a price for {signal.ticker} — try reacting again shortly."
        notional = get_notional()
        quantity = round(notional / price, 4)
        db.add_paper_transaction(
            signal.ticker,
            "buy",
            price,
            quantity,
            signal_id=signal.id,
            note=f"✅ on {signal.decision} signal of {signal.signal_date}",
        )
        position = compute_position(db.get_paper_transactions(signal.ticker))
        return (
            f"📄 Paper buy: {quantity:g} {signal.ticker} @ ${price:,.2f} (~${notional:,.0f}). "
            f"Paper position: {position.quantity:g} shares @ avg ${position.avg_cost:,.2f}."
        )

    if signal.decision in SELLISH_DECISIONS:
        reply = _close_all(
            signal.ticker, signal.id, note=f"✅ on {signal.decision} signal of {signal.signal_date}"
        )
        if reply is None:
            return (
                f"No open paper position in {signal.ticker} to close — "
                f"Sell signals only exit longs (no shorting yet)."
            )
        return reply

    return f"{signal.ticker} was a {signal.decision} — nothing to execute as a paper trade."


def close_paper_position(ticker: str) -> str:
    """/paperclose — manual exit without waiting for a Sell signal."""
    reply = _close_all(ticker, signal_id=None, note="manual close via /paperclose")
    return reply if reply is not None else f"No open paper position in {ticker}."


def record_daily_snapshot() -> None:
    """End-of-day valuation for the equity curve; called by the daily task.
    Tickers whose price can't be fetched are left out of value AND cost so a
    bad quote day dents coverage, not the P&L series."""
    open_value = open_cost = total_realized = 0.0
    for ticker in db.get_all_paper_tickers():
        position = compute_position(db.get_paper_transactions(ticker))
        total_realized += position.realized_pnl
        if position.quantity <= 0:
            continue
        price = get_current_price(ticker)
        if price is None:
            continue
        open_value += price * position.quantity
        open_cost += position.avg_cost * position.quantity
    db.record_paper_snapshot(
        snapshot_date=datetime.date.today(),
        open_value=open_value,
        open_cost=open_cost,
        realized_pnl=total_realized,
        spy_close=get_current_price("SPY"),
    )


def _performance_lines(open_positions: dict) -> list[str]:
    """Equity-curve summary from stored snapshots plus the lot-by-lot vs-SPY
    comparison (reused from backend/services/portfolio.py) on the open paper book."""
    lines: list[str] = []
    snapshots = db.get_paper_snapshots()
    if len(snapshots) >= 2:
        pnl_series = [s.open_value - s.open_cost + s.realized_pnl for s in snapshots]
        lines.append(
            f"P&L since {snapshots[0].snapshot_date}: {sparkline(pnl_series)} "
            f"{signed_dollars(pnl_series[-1])} (max drawdown ${max_drawdown(pnl_series):,.2f})"
        )
        first_spy = next((s.spy_close for s in snapshots if s.spy_close), None)
        last_spy = next((s.spy_close for s in reversed(snapshots) if s.spy_close), None)
        if first_spy and last_spy and first_spy != last_spy:
            lines.append(f"SPY {(last_spy / first_spy - 1) * 100:+.1f}% over the same span")
    if open_positions:
        prices = {t: get_current_price(t) for t in open_positions}
        priced = {t: p for t, p in open_positions.items() if prices[t] is not None}
        comparison = open_book_vs_spy(priced, prices) if priced else None
        if comparison is not None:
            lines.append(
                f"Open lots {comparison.book_return_pct:+.1f}% vs SPY "
                f"{comparison.benchmark_return_pct:+.1f}% (alpha {comparison.alpha_pct:+.1f}%)"
            )
    return lines


@dataclass
class PaperPositionData:
    """One open paper position, priced now. ``price``/``value``/``unrealized``/
    ``unrealized_pct`` are None when a current price couldn't be fetched."""

    ticker: str
    quantity: float
    avg_cost: float
    cost_basis: float
    price: float | None
    value: float | None
    unrealized: float | None
    unrealized_pct: float | None


@dataclass
class PaperPortfolioData:
    """Structured equivalent of ``build_paper_embed`` — open positions plus
    totals, reusable by both the Discord embed and the web API."""

    positions: list[PaperPositionData] = field(default_factory=list)
    open_positions: dict[str, Position] = field(default_factory=dict)  # for _performance_lines
    total_value: float = 0.0
    total_cost: float = 0.0
    total_unrealized: float = 0.0
    total_realized: float = 0.0
    missing_prices: list[str] = field(default_factory=list)


def get_paper_positions() -> PaperPortfolioData | None:
    """Pure data equivalent of ``build_paper_embed`` — None when no paper
    trades exist at all."""
    tickers = db.get_all_paper_tickers()
    if not tickers:
        return None

    data = PaperPortfolioData()
    for ticker in sorted(tickers):
        position = compute_position(db.get_paper_transactions(ticker))
        data.total_realized += position.realized_pnl
        if position.quantity <= 0:
            continue
        data.open_positions[ticker] = position
        cost = position.avg_cost * position.quantity
        data.total_cost += cost
        price = get_current_price(ticker)
        if price is None:
            data.missing_prices.append(ticker)
            data.positions.append(PaperPositionData(
                ticker=ticker, quantity=position.quantity, avg_cost=position.avg_cost,
                cost_basis=cost, price=None, value=None, unrealized=None, unrealized_pct=None,
            ))
            continue
        value = price * position.quantity
        unrealized = value - cost
        unrealized_pct = (price / position.avg_cost - 1) * 100 if position.avg_cost else 0.0
        data.total_value += value
        data.total_unrealized += unrealized
        data.positions.append(PaperPositionData(
            ticker=ticker, quantity=position.quantity, avg_cost=position.avg_cost,
            cost_basis=cost, price=price, value=value, unrealized=unrealized, unrealized_pct=unrealized_pct,
        ))
    return data


def build_paper_embed() -> discord.Embed | None:
    """Portfolio view for /paper; None when no paper trades exist at all."""
    data = get_paper_positions()
    if data is None:
        return None

    embed = discord.Embed(title="📄 Paper Portfolio", color=discord.Color.blurple())
    for p in data.positions:
        if p.price is None:
            embed.add_field(
                name=p.ticker,
                value=f"Quantity: {p.quantity:g}\nAvg cost: ${p.avg_cost:,.2f}\nCurrent price: unavailable",
                inline=False,
            )
            continue
        embed.add_field(
            name=p.ticker,
            value=(
                f"Quantity: {p.quantity:g} @ avg ${p.avg_cost:,.2f}\n"
                f"Now: ${p.price:,.2f} · Value: ${p.value:,.2f}\n"
                f"Unrealized: {signed_dollars(p.unrealized)} ({p.unrealized_pct:+.1f}%)"
            ),
            inline=False,
        )

    totals = []
    if data.positions:
        totals.append(f"Open value: ${data.total_value:,.2f} (cost ${data.total_cost:,.2f})")
        totals.append(f"Unrealized: {signed_dollars(data.total_unrealized)}")
    else:
        totals.append("No open positions.")
    totals.append(f"Realized to date: {signed_dollars(data.total_realized)}")
    totals.append(f"Total P&L: {signed_dollars(data.total_unrealized + data.total_realized)}")
    if data.missing_prices:
        totals.append(f"(price unavailable for {', '.join(data.missing_prices)} — excluded from totals)")
    embed.add_field(name="Totals", value="\n".join(totals), inline=False)

    performance = _performance_lines(data.open_positions)
    if performance:
        embed.add_field(name="Performance", value="\n".join(performance), inline=False)

    embed.set_footer(text=f"Per-trade notional: ${get_notional():,.0f} · change with /papersize")
    return embed
