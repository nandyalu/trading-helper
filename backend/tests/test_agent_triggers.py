"""When the agent runs on its own.

Two paths, deliberately different. The nightly sweep goes to the 13:35 batch
because 21:30 UTC is after the US close and because eight signals decided one
at a time would hand out the budget first-come-first-served. Intraday triggers
run immediately, because a move worth analyzing at 11:00 is worth nothing by
the next morning.

No LLM, no broker: agent.run_once is stubbed and only the gating is exercised.
"""
import asyncio
import datetime

import pytest

from backend.tasks import scheduler


@pytest.fixture(autouse=True)
def reset_cooldown():
    scheduler._last_agent_run = None
    yield
    scheduler._last_agent_run = None


@pytest.fixture
def agent_stub(monkeypatch):
    runs = []

    class Run:
        acted = False
        rejected = []
        failed = []
        notes = []
        skipped = None

    def run_once():
        runs.append(datetime.datetime.now(datetime.timezone.utc))
        return Run()

    monkeypatch.setattr(scheduler.agent, "run_once", run_once)
    monkeypatch.setattr(scheduler.agent, "is_enabled", lambda: True)
    return runs


def _open(monkeypatch, is_open=True):
    monkeypatch.setattr(scheduler.watchdog, "is_us_market_hours", lambda: is_open)


def _weekday(monkeypatch, when=datetime.datetime(2026, 8, 20, 13, 35, tzinfo=datetime.timezone.utc)):
    """Pin the clock to a Thursday.

    The batch job returns early at the weekend, so a test that exercises it
    while reading the real clock passes five days in seven and fails on the
    other two. Found on a Saturday, having passed all week.
    """

    class FrozenDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return when

    monkeypatch.setattr(scheduler.datetime, "datetime", FrozenDatetime)


def test_a_trigger_during_market_hours_runs_the_agent(agent_stub, monkeypatch):
    _open(monkeypatch)
    asyncio.run(scheduler._maybe_run_agent())
    assert len(agent_stub) == 1


def test_a_trigger_outside_market_hours_does_not(agent_stub, monkeypatch):
    """It would only queue an order that cannot fill. The 13:35 batch picks it
    up and re-decides on fresh prices."""
    _open(monkeypatch, is_open=False)
    asyncio.run(scheduler._maybe_run_agent())
    assert agent_stub == []


def test_a_disabled_agent_is_not_run_by_a_trigger(agent_stub, monkeypatch):
    _open(monkeypatch)
    monkeypatch.setattr(scheduler.agent, "is_enabled", lambda: False)
    asyncio.run(scheduler._maybe_run_agent())
    assert agent_stub == []


def test_a_burst_of_triggers_produces_one_run(agent_stub, monkeypatch):
    """A busy morning must not have the model re-plan the book every fifteen
    minutes against a book that has barely moved."""
    _open(monkeypatch)
    for _ in range(4):
        asyncio.run(scheduler._maybe_run_agent())
    assert len(agent_stub) == 1


def test_the_cooldown_expires(agent_stub, monkeypatch):
    _open(monkeypatch)
    asyncio.run(scheduler._maybe_run_agent())
    scheduler._last_agent_run -= scheduler._AGENT_COOLDOWN + datetime.timedelta(seconds=1)
    asyncio.run(scheduler._maybe_run_agent())
    assert len(agent_stub) == 2


def test_a_failing_run_does_not_escape_the_trigger_path(agent_stub, monkeypatch):
    """A trigger is fired from the watchdog loop; an exception here would kill
    the tick that was also delivering price alerts."""
    _open(monkeypatch)

    def boom():
        raise RuntimeError("model down")

    monkeypatch.setattr(scheduler.agent, "run_once", boom)
    asyncio.run(scheduler._maybe_run_agent())  # must not raise


def test_the_batch_job_arms_the_same_cooldown(agent_stub, monkeypatch):
    """Otherwise a trigger minutes after the 13:35 batch re-plans a book that
    has just moved."""
    _open(monkeypatch)
    _weekday(monkeypatch)
    monkeypatch.setattr(scheduler, "notify", lambda *a, **kw: asyncio.sleep(0))
    asyncio.run(scheduler._agent_run_job())

    before = len(agent_stub)
    asyncio.run(scheduler._maybe_run_agent())
    assert len(agent_stub) == before, "the batch should have armed the cooldown"


# --- noticing a stop that fired ------------------------------------------------


def test_the_watchdog_settles_agent_fills(agent_stub, monkeypatch):
    """A resting stop can trigger at any moment and nobody is waiting for that
    fill. Settled only when the agent next decides, the book would show a
    position that had already been sold — for the rest of the day."""
    called = []
    monkeypatch.setattr(scheduler.agent, "settle_pending", lambda: called.append(1) or [])
    monkeypatch.setattr(scheduler, "notify", lambda *a, **kw: asyncio.sleep(0))

    asyncio.run(scheduler._settle_agent_fills())

    assert called == [1]


def test_a_triggered_stop_is_announced(monkeypatch):
    posted = []
    monkeypatch.setattr(scheduler.agent, "is_enabled", lambda: True)
    monkeypatch.setattr(
        scheduler.agent, "settle_pending",
        lambda: [{"ticker": "ZBH", "side": "sell", "quantity": 10.0, "price": 92.0,
                  "was_stop": True, "status": "filled"}],
    )

    async def fake_notify(*args, **kwargs):
        posted.append(args[0] if args else kwargs)

    monkeypatch.setattr(scheduler, "notify", fake_notify)
    asyncio.run(scheduler._settle_agent_fills())

    assert len(posted) == 1
    assert "Stop triggered" in posted[0]
    assert "ZBH" in posted[0] and "92.00" in posted[0]


def test_an_ordinary_fill_is_not_announced_again(monkeypatch):
    """The run that placed it already reported it."""
    posted = []
    monkeypatch.setattr(scheduler.agent, "is_enabled", lambda: True)
    monkeypatch.setattr(
        scheduler.agent, "settle_pending",
        lambda: [{"ticker": "ZBH", "side": "buy", "quantity": 10.0, "price": 97.8,
                  "was_stop": False, "status": "filled"}],
    )

    async def fake_notify(*args, **kwargs):
        posted.append(args)

    monkeypatch.setattr(scheduler, "notify", fake_notify)
    asyncio.run(scheduler._settle_agent_fills())

    assert posted == []


def test_a_disabled_agent_is_not_polled(monkeypatch):
    called = []
    monkeypatch.setattr(scheduler.agent, "is_enabled", lambda: False)
    monkeypatch.setattr(scheduler.agent, "settle_pending", lambda: called.append(1) or [])

    asyncio.run(scheduler._settle_agent_fills())

    assert called == []


def test_a_settle_failure_does_not_kill_the_watchdog_tick(monkeypatch):
    """This runs before the price alerts; an exception here would take them
    down with it."""
    monkeypatch.setattr(scheduler.agent, "is_enabled", lambda: True)

    def boom():
        raise RuntimeError("broker down")

    monkeypatch.setattr(scheduler.agent, "settle_pending", boom)
    asyncio.run(scheduler._settle_agent_fills())  # must not raise


def test_a_filled_take_profit_is_announced_as_a_target_hit(monkeypatch):
    """A stop and a target both close the position, but one is good news and
    the other is not — reporting both as "stop triggered" would be a lie."""
    posted = []
    monkeypatch.setattr(scheduler.agent, "is_enabled", lambda: True)
    monkeypatch.setattr(
        scheduler.agent, "settle_pending",
        lambda: [{"ticker": "ZBH", "side": "sell", "quantity": 10.0, "price": 101.5,
                  "was_stop": True, "reason": "take-profit resting at $101.50",
                  "status": "filled"}],
    )

    async def fake_notify(*args, **kwargs):
        posted.append(args[0] if args else kwargs)

    monkeypatch.setattr(scheduler, "notify", fake_notify)
    asyncio.run(scheduler._settle_agent_fills())

    assert "Target reached" in posted[0]
    assert "at a profit" in posted[0]
