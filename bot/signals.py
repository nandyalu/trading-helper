"""Pure logic for turning a TradingAgents rationale into a trackable signal:
parsing the free-text time horizon into an evaluation date, and judging
pass/fail once a follow-up price is available. Mirrors bot/positions.py's
style — no DB or Discord access here, see bot/db.py for persistence.
"""
import re
from dataclasses import dataclass

BUYISH_DECISIONS = frozenset({"Buy", "Overweight"})
SELLISH_DECISIONS = frozenset({"Sell", "Underweight"})

_MONTH_RE = re.compile(r"(\d+)\s*(?:-\s*(\d+)\s*)?month", re.IGNORECASE)
_WEEK_RE = re.compile(r"(\d+)\s*(?:-\s*(\d+)\s*)?week", re.IGNORECASE)
_DAY_RE = re.compile(r"(\d+)\s*(?:-\s*(\d+)\s*)?day", re.IGNORECASE)

_TIME_HORIZON_RE = re.compile(r"\*\*Time Horizon\*\*:\s*(.+)")
_PRICE_TARGET_RE = re.compile(r"\*\*Price Target\*\*:\s*([\d.]+)")

_DEFAULT_HOLD_BAND_PCT = 10.0


def parse_time_horizon_days(text: str | None, default_days: int = 30) -> int:
    """Best-effort: "3-6 months" -> ~135 days, "2 weeks" -> 14. Falls back to
    ``default_days`` when absent or unparseable (e.g. "long-term")."""
    if not text:
        return default_days
    for pattern, unit_days in ((_MONTH_RE, 30), (_WEEK_RE, 7), (_DAY_RE, 1)):
        match = pattern.search(text)
        if match:
            low = int(match.group(1))
            high = int(match.group(2)) if match.group(2) else low
            return max(1, round((low + high) / 2 * unit_days))
    return default_days


def extract_time_horizon(rationale: str) -> str | None:
    match = _TIME_HORIZON_RE.search(rationale)
    return match.group(1).strip() if match else None


def extract_price_target(rationale: str) -> float | None:
    match = _PRICE_TARGET_RE.search(rationale)
    return float(match.group(1)) if match else None


def evaluate_outcome(
    decision: str, price_at_signal: float, price_now: float, hold_band_pct: float = _DEFAULT_HOLD_BAND_PCT
) -> str:
    """"pass"/"fail" for directional calls; Hold passes if price stayed within
    ``hold_band_pct``% of where it was when the signal was made."""
    pct_change = (price_now / price_at_signal - 1) * 100 if price_at_signal else 0.0
    if decision in BUYISH_DECISIONS:
        return "pass" if pct_change > 0 else "fail"
    if decision in SELLISH_DECISIONS:
        return "pass" if pct_change < 0 else "fail"
    # Hold (or anything unrecognized defaults to the same band rule)
    return "pass" if abs(pct_change) <= hold_band_pct else "fail"


@dataclass
class SignalEvaluation:
    pct_change: float
    outcome: str  # absolute pass/fail, same rule as evaluate_outcome
    benchmark_pct_change: float | None = None
    alpha_pct: float | None = None  # pct_change − benchmark_pct_change (raw, not direction-adjusted)
    outcome_vs_benchmark: str | None = None
    price_target_hit: bool | None = None


def evaluate_signal_window(
    decision: str,
    price_at_signal: float,
    price_now: float,
    benchmark_price_at_signal: float | None = None,
    benchmark_price_now: float | None = None,
    price_target: float | None = None,
    window_high: float | None = None,
    window_low: float | None = None,
    hold_band_pct: float = _DEFAULT_HOLD_BAND_PCT,
) -> SignalEvaluation:
    """Full grading of a matured signal. The absolute outcome is always
    computed; the vs-benchmark outcome and target-hit check are filled only
    when their inputs are available (benchmark fetch can fail, targets are
    optional), leaving None so callers/storage can tell "not graded" from
    "graded fail".

    vs-benchmark rule: a Buy must beat the benchmark, a Sell must lag it
    (selling something that then underperforms was right in relative terms),
    and Hold passes if alpha stayed within ±``hold_band_pct``.
    """
    pct_change = (price_now / price_at_signal - 1) * 100 if price_at_signal else 0.0
    result = SignalEvaluation(
        pct_change=pct_change,
        outcome=evaluate_outcome(decision, price_at_signal, price_now, hold_band_pct),
    )

    if benchmark_price_at_signal and benchmark_price_now is not None:
        benchmark_pct = (benchmark_price_now / benchmark_price_at_signal - 1) * 100
        alpha = pct_change - benchmark_pct
        result.benchmark_pct_change = benchmark_pct
        result.alpha_pct = alpha
        if decision in BUYISH_DECISIONS:
            result.outcome_vs_benchmark = "pass" if alpha > 0 else "fail"
        elif decision in SELLISH_DECISIONS:
            result.outcome_vs_benchmark = "pass" if alpha < 0 else "fail"
        else:
            result.outcome_vs_benchmark = "pass" if abs(alpha) <= hold_band_pct else "fail"

    if price_target and window_high is not None and window_low is not None:
        result.price_target_hit = price_crossed_target(
            price_target, price_at_signal, high=window_high, low=window_low
        )

    return result


def price_crossed_target(price_target: float, price_at_signal: float, high: float, low: float) -> bool:
    """True when the price touched the target level at some point, in
    whichever direction the target sat relative to the entry price. For a
    single quote (rather than a window) pass it as both ``high`` and ``low``."""
    if price_target >= price_at_signal:
        return high >= price_target
    return low <= price_target
