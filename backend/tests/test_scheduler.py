"""Unit tests for _seconds_until() (backend/tasks/scheduler.py) — quiv has no
cron/calendar scheduling, so the daily jobs approximate a fixed UTC time via
interval=86400 + a delay computed by this helper."""
import datetime

import pytest

from backend.tasks.scheduler import _seconds_until


def _fixed_now(monkeypatch, iso: str) -> None:
    fixed = datetime.datetime.fromisoformat(iso).replace(tzinfo=datetime.timezone.utc)

    class _FixedDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed if tz else fixed.replace(tzinfo=None)

    monkeypatch.setattr(datetime, "datetime", _FixedDatetime)


def test_target_later_today(monkeypatch):
    _fixed_now(monkeypatch, "2026-08-05T10:00:00")
    assert _seconds_until(21, 30) == pytest.approx(11.5 * 3600)


def test_target_already_passed_rolls_to_tomorrow(monkeypatch):
    _fixed_now(monkeypatch, "2026-08-05T22:00:00")
    # 21:30 already passed today -> next occurrence is tomorrow, 23.5h away.
    assert _seconds_until(21, 30) == pytest.approx(23.5 * 3600)


def test_target_equals_now_rolls_to_tomorrow(monkeypatch):
    _fixed_now(monkeypatch, "2026-08-05T21:30:00")
    assert _seconds_until(21, 30) == pytest.approx(24 * 3600)
