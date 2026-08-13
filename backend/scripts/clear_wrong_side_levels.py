"""Clear stop and target levels that sit on the wrong side of the traded price.

The plausibility check asks only *how far* a level is from the price the signal
was recorded at, never *which side* of it the level is on. A plan drawn around
an entry the market never came back to passes it easily. ZBH on 2026-08-12 is
the case that showed it: the trader proposed buying a pullback to $91.00 with a
stop at $90.76 and a target at $92.00, the stock was at $97.89, and all three
levels are within 8% of that price. The signal was stored with a target the
market had already passed, so the auto trader had no usable exit to arm and the
watchdog had a target it could never report reaching.

Levels are only ever read from the traded price forward. A target under it is
reached the instant it is written; a stop over it triggers the same way.

The derived numbers go out with their inputs, the same rule ``_trade_plan_levels``
follows: ``risk_reward`` and ``expected_value_r`` are computed *from* the levels,
so a confident "4.17 : 1" beside a row with no target describes nothing.
``win_probability`` stays — it is the model's own estimate.

Safe to re-run. Sell-ish signals are left alone (this app is long-only and their
levels point the other way by design), and so is any signal already graded —
grading read the target to decide ``price_target_hit``, and clearing it now
would contradict a verdict already given.

    python -m backend.scripts.clear_wrong_side_levels [--apply]
"""
import sys

from sqlmodel import Session, select

from backend.database.engine import engine
from backend.database.models import Signal
from backend.services.signals import SELLISH_DECISIONS


def main() -> int:
    apply = "--apply" in sys.argv
    changed = skipped_graded = 0

    with Session(engine) as session:
        for signal in session.exec(select(Signal).order_by(Signal.id)).all():
            if signal.decision in SELLISH_DECISIONS or not signal.price_at_signal:
                continue
            price = signal.price_at_signal
            bad_stop = signal.stop_loss is not None and signal.stop_loss >= price
            bad_target = signal.price_target is not None and signal.price_target <= price
            if not bad_stop and not bad_target:
                continue
            if signal.outcome is not None:
                skipped_graded += 1
                print(f"  #{signal.id:<3} {signal.ticker:<6} graded already — left alone")
                continue

            problems = []
            if bad_stop:
                problems.append(f"stop {signal.stop_loss} at or above")
            if bad_target:
                problems.append(f"target {signal.price_target} at or below")
            print(
                f"  #{signal.id:<3} {signal.ticker:<6} {signal.signal_date}  "
                f"{signal.decision:<11} priced {price:.2f} — {', '.join(problems)}"
            )
            if apply:
                if bad_stop:
                    signal.stop_loss = None
                if bad_target:
                    signal.price_target = None
                signal.risk_reward = None
                signal.expected_value_r = None
                session.add(signal)
            changed += 1
        if apply:
            session.commit()

    print()
    print(f"{changed} signal(s) {'cleared' if apply else 'would be cleared'}")
    if skipped_graded:
        print(f"{skipped_graded} left alone because they are already graded")
    if not apply:
        print("Dry run — pass --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
