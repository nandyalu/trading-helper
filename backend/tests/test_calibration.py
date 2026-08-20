"""Whether the model's stated confidence is worth anything.

win_probability is the one number a signal asserts rather than derives, and
every expected value on the dashboard is computed from it. Nothing checked it
until this existed.

Pure — signals are constructed in memory.
"""
from backend.database.models import Signal
from backend.services import calibration


def _signal(probability: float | None, outcome: str | None):
    return Signal(
        ticker="AAA",
        decision="Buy",
        rationale="",
        price_at_signal=100.0,
        win_probability=probability,
        outcome=outcome,
    )


def test_a_model_that_claims_more_than_it_delivers_is_named_overconfident():
    """The direction that costs money: every expected value on the dashboard
    reads positive when it is not."""
    signals = [_signal(80.0, "pass")] * 4 + [_signal(80.0, "fail")] * 16

    result = calibration.calibrate(signals)

    assert result.stated_pct == 80.0
    assert result.actual_pct == 20.0
    assert "Overconfident" in result.verdict


def test_a_well_centered_model_is_not_scolded():
    signals = [_signal(60.0, "pass")] * 12 + [_signal(60.0, "fail")] * 8

    result = calibration.calibrate(signals)

    assert "Roughly honest" in result.verdict


def test_a_number_that_does_not_sort_outcomes_is_called_out():
    """Being right on average is not enough. If confident calls do no better
    than doubtful ones, the number cannot be used as a filter — which is
    exactly what the conviction threshold would try to do with it."""
    # 45% band wins often, 65% band rarely; centred overall, useless as a sort.
    signals = [_signal(45.0, "pass")] * 8 + [_signal(45.0, "fail")] * 2
    signals += [_signal(65.0, "pass")] * 3 + [_signal(65.0, "fail")] * 7

    result = calibration.calibrate(signals)

    assert result.sorts_outcomes is False
    assert "does not sort outcomes" in result.verdict


def test_it_refuses_a_verdict_on_too_few_signals():
    """Three wins in four reads as 75% and means nothing."""
    result = calibration.calibrate([_signal(60.0, "pass")] * 3)

    assert "too few to judge" in result.verdict


def test_it_refuses_to_say_whether_it_sorts_on_too_few_signals():
    """The real book's first 19 graded signals ran 40%, 83%, 50% across three
    bands. Comparing only the ends answers "yes, it sorts" from a shape that
    plainly does not."""
    signals = [_signal(45.0, "fail")] * 3 + [_signal(45.0, "pass")] * 2
    signals += [_signal(55.0, "pass")] * 5 + [_signal(55.0, "fail")]
    signals += [_signal(65.0, "pass")] * 4 + [_signal(65.0, "fail")] * 4

    result = calibration.calibrate(signals)

    assert result.resolved == 19
    assert result.sorts_outcomes is None


def test_a_signal_with_no_stated_confidence_is_skipped_not_counted_as_zero():
    """The model declining to state a probability is not a claim of 0%."""
    result = calibration.calibrate([_signal(None, "pass"), _signal(60.0, "pass")])

    assert result.resolved == 1


def test_an_ungraded_signal_is_skipped():
    result = calibration.calibrate([_signal(60.0, None)])

    assert result.resolved == 0
    assert result.bands == [] or all(b.total == 0 for b in result.bands)


def test_a_band_reports_what_was_claimed_not_its_own_midpoint():
    """A band holding four signals that all claim 65% claims 65%, not 65 by
    construction — the distinction matters once a band is wide."""
    result = calibration.calibrate([_signal(61.0, "pass"), _signal(69.0, "fail")])

    band = result.populated_bands[0]
    assert band.stated_pct == 65.0
    assert band.label == "60–69%"
