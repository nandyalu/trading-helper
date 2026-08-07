"""One-off: strip invented trade-plan levels from signals already recorded.

New signals are checked as they are written (see analysis._trade_plan_levels),
but rows written before that check still carry whatever the model said. On a
$1.26 stock that included an entry of $4.50 on one run and $30.00 on another.

A fabricated stop is worse than no stop, because the watchdog acts on it: it
arms an alert at a price the stock may never reach, or fires one immediately.

    python -m backend.scripts.scrub_implausible_levels          # report only
    python -m backend.scripts.scrub_implausible_levels --yes    # clear them

Only the levels are cleared. The decision, the rationale, and the analyst
reports are untouched — the reasoning was about the right company, and it is
still the useful part of the signal. ``win_probability`` also stays: it is the
model's own estimate, not derived from the levels.
"""
import argparse
import sys

from sqlmodel import Session, select

from backend.database.engine import write_session
from backend.database.models import Signal
from backend.services.signals import horizon_params, plausible_level

_LEVEL_FIELDS = ("entry_price", "stop_loss", "price_target")
# Cleared alongside the levels: TradingAgents computes both *from* entry, stop,
# and target, so once a level is gone they describe nothing.
_DERIVED_FIELDS = ("risk_reward", "expected_value_r")


def _implausible(signal: Signal) -> dict[str, float]:
    """Levels on this signal that sit too far from its own price at the time."""
    max_deviation = horizon_params(signal.horizon)["max_level_deviation_pct"]
    bad = {}
    for field in _LEVEL_FIELDS:
        value = getattr(signal, field)
        if value is None:
            continue
        if plausible_level(value, signal.price_at_signal, max_deviation) is None:
            bad[field] = value
    return bad


@write_session
def _scan(*, _session: Session = None) -> list[tuple[Signal, dict[str, float]]]:
    rows = _session.exec(select(Signal).order_by(Signal.id)).all()
    return [(row, bad) for row in rows if (bad := _implausible(row))]


@write_session
def _scrub(*, _session: Session = None) -> int:
    rows = _session.exec(select(Signal).order_by(Signal.id)).all()
    cleared = 0
    for row in rows:
        if not _implausible(row):
            continue
        for field in _LEVEL_FIELDS + _DERIVED_FIELDS:
            setattr(row, field, None)
        _session.add(row)
        cleared += 1
    _session.commit()
    return cleared


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--yes", action="store_true", help="actually clear the levels")
    args = parser.parse_args()

    affected = _scan()
    if not affected:
        print("No signal carries an implausible level. Nothing to do.")
        return 0

    print(f"{len(affected)} signal(s) carry a level far from the price at the time:\n")
    for signal, bad in affected:
        levels = ", ".join(f"{name}=${value:,.2f}" for name, value in bad.items())
        print(f"  #{signal.id:<4} {signal.ticker:<6} {signal.signal_date}  "
              f"priced ${signal.price_at_signal:,.2f}  →  {levels}")

    if not args.yes:
        print("\nReport only. Re-run with --yes to clear these levels.")
        print("Decisions, rationales, analyst reports, and win probabilities are never touched.")
        return 0

    print(f"\nCleared levels on {_scrub()} signal(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
