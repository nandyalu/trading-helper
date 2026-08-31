"""What the comparison sweep tells Discord.

The message used to end "see the scorecard's by-model table". That table
counts resolved signals only, so a reader who followed it on the day of a
sweep found the new model absent and nothing explaining why — which is exactly
what happened on 2026-08-31, nine days into the Gemini comparison and a day
before its first signal was due to grade.
"""
import datetime

from backend.tasks import scheduler


class Recorded:
    def __init__(self, evaluation_date):
        self.evaluation_date = evaluation_date


def _notice(recorded, tickers=9, model="gemini-3.5-flash-lite") -> str:
    """The message body, built the way _morning_sweep_job builds it."""
    due = sorted(s.evaluation_date for s in recorded if s.evaluation_date)
    when = (
        f" The first grades {due[0]:%b %-d} and the last {due[-1]:%b %-d}; "
        "until then they are pending and the scorecard's by-model table, "
        "which counts resolved signals only, will not list this model."
        if due else ""
    )
    return (f"🔬 Comparison: {len(recorded)} of {tickers} tickers analysed on "
            f"`{model}`. They grade like any other signal.{when}")


def test_it_says_when_the_first_and_last_signal_grade():
    recorded = [Recorded(datetime.date(2026, 9, 10)),
                Recorded(datetime.date(2026, 9, 4)),
                Recorded(datetime.date(2026, 9, 14))]

    message = _notice(recorded)

    assert "first grades Sep 4" in message
    assert "last Sep 14" in message


def test_it_explains_why_the_scorecard_is_empty_until_then():
    """The gap that sent someone looking. Naming the reason costs one clause
    and saves the reader a hunt through a page that is working correctly."""
    message = _notice([Recorded(datetime.date(2026, 9, 4))])

    assert "counts resolved signals only" in message
    assert "will not list this model" in message


def test_a_signal_with_no_evaluation_date_is_skipped_rather_than_crashing():
    """A signal recorded outside the normal path can carry no date. The notice
    is telemetry: it must never be the reason a sweep reports a failure."""
    message = _notice([Recorded(None), Recorded(datetime.date(2026, 9, 4))])

    assert "first grades Sep 4" in message


def test_no_dates_at_all_leaves_the_promise_off():
    """Better to say nothing about timing than to say something wrong."""
    message = _notice([Recorded(None)])

    assert "grade like any other signal." in message
    assert "grades" not in message.split("like any other signal.")[1]


def test_the_scheduler_builds_the_same_message():
    """Guards against this test drifting from the code it describes."""
    import inspect

    source = inspect.getsource(scheduler._morning_sweep_job)

    assert "counts resolved signals only" in source
    assert "%b %-d" in source
