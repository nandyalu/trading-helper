"""Pure logic for turning a TradingAgents rationale into a trackable signal:
parsing the free-text time horizon into an evaluation date, and judging
pass/fail once a follow-up price is available. Mirrors backend/services/positions.py's
style — no DB or Discord access here, see backend/database/db.py for persistence.
"""
import re
from dataclasses import dataclass

BUYISH_DECISIONS = frozenset({"Buy", "Overweight"})
SELLISH_DECISIONS = frozenset({"Sell", "Underweight"})

_MONTH_RE = re.compile(r"(\d+)\s*(?:-\s*(\d+)\s*)?month", re.IGNORECASE)
_WEEK_RE = re.compile(r"(\d+)\s*(?:-\s*(\d+)\s*)?week", re.IGNORECASE)
_DAY_RE = re.compile(r"(\d+)\s*(?:-\s*(\d+)\s*)?day", re.IGNORECASE)

_TIME_HORIZON_RE = re.compile(r"\*\*Time Horizon\*\*:\s*(.+)")
_PRICE_TARGET_RE = re.compile(r"\*\*Price Target\*\*:\s*\$?([\d.]+)")

# Labels emitted by TradingAgents' trader stage. render_trader_proposal()
# (TradingAgents/tradingagents/agents/schemas.py) writes the first three, and
# _render_trade_review() writes the rest. The review numbers are computed in
# Python from the entry/stop/target levels rather than by the model, so they
# are arithmetically consistent with each other — worth keeping as given
# instead of recomputing here.
_ENTRY_PRICE_RE = re.compile(r"\*\*Entry Price\*\*:\s*\$?([\d.]+)")
_STOP_LOSS_RE = re.compile(r"\*\*Stop Loss\*\*:\s*\$?([\d.]+)")
_WIN_PROBABILITY_RE = re.compile(r"\*\*Win Probability\*\*:\s*([\d.]+)\s*%")
_RISK_REWARD_RE = re.compile(r"\*\*Risk/Reward Ratio\*\*:\s*([\d.]+)\s*:\s*1")
_EXPECTED_VALUE_RE = re.compile(r"\*\*Expected Value\*\*:\s*([+-]?[\d.]+)\s*R")

_DEFAULT_HOLD_BAND_PCT = 10.0

# Per-horizon grading parameters. Both scale with the length of the window, so
# a single set of constants cannot serve both horizons:
#
# - ``eval_days`` is how long to wait before grading a signal whose own stated
#   horizon was unparseable. TradingAgents is asked for 5-10 trading days on a
#   swing run, so 14 calendar days is the middle of that range.
# - ``hold_band_pct`` is how far price may drift before a Hold counts as wrong.
#   ±10% over six months is a tight-ish band; over two weeks it is so wide that
#   almost every Hold passes and the grade stops carrying information. Roughly
#   scaling with the square root of time (10% × √(14/180) ≈ 2.8%) gives about
#   3%, rounded up to 4% to stay forgiving of a single volatile session.
# - ``max_eval_days`` caps a horizon the model states for itself. The prompt
#   asks a swing run for weeks, but a model that ignores that and answers "3-6
#   months" would otherwise book a 135-day evaluation. Grading at the cap is
#   closer to what was asked for than honoring the drift.
# - ``max_level_deviation_pct`` is how far a stated entry / stop / target may
#   sit from the price when the signal was made before it is treated as
#   invented rather than intended. See plausible_level().
HORIZONS = {
    "swing": {
        "eval_days": 14,
        "max_eval_days": 21,
        "hold_band_pct": 4.0,
        "max_level_deviation_pct": 35.0,
    },
    "position": {
        "eval_days": 30,
        "max_eval_days": 270,
        "hold_band_pct": _DEFAULT_HOLD_BAND_PCT,
        "max_level_deviation_pct": 70.0,
    },
}
DEFAULT_HORIZON = "swing"


def horizon_params(horizon: str | None) -> dict:
    """Grading parameters for a horizon, falling back to the default for an
    unknown or missing value rather than raising — a bad setting should not
    stop a signal from being graded."""
    return HORIZONS.get((horizon or "").strip().lower(), HORIZONS[DEFAULT_HORIZON])


def parse_time_horizon_days(
    text: str | None, default_days: int = 30, max_days: int | None = None
) -> int:
    """Best-effort: "3-6 months" -> ~135 days, "2 weeks" -> 14. Falls back to
    ``default_days`` when absent or unparseable (e.g. "long-term"), and to
    ``max_days`` when the model states a horizon longer than the run asked
    for."""
    if not text:
        return min(default_days, max_days) if max_days else default_days
    for pattern, unit_days in ((_MONTH_RE, 30), (_WEEK_RE, 7), (_DAY_RE, 1)):
        match = pattern.search(text)
        if match:
            low = int(match.group(1))
            high = int(match.group(2)) if match.group(2) else low
            days = max(1, round((low + high) / 2 * unit_days))
            return min(days, max_days) if max_days else days
    return min(default_days, max_days) if max_days else default_days


def extract_time_horizon(rationale: str) -> str | None:
    match = _TIME_HORIZON_RE.search(rationale)
    return match.group(1).strip() if match else None


def _extract_float(pattern: re.Pattern, text: str | None) -> float | None:
    """None when the label is absent or its value doesn't parse. The character
    class in these patterns admits strings float() rejects — "1.2.3" from a
    model that formats badly — and an exception here would abort a whole
    analysis over a cosmetic problem in one field."""
    if not text:
        return None
    match = pattern.search(text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def extract_price_target(rationale: str) -> float | None:
    return _extract_float(_PRICE_TARGET_RE, rationale)


# --- Trader-plan fields ------------------------------------------------------
#
# These read final_state["trader_investment_plan"], not the final decision
# text. The portfolio manager's PortfolioDecision carries only a rating,
# summary, thesis, price target, and time horizon; the levels a trade actually
# needs — where to get out, and how good the bet is — live one stage earlier on
# the trader's proposal.


def extract_entry_price(trader_plan: str | None) -> float | None:
    return _extract_float(_ENTRY_PRICE_RE, trader_plan)


def extract_stop_loss(trader_plan: str | None) -> float | None:
    """The price at which the thesis is wrong. Quoted against the trader's own
    proposed entry, which may differ from what you actually paid — callers
    comparing it to a real position should treat it as a level, not as a
    percentage below cost."""
    return _extract_float(_STOP_LOSS_RE, trader_plan)


def extract_win_probability(trader_plan: str | None) -> float | None:
    """0-100. The model's own estimate, and the one field here it produces
    rather than derives, so it is the one most worth calibrating against
    realized outcomes before trusting."""
    value = _extract_float(_WIN_PROBABILITY_RE, trader_plan)
    if value is None or not 0 <= value <= 100:
        return None
    return value


def extract_risk_reward(trader_plan: str | None) -> float | None:
    """Reward divided by risk, from a "2.50 : 1" line. Absent when the trader
    gave no entry/stop/target, in which case the source line reads "n/a"."""
    return _extract_float(_RISK_REWARD_RE, trader_plan)


def extract_expected_value(trader_plan: str | None) -> float | None:
    """Expected value in R-multiples: ``p × rr − (1 − p)``. Positive means the
    bet pays at the stated probability. Signed, so a negative value is a real
    reading and not a parse failure."""
    return _extract_float(_EXPECTED_VALUE_RE, trader_plan)


def plausible_level(
    level: float | None, reference_price: float | None, max_deviation_pct: float
) -> float | None:
    """Return ``level`` when it is near ``reference_price``, otherwise None.

    A small local model reasons acceptably in prose but does not reliably carry
    concrete figures into structured numeric fields. Observed on a $1.26 stock:
    one run proposed an entry of $4.50, another $30.00, both with sound
    ticker-specific reasoning around them. The numbers are invented, not read
    off the data — the market analyst's own report had the right prices.

    A trade plan is built around the price you can actually trade at, so a
    level far from it is not a plan. Dropping it is strictly better than
    storing it: a fabricated stop would arm a watchdog alert at a price the
    stock may never see, or fire one immediately.

    Returns None for a non-positive reference price, since "percent away from
    zero" has no meaning.
    """
    if level is None or reference_price is None or reference_price <= 0:
        return None
    deviation_pct = abs(level / reference_price - 1) * 100
    # Epsilon because a level exactly at the limit lands a hair above it in
    # binary floating point (135/100 - 1 == 0.3500000000000001), and rejecting
    # a level for being 0.0000000000001% too far is not a judgment anyone meant
    # to make.
    return level if deviation_pct <= max_deviation_pct + 1e-9 else None


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
