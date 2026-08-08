"""Detecting tickers that have stopped trading.

A delisted symbol does not fail cleanly. AILEQ, delisted, kept returning data
from yfinance — five bars across two months, every one priced at $0.000001.
Nothing about that looks like an error: to the bar cache it is a ticker merely
behind, so it refetched every half hour forever, and the daily sweep spent
minutes of GPU analyzing a company with no market, then could not record the
signal because there was no price to record it against.

The rule is about freshness, not price. A live ticker produces a bar every
session. A price threshold would be wrong — a real penny stock at $0.0001 is
still real.
"""
import datetime

import pytest

from backend.services import listings

# A Friday, so weekday arithmetic in these tests is easy to follow.
TODAY = datetime.date(2026, 8, 7)


def _days_ago(trading_days: int) -> datetime.date:
    """A date ``trading_days`` weekdays before TODAY."""
    day = TODAY
    remaining = trading_days
    while remaining:
        day -= datetime.timedelta(days=1)
        if day.weekday() < 5:
            remaining -= 1
    return day


# --- detection ---------------------------------------------------------------


def test_a_ticker_with_a_recent_bar_stays_active():
    assert listings.record_fetch("NVDA", _days_ago(1), TODAY) is False
    assert listings.is_inactive("NVDA") is False


def test_a_long_gap_marks_it_inactive():
    assert listings.record_fetch("AILEQ", _days_ago(20), TODAY) is True
    assert listings.is_inactive("AILEQ") is True


def test_no_data_at_all_marks_it_inactive():
    assert listings.record_fetch("NOTREAL", None, TODAY) is True
    assert listings.is_inactive("NOTREAL") is True


def test_the_threshold_is_generous_enough_for_a_holiday_week():
    """A long weekend plus a provider outage must not retire a healthy ticker.
    The cost of being slow here is a few wasted requests; the cost of a false
    positive is silently ignoring a position the user holds."""
    assert listings.record_fetch("SPY", _days_ago(listings.STALE_AFTER_TRADING_DAYS), TODAY) is False


def test_one_day_past_the_threshold_trips_it():
    assert (
        listings.record_fetch("DEAD", _days_ago(listings.STALE_AFTER_TRADING_DAYS + 1), TODAY)
        is True
    )


def test_a_weekend_gap_is_not_counted_as_staleness():
    # Monday, with Friday's bar: two calendar days, zero trading days.
    monday = datetime.date(2026, 8, 10)
    friday = datetime.date(2026, 8, 7)
    assert listings.record_fetch("NVDA", friday, monday) is False


def test_a_resumed_listing_becomes_active_again():
    """Halts lift and symbols get reused. Recovering must not need anyone to
    notice and intervene."""
    listings.record_fetch("HALT", None, TODAY)
    assert listings.is_inactive("HALT") is True
    listings.record_fetch("HALT", TODAY, TODAY)
    assert listings.is_inactive("HALT") is False


# --- fetch gating ------------------------------------------------------------


def test_an_active_ticker_is_always_fetched():
    listings.record_fetch("NVDA", _days_ago(1), TODAY)
    assert listings.should_fetch("NVDA") is True


def test_an_inactive_ticker_is_not_fetched_again_today():
    listings.record_fetch("AILEQ", None, TODAY)
    assert listings.should_fetch("AILEQ") is False


def test_an_inactive_ticker_is_rechecked_the_next_day():
    # The single daily request is what makes recovery possible at all.
    listings.record_fetch("AILEQ", None, TODAY)
    tomorrow = datetime.datetime.now(datetime.timezone.utc) + listings.RECHECK_INTERVAL
    assert listings.should_fetch("AILEQ", now=tomorrow) is True


def test_an_unknown_ticker_is_fetched():
    assert listings.should_fetch("NEVERSEEN") is True


# --- manual override ---------------------------------------------------------


def test_a_manual_ignore_survives_detection():
    listings.set_manual("MEME", inactive=True, reason="not interested")
    listings.record_fetch("MEME", TODAY, TODAY)  # plenty fresh
    assert listings.is_inactive("MEME") is True


def test_a_manual_keep_survives_detection():
    """The escape hatch when the heuristic is wrong — a thinly traded name the
    user wants followed regardless."""
    listings.set_manual("THIN", inactive=False)
    listings.record_fetch("THIN", None, TODAY)
    assert listings.is_inactive("THIN") is False


def test_clearing_the_override_hands_it_back_to_detection():
    listings.set_manual("MEME", inactive=True)
    listings.clear_manual("MEME")
    listings.record_fetch("MEME", TODAY, TODAY)
    assert listings.is_inactive("MEME") is False


def test_inactive_tickers_lists_them_sorted():
    listings.record_fetch("ZZZ", None, TODAY)
    listings.record_fetch("AAA", None, TODAY)
    listings.record_fetch("NVDA", _days_ago(1), TODAY)
    assert listings.inactive_tickers() == ["AAA", "ZZZ"]


# --- the reason a caller sees ------------------------------------------------


@pytest.mark.parametrize(
    "newest, expected_fragment",
    [(None, "no market data"), (_days_ago(30), "no new bar since")],
)
def test_the_reason_says_what_was_wrong(newest, expected_fragment):
    listings.record_fetch("DEAD", newest, TODAY)
    from backend.database import db

    assert expected_fragment in db.get_ticker_status("DEAD").reason
