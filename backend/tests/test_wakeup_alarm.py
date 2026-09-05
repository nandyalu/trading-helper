"""The agent's chosen time is a real alarm, and it survives a restart.

A ``run_once`` quiv task fires at the second the agent asked for. quiv keeps
its tasks in a temporary file that a restart deletes, so the alarm is rebuilt
from ``agentrun.next_wakeup`` at startup. **That restore is the one step that
can end the experiment**: without it the agent has no alarm and nothing else
schedules it.
"""
import asyncio
import datetime
from zoneinfo import ZoneInfo

import pytest

from backend.tasks import scheduler

ET = ZoneInfo("America/New_York")


def _et(hour, minute=0, day=4):
    return datetime.datetime(2026, 9, day, hour, minute, tzinfo=ET)


class _Run:
    def __init__(self, next_wakeup=None):
        self.next_wakeup = next_wakeup


@pytest.fixture
def quiv(monkeypatch):
    """Records what the scheduler was asked to do."""
    calls = {"added": [], "removed": [], "fired": []}

    def add_task(task_name, func, interval, delay=0, run_once=False, **kw):
        assert run_once, "a wakeup must not repeat"
        assert interval > 0, "quiv rejects a non-positive interval even for a one-off"
        calls["added"].append(delay)
        return f"task-{len(calls['added'])}"

    monkeypatch.setattr(scheduler.scheduler, "add_task", add_task)
    monkeypatch.setattr(scheduler.scheduler, "remove_task", lambda tid: calls["removed"].append(tid))
    monkeypatch.setattr(scheduler.scheduler, "run_task_immediately", lambda tid: calls["fired"].append(tid))
    monkeypatch.setattr(scheduler, "_wakeup_task_id", None)
    monkeypatch.setattr(scheduler.market_clock, "now_et", lambda *a: _et(10, 0))
    return calls


# --- setting the alarm ---------------------------------------------------------


def test_the_alarm_is_set_for_the_time_the_agent_chose(quiv):
    scheduler._replace_wakeup_alarm(_et(10, 30))

    assert quiv["added"] == [1800]  # half an hour, in seconds


def test_a_time_already_past_fires_at_once(quiv):
    """The container was down when the wakeup came due. Ask the agent now
    rather than dropping the time it chose."""
    scheduler._replace_wakeup_alarm(_et(9, 0))

    assert quiv["added"] == [0]


def test_setting_an_alarm_replaces_the_pending_one(quiv):
    """**Not every pass consumes an alarm.** The last pass before the close does
    not, nor does the first after a restore. One of those would leave two
    alarms pending and both would fire."""
    scheduler._replace_wakeup_alarm(_et(10, 30))
    scheduler._replace_wakeup_alarm(_et(11, 0))

    assert quiv["removed"] == ["task-1"]
    assert len(quiv["added"]) == 2


def test_no_time_means_no_alarm(quiv):
    scheduler._replace_wakeup_alarm(None)

    assert quiv["added"] == []


def test_removing_an_already_fired_alarm_is_not_an_error(quiv, monkeypatch):
    """A one-off deletes itself when it fires, so the ordinary case is that the
    remove finds nothing."""
    scheduler._replace_wakeup_alarm(_et(10, 30))
    monkeypatch.setattr(
        scheduler.scheduler, "remove_task",
        lambda tid: (_ for _ in ()).throw(KeyError("gone")),
    )

    scheduler._replace_wakeup_alarm(_et(11, 0))  # must not raise

    assert len(quiv["added"]) == 2


# --- surviving a restart -------------------------------------------------------


def test_the_stored_wakeup_is_restored_at_startup(quiv, monkeypatch):
    """quiv's task file is deleted on restart. Without this the agent never
    wakes and nothing reports a problem."""
    stored = datetime.datetime(2026, 9, 4, 15, 0)  # naive UTC, as SQLite returns it
    monkeypatch.setattr(scheduler.agent.db, "get_agent_runs", lambda limit: [_Run(stored)])

    scheduler.restore_wakeup_alarm()

    assert len(quiv["added"]) == 1


def test_a_restore_with_no_stored_time_falls_back_to_the_next_open(quiv, monkeypatch):
    """An unreadable or missing wakeup must still leave the agent scheduled."""
    monkeypatch.setattr(scheduler.agent.db, "get_agent_runs", lambda limit: [_Run(None)])

    scheduler.restore_wakeup_alarm()

    assert len(quiv["added"]) == 1


def test_a_restore_with_no_runs_at_all_still_sets_an_alarm(quiv, monkeypatch):
    """A fresh database must not mean an agent that never starts."""
    monkeypatch.setattr(scheduler.agent.db, "get_agent_runs", lambda limit: [])

    scheduler.restore_wakeup_alarm()

    assert len(quiv["added"]) == 1


# --- pulling the alarm forward -------------------------------------------------


def test_an_early_pass_pulls_the_alarm_forward(quiv):
    """Friday's case: an analysis landed at 17:00, twelve minutes before the
    alarm set for 17:12. Firing the one-off now also deletes it, so the
    superseded time cannot arrive later."""
    scheduler._replace_wakeup_alarm(_et(10, 30))

    assert scheduler.wake_agent_now() is True
    assert quiv["fired"] == ["task-1"]


def test_pulling_forward_with_no_alarm_reports_it(quiv):
    """The caller then runs the pass itself rather than skipping it."""
    assert scheduler.wake_agent_now() is False


def test_a_failed_pull_reports_it(quiv, monkeypatch):
    """Already running or already fired. Either way a pass is happening, and
    the caller must not start a second."""
    scheduler._replace_wakeup_alarm(_et(10, 30))
    monkeypatch.setattr(
        scheduler.scheduler, "run_task_immediately",
        lambda tid: (_ for _ in ()).throw(RuntimeError("not active")),
    )

    assert scheduler.wake_agent_now() is False


# --- never two passes at once --------------------------------------------------


def test_two_passes_cannot_overlap(quiv, monkeypatch):
    """The alarm fires, and a second later the tick reads a next_wakeup the
    running pass has not replaced yet."""
    started = []

    async def slow_run(label):
        started.append(label)
        await asyncio.sleep(0.05)

    monkeypatch.setattr(scheduler, "_run_agent_pass_locked", slow_run)

    async def both():
        await asyncio.gather(
            scheduler._run_agent_pass("alarm"), scheduler._run_agent_pass("tick")
        )

    asyncio.run(both())

    assert started == ["alarm"]


def test_a_failed_pass_still_leaves_an_alarm(quiv, monkeypatch):
    """Without one the agent never runs again. The next open is honest: the
    pass produced no answer, so the agent chose nothing."""
    monkeypatch.setattr(
        scheduler.agent, "run_once",
        lambda: (_ for _ in ()).throw(RuntimeError("model down")),
    )

    asyncio.run(scheduler._run_agent_pass_locked("test"))

    assert len(quiv["added"]) == 1
