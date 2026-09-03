"""The agent's clock, and the bounds on the time it may ask for.

It had no clock at all until 2026-09-03, which was survivable while it decided
once at the open. It is not survivable once it chooses its own next wakeup,
because that is a question about the time.
"""
import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.services import market_clock as mc

ET = ZoneInfo("America/New_York")


def at(hour, minute=0, day=3):
    """A Thursday in September, Eastern."""
    return datetime.datetime(2026, 9, day, hour, minute, tzinfo=ET)


# --- what it tells the agent ---------------------------------------------------


def test_it_says_how_long_is_left():
    said = mc.describe(at(9, 35))
    assert "9:35 AM Eastern" in said
    assert "6h 25m" in said


def test_it_says_when_the_session_is_over():
    assert "closed for the day" in mc.describe(at(17, 10))


def test_it_says_when_the_market_has_not_opened():
    assert "has not opened yet" in mc.describe(at(7, 0))


def test_it_knows_a_weekend():
    assert "closed for the weekend" in mc.describe(at(11, 0, day=5))  # Saturday


# --- the bounds on a requested wakeup ------------------------------------------


def test_a_sensible_request_is_left_alone():
    assert mc.clamp_wakeup(at(11, 0), at(10, 0)) == at(11, 0)


def test_asking_for_nothing_stays_nothing():
    """None is not a decision. The scheduler falls back, and the agent is not
    credited with having chosen the fallback."""
    assert mc.clamp_wakeup(None, at(10, 0)) is None


def test_too_soon_is_pushed_to_the_floor():
    """Below five minutes the book has not moved enough to be worth a fresh
    opinion — the agent would read the same numbers again."""
    assert mc.clamp_wakeup(at(10, 1), at(10, 0)) == at(10, 0) + mc.MIN_WAKEUP


def test_too_far_is_pulled_to_the_ceiling():
    assert mc.clamp_wakeup(at(23, 0), at(10, 0)) == at(10, 0) + mc.MAX_WAKEUP


def test_past_the_close_becomes_the_next_open():
    """Deliberately not the final pass. That one runs anyway, and folding a
    request into it would turn "look tomorrow" into "look at 3:55"."""
    got = mc.clamp_wakeup(at(17, 0), at(15, 0))
    assert got == at(9, 30, day=4)


def test_a_friday_afternoon_request_skips_the_weekend():
    friday = datetime.datetime(2026, 9, 4, 15, 30, tzinfo=ET)
    got = mc.clamp_wakeup(friday + datetime.timedelta(hours=3), friday)
    assert got.weekday() == 0  # Monday
    assert got.time() == datetime.time(9, 30)


@pytest.mark.parametrize("minutes", [5, 30, 120, 360])
def test_every_allowed_gap_survives_the_clamp(minutes):
    now = at(10, 0)
    wanted = now + datetime.timedelta(minutes=minutes)
    assert mc.clamp_wakeup(wanted, now) == wanted
