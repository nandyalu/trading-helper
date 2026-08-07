"""Imported broker holdings and the date they claim to have been bought on.

A Webull sync imports every existing holding as a synthetic buy. Recording that
buy as "today" is wrong in a way that does not look wrong: the position keeps
its real cost basis, so P&L stays right, but any date-sensitive calculation is
then anchored on the import date. The vs-SPY comparison is the one that matters
— SPY gets a few days to move while the position is credited with months of
gains, which reads as enormous alpha.
"""
import datetime

import pytest

from backend.services.broker import BrokerPosition, _parse_opened_at, _parse_position, plan_sync
from backend.services.portfolio import LotComparison, compare_open_book
from backend.services.positions import ESTIMATED_DATE_NOTE, compute_position

TODAY = datetime.date.today()


# --- Reading a date off the broker payload -----------------------------------


def test_iso_date_is_used():
    assert _parse_opened_at({"open_date": "2026-03-14"}) == datetime.date(2026, 3, 14)


def test_iso_datetime_is_truncated_to_a_date():
    assert _parse_opened_at({"position_date": "2026-03-14T15:30:00Z"}) == datetime.date(2026, 3, 14)


def test_epoch_seconds_and_milliseconds_both_work():
    seconds = _parse_opened_at({"open_time": 1773446400})
    millis = _parse_opened_at({"open_time": 1773446400000})
    assert seconds == millis
    assert seconds is not None


def test_absent_or_unparseable_date_is_none():
    assert _parse_opened_at({}) is None
    assert _parse_opened_at({"open_date": ""}) is None
    assert _parse_opened_at({"open_date": "not a date"}) is None


def test_future_date_rejected():
    # A date after today means a clock or unit mix-up, not a purchase.
    future = (TODAY + datetime.timedelta(days=30)).isoformat()
    assert _parse_opened_at({"open_date": future}) is None


def test_position_parsing_carries_the_date_through():
    raw = {"symbol": "NVDA", "quantity": "10", "cost_price": "120.5", "open_date": "2026-03-14"}
    position = _parse_position(raw)
    assert position is not None
    assert position.opened_at == datetime.date(2026, 3, 14)


def test_position_without_a_date_still_parses():
    raw = {"symbol": "NVDA", "quantity": "10", "cost_price": "120.5"}
    position = _parse_position(raw)
    assert position is not None
    assert position.opened_at is None


# --- What the sync plan records ----------------------------------------------


def test_import_with_a_known_date_uses_it():
    position = BrokerPosition("NVDA", 10.0, 120.0, opened_at=datetime.date(2026, 3, 14))
    plan = plan_sync([position], {}, [])
    action = plan.transactions[0]
    assert action.date == datetime.date(2026, 3, 14)
    assert ESTIMATED_DATE_NOTE not in action.reason


def test_import_without_a_date_says_so_instead_of_guessing():
    position = BrokerPosition("NVDA", 10.0, 120.0, opened_at=None)
    plan = plan_sync([position], {}, [])
    action = plan.transactions[0]
    assert action.date is None
    assert ESTIMATED_DATE_NOTE in action.reason


def test_quantity_drift_is_dated_today_not_backdated():
    # Drift is genuinely new shares, so the sync date is the right date — and
    # backdating it to the original purchase would be its own lie.
    position = BrokerPosition("NVDA", 15.0, 120.0, opened_at=datetime.date(2026, 3, 14))
    plan = plan_sync([position], {"NVDA": 10.0}, ["NVDA"])
    action = plan.transactions[0]
    assert action.quantity == pytest.approx(5.0)
    assert action.date is None  # add_transaction defaults to today


# --- The lot, and the comparison that must skip it ---------------------------


def test_lot_is_flagged_from_the_transaction_note():
    transactions = [
        {
            "side": "buy",
            "date": TODAY.isoformat(),
            "price": 120.0,
            "quantity": 10.0,
            "note": f"webull sync: imported holding ({ESTIMATED_DATE_NOTE})",
        }
    ]
    lot = compute_position(transactions).open_lots[0]
    assert lot.date_estimated is True


def test_a_normal_lot_is_not_flagged():
    transactions = [
        {"side": "buy", "date": "2026-03-14", "price": 120.0, "quantity": 10.0, "note": None}
    ]
    assert compute_position(transactions).open_lots[0].date_estimated is False


def test_missing_note_key_does_not_crash():
    # Paper transactions and older callers return dicts without a note.
    transactions = [{"side": "buy", "date": "2026-03-14", "price": 120.0, "quantity": 10.0}]
    assert compute_position(transactions).open_lots[0].date_estimated is False


def test_estimated_lot_excluded_from_both_sides_of_the_comparison():
    """The bug this whole file exists for: a lot dated today gets a benchmark
    entry equal to today's SPY, so the benchmark shows ~0% while the position
    shows its full historical gain."""
    real = LotComparison(cost=1000.0, value_now=1100.0, benchmark_entry=500.0, benchmark_now=550.0)
    # Same treatment as any lot with no benchmark data: entry None.
    imported = LotComparison(cost=1000.0, value_now=1830.0, benchmark_entry=None, benchmark_now=550.0)

    result = compare_open_book([real, imported])
    assert result is not None
    # 10% book vs 10% SPY — the imported lot's 83% gain must not appear.
    assert result.book_return_pct == pytest.approx(10.0)
    assert result.benchmark_return_pct == pytest.approx(10.0)
    assert result.alpha_pct == pytest.approx(0.0)
    assert result.compared_cost == pytest.approx(1000.0)
