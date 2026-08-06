"""ATR-based sizing suggestions for Buy-ish decisions: a 2×ATR(14) stop and,
when account equity is configured (/risk), a share count that puts the chosen
% of equity at risk between entry and stop. Rule-based only — the numbers
frame the AI's signal, they don't come from it. Math is pure; fetching is
yfinance. Blocking — call via asyncio.to_thread.
"""
from dataclasses import dataclass

import yfinance as yf
from tradingagents.dataflows.stockstats_utils import yf_retry

from bot import db
from bot.positions import get_current_price
from bot.signals import BUYISH_DECISIONS

_ATR_PERIOD = 14
_STOP_ATR_MULT = 2.0
_DEFAULT_RISK_PCT = 1.0

_EQUITY_SETTING_KEY = "risk_equity"
_RISK_PCT_SETTING_KEY = "risk_pct"


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
    capped: bool = False  # position was limited to 100% of equity


def suggest_position(
    price: float,
    atr: float,
    equity: float | None,
    risk_pct: float = _DEFAULT_RISK_PCT,
    stop_mult: float = _STOP_ATR_MULT,
) -> SizingSuggestion | None:
    if price <= 0 or atr <= 0:
        return None
    stop = price - stop_mult * atr
    if stop <= 0:
        return None  # ATR comparable to price — a stop suggestion is meaningless
    suggestion = SizingSuggestion(price=price, atr=atr, stop=stop)
    if equity and equity > 0:
        risk_dollars = equity * risk_pct / 100
        shares = risk_dollars / (stop_mult * atr)
        if shares * price > equity:
            shares = equity / price
            suggestion.capped = True
        suggestion.shares = round(shares, 2)
        suggestion.risk_dollars = risk_dollars
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
            size_line += " · capped at 100% of equity"
        lines.append(size_line)
    else:
        lines.append("Set account equity with /risk to get a share count.")
    return "\n".join(lines)


# --- Settings ---------------------------------------------------------------------


def get_risk_settings() -> tuple[float | None, float]:
    """(equity, risk_pct) — equity is None until configured via /risk."""
    equity = None
    raw_equity = db.get_setting(_EQUITY_SETTING_KEY)
    if raw_equity:
        try:
            equity = float(raw_equity)
        except ValueError:
            pass
    risk_pct = _DEFAULT_RISK_PCT
    raw_pct = db.get_setting(_RISK_PCT_SETTING_KEY)
    if raw_pct:
        try:
            risk_pct = float(raw_pct)
        except ValueError:
            pass
    return equity, risk_pct


def set_risk_settings(equity: float | None = None, risk_pct: float | None = None) -> None:
    if equity is not None:
        db.set_setting(_EQUITY_SETTING_KEY, str(equity))
    if risk_pct is not None:
        db.set_setting(_RISK_PCT_SETTING_KEY, str(risk_pct))


# --- Fetch + orchestration -----------------------------------------------------------


def get_atr(ticker: str, period: int = _ATR_PERIOD) -> float | None:
    try:
        history = yf_retry(lambda: yf.Ticker(ticker).history(period="3mo"))
        if len(history) < 2:
            return None
        return compute_atr(
            [float(v) for v in history["High"]],
            [float(v) for v in history["Low"]],
            [float(v) for v in history["Close"]],
            period,
        )
    except Exception:
        return None


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
    suggestion = suggest_position(price, atr, equity, risk_pct)
    if suggestion is None:
        return None
    return format_sizing_field(suggestion, risk_pct, equity)
