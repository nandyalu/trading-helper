"""Re-read each signal's price target from the plan that computed its risk/reward.

The trader labels the number "Target Price" and the portfolio manager labels it
"Price Target" — the same words in the other order. Only the manager's label
was read, so ``extract_price_target`` silently returned None on a trader plan
and the target fell back to the manager's while the entry, stop, risk/reward
and expected value beside it stayed the trader's. Nothing failed; the rows just
stopped describing one trade. ADT on 2026-08-12 stored a 0.08 risk/reward that
only makes sense against a target it did not keep, and GOOG on 2026-08-10
stored a target equal to its own entry — zero reward — beside a 2.5 to 1.

Safe to re-run: it only rewrites rows where the trader stated a target that
differs from the stored one, and it leaves a graded signal alone. Grading reads
the target to decide ``price_target_hit``, so changing it afterwards would
silently disagree with a verdict already given.

    python -m backend.scripts.fix_signal_targets [--apply]
"""
import sys

from sqlmodel import Session, select

from backend.database.engine import engine
from backend.database.models import Signal, SignalReport
from backend.services.signals import extract_trader_target


def main() -> int:
    apply = "--apply" in sys.argv
    changed = skipped_graded = 0

    with Session(engine) as session:
        plans = {
            row.signal_id: row.content
            for row in session.exec(
                select(SignalReport).where(SignalReport.report_type == "trader_investment_plan")
            ).all()
        }
        for signal in session.exec(select(Signal).order_by(Signal.id)).all():
            trader_target = extract_trader_target(plans.get(signal.id))
            if trader_target is None or signal.price_target is None:
                continue
            if abs(trader_target - signal.price_target) <= 0.005:
                continue
            if signal.outcome is not None:
                # Already graded against the old target; rewriting it now would
                # contradict the price_target_hit already recorded.
                skipped_graded += 1
                print(f"  #{signal.id:<3} {signal.ticker:<6} graded already — left alone")
                continue
            print(
                f"  #{signal.id:<3} {signal.ticker:<6} {signal.signal_date}  "
                f"{signal.price_target:>8} -> {trader_target:<8} (rr {signal.risk_reward})"
            )
            if apply:
                signal.price_target = trader_target
                session.add(signal)
            changed += 1
        if apply:
            session.commit()

    print()
    print(f"{changed} signal(s) {'corrected' if apply else 'would be corrected'}")
    if skipped_graded:
        print(f"{skipped_graded} left alone because they are already graded")
    if not apply:
        print("Dry run — pass --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
