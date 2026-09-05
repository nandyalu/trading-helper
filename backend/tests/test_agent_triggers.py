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


# --- research the agent asked to see today -------------------------------------


def test_research_asked_for_now_is_analysed_now(monkeypatch):
    """The whole point of letting the agent choose. A stock can move enough in
    a day to be worth acting on, so "now" has to actually mean now — not a
    field that is recorded and then waits for the morning like everything else.
    """
    dispatched = {}

    async def fake_run_analyses(tickers, on_failure=None, trigger=None):
        dispatched["tickers"] = list(tickers)
        dispatched["trigger"] = trigger
        return []

    monkeypatch.setattr(scheduler.analysis, "run_analyses", fake_run_analyses)
    monkeypatch.setattr(scheduler, "_maybe_run_agent", _noop)

    class Run:
        research_now = ["INTC", "PLTR"]

    asyncio.run(scheduler._dispatch_immediate_research(Run()))

    assert dispatched["tickers"] == ["INTC", "PLTR"]
    # Stored on every signal it produces, so the next prompt can say the
    # analysis exists because the agent asked for it today.
    assert dispatched["trigger"] == "commissioned"


def test_the_agent_is_asked_again_once_they_land(monkeypatch):
    """An answer nobody looks at until tomorrow is the delay the agent was
    trying to avoid, so the dispatch has to re-ask."""
    asked = []

    async def fake_run_analyses(tickers, on_failure=None, trigger=None):
        return []

    async def fake_maybe_run_agent():
        asked.append(True)

    monkeypatch.setattr(scheduler.analysis, "run_analyses", fake_run_analyses)
    monkeypatch.setattr(scheduler, "_maybe_run_agent", fake_maybe_run_agent)

    class Run:
        research_now = ["INTC"]

    asyncio.run(scheduler._dispatch_immediate_research(Run()))

    assert asked == [True]


def test_nothing_is_dispatched_when_nothing_was_asked_for(monkeypatch):
    """The overnight default must cost no GPU at all."""
    called = []

    async def fake_run_analyses(tickers, on_failure=None, trigger=None):
        called.append(tickers)
        return []

    monkeypatch.setattr(scheduler.analysis, "run_analyses", fake_run_analyses)

    class Run:
        research_now = []

    asyncio.run(scheduler._dispatch_immediate_research(Run()))

    assert called == []


async def _noop():
    return None


# --- the agent's own cadence ---------------------------------------------------


@pytest.fixture
def wakeup_stub(monkeypatch):
    """A pass that records it ran, with no LLM and no broker."""
    passes = []

    async def fake_pass(label):
        passes.append(label)

    monkeypatch.setattr(scheduler, "_run_agent_pass", fake_pass)
    monkeypatch.setattr(scheduler.agent, "is_enabled", lambda: True)
    monkeypatch.setattr(scheduler.watchdog, "is_us_market_hours", lambda: True)
    scheduler._last_final_pass = None
    return passes


def _et(hour, minute):
    from zoneinfo import ZoneInfo

    return datetime.datetime(2026, 9, 3, hour, minute, tzinfo=ZoneInfo("America/New_York"))


def test_the_agent_is_woken_when_it_asked_to_be(wakeup_stub, monkeypatch):
    monkeypatch.setattr(scheduler.market_clock, "now_et", lambda *a: _et(11, 0))
    monkeypatch.setattr(scheduler.agent, "wakeup_due", lambda now: _et(11, 0))

    asyncio.run(scheduler._agent_wakeup_job())

    assert wakeup_stub == ["Wakeup"]


def test_nothing_happens_before_the_time_it_chose(wakeup_stub, monkeypatch):
    monkeypatch.setattr(scheduler.market_clock, "now_et", lambda *a: _et(11, 0))
    monkeypatch.setattr(scheduler.agent, "wakeup_due", lambda now: None)

    asyncio.run(scheduler._agent_wakeup_job())

    assert wakeup_stub == []


def test_the_chosen_time_is_not_blocked_by_the_cooldown(wakeup_stub, monkeypatch):
    """The cooldown stops the *watchdog* re-planning a book that has barely
    moved. The agent naming a moment is the opposite case, and overriding it
    would make the tool a suggestion."""
    scheduler._last_agent_run = datetime.datetime.now(datetime.timezone.utc)
    monkeypatch.setattr(scheduler.market_clock, "now_et", lambda *a: _et(11, 0))
    monkeypatch.setattr(scheduler.agent, "wakeup_due", lambda now: _et(11, 0))

    asyncio.run(scheduler._agent_wakeup_job())

    assert wakeup_stub == ["Wakeup"]


def test_a_final_pass_runs_before_the_close(wakeup_stub, monkeypatch):
    """So no position goes into the night unreviewed."""
    monkeypatch.setattr(scheduler.market_clock, "now_et", lambda *a: _et(15, 56))
    monkeypatch.setattr(scheduler.agent, "wakeup_due", lambda now: None)
    monkeypatch.setattr(scheduler, "_ran_recently", lambda now, **k: False)

    asyncio.run(scheduler._agent_wakeup_job())

    assert wakeup_stub == ["Final"]


def test_the_final_pass_runs_once_a_session(wakeup_stub, monkeypatch):
    monkeypatch.setattr(scheduler.market_clock, "now_et", lambda *a: _et(15, 56))
    monkeypatch.setattr(scheduler.agent, "wakeup_due", lambda now: None)
    monkeypatch.setattr(scheduler, "_ran_recently", lambda now, **k: False)

    asyncio.run(scheduler._agent_wakeup_job())
    asyncio.run(scheduler._agent_wakeup_job())

    assert wakeup_stub == ["Final"]


def test_the_final_pass_is_skipped_after_a_recent_pass(wakeup_stub, monkeypatch):
    """The agent asked to be woken at 3:45 on 2026-09-04 and was woken again at
    3:56. Two passes eleven minutes apart said the same thing."""
    monkeypatch.setattr(scheduler.market_clock, "now_et", lambda *a: _et(15, 56))
    monkeypatch.setattr(scheduler.agent, "wakeup_due", lambda now: None)
    monkeypatch.setattr(scheduler, "_ran_recently", lambda now, **k: True)

    asyncio.run(scheduler._agent_wakeup_job())

    assert wakeup_stub == []


def test_the_agent_is_woken_outside_market_hours_when_it_asked(wakeup_stub, monkeypatch):
    """**The market-hours gate is gone.** Morning analyses take about eighteen
    minutes, so commissioning them has to happen before the day starts, and
    that timing is the agent's decision."""
    monkeypatch.setattr(scheduler.watchdog, "is_us_market_hours", lambda: False)
    monkeypatch.setattr(scheduler.market_clock, "now_et", lambda *a: _et(7, 0))
    monkeypatch.setattr(scheduler.agent, "wakeup_due", lambda now: _et(7, 0))

    asyncio.run(scheduler._agent_wakeup_job())

    assert wakeup_stub == ["Wakeup"]


def test_no_final_pass_while_the_market_is_shut(wakeup_stub, monkeypatch):
    """The end-of-day pass belongs to a session. Outside one there is no close
    to run before."""
    monkeypatch.setattr(scheduler.watchdog, "is_us_market_hours", lambda: False)
    monkeypatch.setattr(scheduler.market_clock, "now_et", lambda *a: _et(15, 56))
    monkeypatch.setattr(scheduler.agent, "wakeup_due", lambda now: None)

    asyncio.run(scheduler._agent_wakeup_job())

    assert wakeup_stub == []


def test_nothing_wakes_while_the_agent_is_off(wakeup_stub, monkeypatch):
    monkeypatch.setattr(scheduler.agent, "is_enabled", lambda: False)
    monkeypatch.setattr(scheduler.agent, "wakeup_due", lambda now: _et(11, 0))

    asyncio.run(scheduler._agent_wakeup_job())

    assert wakeup_stub == []
