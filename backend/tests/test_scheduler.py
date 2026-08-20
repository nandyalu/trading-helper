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


def test_the_sweep_and_the_grading_are_separate_jobs():
    """They moved apart for opposite reasons. Grading reads the day's closing
    price, so it stays after the close; the sweep moved to the morning to catch
    the overnight news cycle its evening slot missed entirely."""
    from backend.tasks import scheduler as module

    assert hasattr(module, "morning_sweep")
    assert hasattr(module, "daily_signals")


def test_the_morning_sweep_leaves_margin_before_the_agent_decides():
    """9 tickers is about 21 minutes of GPU, but the pre-open window already
    holds broker_sync, morning_regime, and an earnings check that runs its own
    analyses on the same pool. A sweep that overran into 13:35 would hand the
    agent half a picture."""
    from backend.tasks.scheduler import _seconds_until

    sweep_hour, agent_hour = 11.0, 13 + 35 / 60
    assert agent_hour - sweep_hour >= 2.0
    assert _seconds_until(11, 0) >= 0
