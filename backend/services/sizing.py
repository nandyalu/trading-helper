"""The 2×ATR(14) stop, derived in Python from the bar cache.

**This module suggests a stop. It never suggests a size.** It used to do both,
computing a share count from a configured account equity and a risk percentage.
Both callers now pass no equity, and for a reason worth keeping: the agent
decides how much to buy, and Python refuses what cannot be executed rather than
resizing it. A share count computed here would either be ignored or would
quietly turn the agent's decision into a different one.

The stop matters because a stated stop is often unusable — the price has moved
through it, or the model never gave one — and a position with no stop is a
position with nothing looking for its exit.

Math is pure. Fetching reads the bar cache. Blocking — call via
asyncio.to_thread.
"""
import datetime
from dataclasses import dataclass

_ATR_PERIOD = 14
_STOP_ATR_MULT = 2.0

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


def suggest_position(price: float, atr: float, stop_mult: float = _STOP_ATR_MULT) -> SizingSuggestion | None:
    """A stop ``stop_mult``×ATR below the price.

    None when the stop would land at or below zero — that happens when the ATR
    is comparable to the price itself, and a stop there says nothing about
    where the trade is wrong.
    """
    if price <= 0 or atr <= 0:
        return None
    stop = price - stop_mult * atr
    if stop <= 0:
        return None
    return SizingSuggestion(price=price, atr=atr, stop=stop)


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
