"""Is the model's stated confidence worth anything?

``win_probability`` is the one number in a signal the model asserts rather than
derives. Everything else on the trade plan is arithmetic — risk/reward comes
from the levels, expected value comes from the probability and the risk/reward
together — so an inflated probability quietly inflates every figure computed
downstream of it, and nothing has ever checked it.

The check is the obvious one and it needs no new data. Group resolved signals
by the confidence the model claimed, and compare each group's claim against how
often it was actually right. A model claiming 65% and passing 40% of the time
is not slightly optimistic; it is telling you a losing bet is a winning one.

Two ways to be wrong that this distinguishes:

- **Overconfident** — the claim exceeds the outcome. The dangerous direction:
  every expected value reads positive when it is not.
- **Undiscriminating** — the claims may be roughly right on average and still
  useless, because high-confidence signals do no better than low-confidence
  ones. A number that does not sort outcomes cannot inform a decision, however
  well it is centered.

Graded on the absolute outcome, not the vs-SPY one. "The thesis plays out" is
a claim about the stock, and the benchmark grade asks a second question the
model was never making a claim about.

Pure apart from ``build_calibration``, which adds the DB read.
"""
from dataclasses import dataclass, field

from backend.database import db
from backend.database.models import Signal

# Buckets by stated confidence. Ten-point bands are wide enough that a handful
# of signals lands in each rather than spreading one per band across the page.
_BANDS = [(0, 50), (50, 60), (60, 70), (70, 80), (80, 101)]

# Below this, the comparison is anecdote. The scorecard uses the same threshold
# for the same reason: three wins in four reads as 75% and means nothing.
MIN_FOR_A_VERDICT = 20

# How far the claim may sit above the outcome before it is worth naming, in
# percentage points. Sampling noise alone moves a small book by more than a
# few points, so a tighter line would cry wolf.
_OVERCONFIDENCE_TOLERANCE = 10.0


@dataclass
class Band:
    """One confidence band: what the model claimed, and what happened."""

    low: int
    high: int
    total: int = 0
    passes: int = 0
    stated_sum: float = 0.0

    @property
    def label(self) -> str:
        return f"{self.low}–{self.high - 1}%" if self.high <= 100 else f"{self.low}%+"

    @property
    def stated_pct(self) -> float | None:
        """The average confidence claimed in this band, not the band's midpoint
        — a band holding four signals all claiming 65% claims 65%, not 65 by
        construction."""
        return self.stated_sum / self.total if self.total else None

    @property
    def actual_pct(self) -> float | None:
        return self.passes / self.total * 100 if self.total else None

    @property
    def gap(self) -> float | None:
        """Claimed minus actual, in percentage points. Positive is
        overconfident, which is the direction that costs money."""
        stated, actual = self.stated_pct, self.actual_pct
        return None if stated is None or actual is None else stated - actual


@dataclass
class Calibration:
    resolved: int = 0
    passes: int = 0
    stated_sum: float = 0.0
    bands: list[Band] = field(default_factory=list)

    @property
    def stated_pct(self) -> float | None:
        return self.stated_sum / self.resolved if self.resolved else None

    @property
    def actual_pct(self) -> float | None:
        return self.passes / self.resolved * 100 if self.resolved else None

    @property
    def gap(self) -> float | None:
        stated, actual = self.stated_pct, self.actual_pct
        return None if stated is None or actual is None else stated - actual

    @property
    def populated_bands(self) -> list[Band]:
        return [b for b in self.bands if b.total]

    @property
    def sorts_outcomes(self) -> bool | None:
        """Do higher-confidence signals actually win more often?

        This is the question that decides whether the number is usable at all:
        a probability that does not separate winners from losers cannot inform
        a threshold, however well centered it is.

        None until the book is large enough to mean anything. It is tempting to
        answer from whatever bands exist — but on the first 19 graded signals
        the bands ran 40%, 83%, 50%, and comparing only the ends of that
        returns "yes, it sorts" from a shape that plainly does not. Bands hold
        a fraction of an already-small book, so this needs the full threshold,
        not a lower one.
        """
        bands = self.populated_bands
        if self.resolved < MIN_FOR_A_VERDICT or len(bands) < 2:
            return None
        return bands[-1].actual_pct > bands[0].actual_pct

    @property
    def verdict(self) -> str:
        """One sentence, in the terms the number is actually used for."""
        if self.resolved < MIN_FOR_A_VERDICT:
            return (
                f"{self.resolved} graded signal(s) state a confidence — too few to judge. "
                f"A verdict needs {MIN_FOR_A_VERDICT}."
            )
        gap = self.gap or 0.0
        if gap > _OVERCONFIDENCE_TOLERANCE:
            return (
                f"Overconfident: the model claims {self.stated_pct:.0f}% and is right "
                f"{self.actual_pct:.0f}% of the time. Every expected value on the dashboard is "
                f"inflated by roughly that much."
            )
        if gap < -_OVERCONFIDENCE_TOLERANCE:
            return (
                f"Underconfident: the model claims {self.stated_pct:.0f}% and is right "
                f"{self.actual_pct:.0f}% of the time. Its good calls are better than it says."
            )
        if self.sorts_outcomes is False:
            return (
                f"Well centered at {self.stated_pct:.0f}% claimed against {self.actual_pct:.0f}% "
                f"actual, but the number does not sort outcomes — its confident calls do no "
                f"better than its doubtful ones, so it cannot be used as a filter."
            )
        return (
            f"Roughly honest: the model claims {self.stated_pct:.0f}% and is right "
            f"{self.actual_pct:.0f}% of the time."
        )


def calibrate(resolved: list[Signal]) -> Calibration:
    """Pure. ``resolved`` is graded signals; ones with no stated confidence are
    skipped rather than counted as zero — the model declining to state a
    probability is not a claim of 0%."""
    result = Calibration(bands=[Band(low=low, high=high) for low, high in _BANDS])
    for signal in resolved:
        stated = signal.win_probability
        if stated is None or signal.outcome not in ("pass", "fail"):
            continue
        won = signal.outcome == "pass"
        result.resolved += 1
        result.passes += won
        result.stated_sum += stated
        for band in result.bands:
            if band.low <= stated < band.high:
                band.total += 1
                band.passes += won
                band.stated_sum += stated
                break
    return result


def build_calibration() -> Calibration:
    """Blocking (DB read) — run from a thread when called off the event loop."""
    return calibrate(db.get_resolved_signals())
