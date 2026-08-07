"""ATR-based sizing suggestions for Buy-ish decisions: a 2×ATR(14) stop and,
when account equity is configured (/risk), a share count that puts the chosen
% of equity at risk between entry and stop. Rule-based only — the numbers
frame the AI's signal, they don't come from it. Math is pure; fetching is
yfinance. Blocking — call via asyncio.to_thread.
"""
import datetime
from dataclasses import dataclass

from backend.database import db
from backend.services.positions import compute_position, get_current_price
from backend.services.signals import BUYISH_DECISIONS

_ATR_PERIOD = 14
_STOP_ATR_MULT = 2.0
_DEFAULT_RISK_PCT = 1.0

# Ceiling on a single position, as a share of account equity. Risk-based
# sizing alone does not bound this: shares = risk_dollars / (2 × ATR), so a
# low-volatility stock produces a large share count from a small risk budget.
# On a $5,000 account at 1% risk, a $50 stock with a $0.50 ATR sizes to about
# $2,500 — half the account in one name, from a $50 risk budget. The old
# behavior capped only at 100% of equity, which is no cap at all for anyone
# holding more than one position.
_DEFAULT_MAX_POSITION_PCT = 20.0

# Ceiling on how many names can be open at once. At a 1-2 week horizon a
# 20-ticker watchlist produces far more actionable signals than a small
# account can fund, and the arithmetic should not be left to the user.
_DEFAULT_MAX_POSITIONS = 5

_EQUITY_SETTING_KEY = "risk_equity"
_RISK_PCT_SETTING_KEY = "risk_pct"
_MAX_POSITION_PCT_SETTING_KEY = "max_position_pct"
_MAX_POSITIONS_SETTING_KEY = "max_positions"


# --- Pure math -----------------------------------------------------------------


def compute_atr(highs: list[float], lows: list[float], closes: list[float], period: int = _ATR_PERIOD) -> float | None:
    """Simple-mean ATR over the last ``period`` true ranges (not Wilder's
    smoothing — close enough for a stop suggestion). None when there isn't
    at least one prior close to anchor the first true range."""
    if not (len(highs) == len(lows) == len(closes)) or len(closes) < 2:
        return None
    true_ranges = [
        max(high - low, abs(high - prev_close), abs(low - prev_close))
        for high, low, prev_close in zip(highs[1:], lows[1:], closes[:-1])
    ]
    window = true_ranges[-period:]
    return sum(window) / len(window)


@dataclass
class SizingSuggestion:
    price: float
    atr: float
    stop: float
    shares: float | None = None  # None when no equity configured
    risk_dollars: float | None = None
    capped: bool = False  # position was limited by max_position_pct
    max_position_value: float | None = None  # the cap that applied, in dollars


def suggest_position(
    price: float,
    atr: float,
    equity: float | None,
    risk_pct: float = _DEFAULT_RISK_PCT,
    stop_mult: float = _STOP_ATR_MULT,
    max_position_pct: float = _DEFAULT_MAX_POSITION_PCT,
) -> SizingSuggestion | None:
    """Share count that risks ``risk_pct`` of equity between entry and a
    ``stop_mult``×ATR stop, then limited to ``max_position_pct`` of equity.

    Both limits matter and they bind in different cases. Risk sizing controls
    the loss if the stop is hit; the position cap controls concentration when
    low volatility makes the risk-based count large. Whichever is smaller wins.
    """
    if price <= 0 or atr <= 0:
        return None
    stop = price - stop_mult * atr
    if stop <= 0:
        return None  # ATR comparable to price — a stop suggestion is meaningless
    suggestion = SizingSuggestion(price=price, atr=atr, stop=stop)
    if equity and equity > 0:
        risk_dollars = equity * risk_pct / 100
        shares = risk_dollars / (stop_mult * atr)
        max_position_value = equity * max_position_pct / 100
        if shares * price > max_position_value:
            shares = max_position_value / price
            suggestion.capped = True
        suggestion.shares = round(shares, 2)
        suggestion.risk_dollars = risk_dollars
        suggestion.max_position_value = max_position_value
    return suggestion


def format_sizing_field(suggestion: SizingSuggestion, risk_pct: float, equity: float | None) -> str:
    lines = [
        f"Stop: ${suggestion.stop:,.2f} ({_STOP_ATR_MULT:g}×ATR{_ATR_PERIOD} of ${suggestion.atr:,.2f} below entry)"
    ]
    if suggestion.shares is not None:
        size_line = (
            f"Size: {suggestion.shares:g} shares ≈ ${suggestion.shares * suggestion.price:,.0f} "
            f"— risking ~${suggestion.risk_dollars:,.0f} ({risk_pct:g}% of ${equity:,.0f})"
        )
        if suggestion.capped:
            size_line += f" · capped at ${suggestion.max_position_value:,.0f} per position"
        lines.append(size_line)
    else:
        lines.append("Set account equity with /risk to get a share count.")
    return "\n".join(lines)


# --- Settings ---------------------------------------------------------------------


def _get_float_setting(key: str, default: float) -> float:
    raw = db.get_setting(key)
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return default


def get_risk_settings() -> tuple[float | None, float]:
    """(equity, risk_pct) — equity is None until configured via /risk."""
    equity = None
    raw_equity = db.get_setting(_EQUITY_SETTING_KEY)
    if raw_equity:
        try:
            equity = float(raw_equity)
        except ValueError:
            pass
    return equity, _get_float_setting(_RISK_PCT_SETTING_KEY, _DEFAULT_RISK_PCT)


def get_max_position_pct() -> float:
    return _get_float_setting(_MAX_POSITION_PCT_SETTING_KEY, _DEFAULT_MAX_POSITION_PCT)


def get_max_positions() -> int:
    return int(_get_float_setting(_MAX_POSITIONS_SETTING_KEY, _DEFAULT_MAX_POSITIONS))


def set_risk_settings(
    equity: float | None = None,
    risk_pct: float | None = None,
    max_position_pct: float | None = None,
    max_positions: int | None = None,
) -> None:
    for key, value in (
        (_EQUITY_SETTING_KEY, equity),
        (_RISK_PCT_SETTING_KEY, risk_pct),
        (_MAX_POSITION_PCT_SETTING_KEY, max_position_pct),
        (_MAX_POSITIONS_SETTING_KEY, max_positions),
    ):
        if value is not None:
            db.set_setting(key, str(value))


# --- Fetch + orchestration -----------------------------------------------------------


def get_atr(ticker: str, period: int = _ATR_PERIOD) -> float | None:
    """ATR over completed sessions, from the daily bar cache. Today is left out
    on purpose: a mid-session range understates the day's true range, which
    would tighten the suggested stop for no reason other than the clock."""
    from backend.services import bars  # lazy: keeps this module import-light

    start = datetime.date.today() - datetime.timedelta(days=120)
    window = bars.get_bars(ticker, start)
    if len(window) < 2:
        return None
    return compute_atr(
        [bar.high for bar in window],
        [bar.low for bar in window],
        [bar.close for bar in window],
        period,
    )


def count_open_positions(ticker: str | None = None) -> int:
    """How many names are held right now, across the real and paper books
    combined. ``ticker`` is excluded from the count when given, so a caller
    asking "is there room for this one?" is not blocked by a position it
    already holds and would only be adding to."""
    open_tickers = set()
    for name in db.get_all_transaction_tickers():
        if compute_position(db.get_transactions(name)).quantity > 0:
            open_tickers.add(name)
    for name in db.get_all_paper_tickers():
        if compute_position(db.get_paper_transactions(name)).quantity > 0:
            open_tickers.add(name)
    open_tickers.discard(ticker)
    return len(open_tickers)


def position_slots_note(ticker: str) -> str | None:
    """A line warning that the book is full, or None when there is room. The
    limit is advice, not a block — the app informs decisions, it does not
    place or refuse trades."""
    limit = get_max_positions()
    open_count = count_open_positions(ticker)
    if open_count < limit:
        return None
    return (
        f"⚠️ You already hold {open_count} of a maximum {limit} positions. "
        "Consider closing a weaker one before opening this."
    )


def build_sizing_field(ticker: str, decision: str) -> str | None:
    """Embed field text for Buy-ish decisions; None otherwise or when data is
    unavailable (the embed simply omits the section)."""
    if decision not in BUYISH_DECISIONS:
        return None
    price = get_current_price(ticker)
    atr = get_atr(ticker)
    if price is None or atr is None:
        return None
    equity, risk_pct = get_risk_settings()
    suggestion = suggest_position(price, atr, equity, risk_pct, max_position_pct=get_max_position_pct())
    if suggestion is None:
        return None
    field = format_sizing_field(suggestion, risk_pct, equity)
    slots = position_slots_note(ticker)
    return f"{field}\n{slots}" if slots else field
