"""Every timestamp the API sends must say it is UTC.

This is not cosmetic. SQLite has no timezone type, so a value written with
``datetime.now(timezone.utc)`` comes back naive and serializes with no offset.
A browser parses such a string as *local* time, so the instant it shows is
wrong by the reader's own offset.

The bug hid for months because it was invisible on UTC: the frontend also
formatted in local time and printed a fixed "UTC" label, so the two errors
cancelled and the number read correctly. It only appears once a page renders
a timestamp in the reader's own zone, which is what these tests protect.
"""
import datetime
import json

from backend.api import schemas


def test_a_naive_datetime_goes_out_marked_utc():
    event = schemas.AgentEventOut(
        id=1,
        ran_at=datetime.datetime(2026, 9, 3, 11, 35, 39),
        orders=[], refusals=[], failures=[], notes=[],
    )
    assert json.loads(event.model_dump_json())["ran_at"] == "2026-09-03T11:35:39Z"


def test_an_already_aware_datetime_is_left_alone():
    """Stamping an aware value would be a second conversion, not a fix."""
    aware = datetime.datetime(2026, 9, 3, 11, 35, 39, tzinfo=datetime.timezone.utc)
    event = schemas.AgentEventOut(
        id=1, ran_at=aware, orders=[], refusals=[], failures=[], notes=[],
    )
    assert json.loads(event.model_dump_json())["ran_at"] == "2026-09-03T11:35:39Z"


def test_a_calendar_date_keeps_no_timezone():
    """A date has no zone. Giving it one moves it across midnight for every
    reader west of UTC — "graded 3 September" would read as the 2nd."""
    point = schemas.AgentEquityPointOut(
        date=datetime.date(2026, 9, 3), equity=1.0, cash=1.0, market_value=0.0,
    )
    assert json.loads(point.model_dump_json())["date"] == "2026-09-03"


def test_every_schema_inherits_the_stamp():
    """A new response model on plain ``BaseModel`` would silently opt out, which
    is exactly how ``AgentEventOut.ran_at`` — the decisions page — missed it."""
    from pydantic import BaseModel

    strays = [
        name for name, obj in vars(schemas).items()
        if isinstance(obj, type) and issubclass(obj, BaseModel)
        and obj not in (BaseModel, schemas.Schema)
        and not issubclass(obj, schemas.Schema)
    ]
    assert strays == [], f"response models bypassing the UTC stamp: {strays}"
