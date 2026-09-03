"""The agent sets its own cadence, and sees what that cadence earned.

Built on 2026-09-03 so it manages a book through the day rather than deciding
once at the open and going quiet. See "What the experiment is for" in
CLAUDE.md: the timing is a tool, not a lever on the experiment.
"""
import datetime
import json
from zoneinfo import ZoneInfo

import pytest

from backend.services import agent, agent_book

ET = ZoneInfo("America/New_York")


def at(hour, minute=0):
    return datetime.datetime(2026, 9, 3, hour, minute, tzinfo=ET)


def _book(cash=1000.0):
    return agent_book.Book(budget=10_000.0, cash=cash, realized_pnl=0.0, holdings=[])


def _reply(value):
    return json.dumps({"reasoning": "x", "next_wakeup": value, "orders": []})


# --- reading the request -------------------------------------------------------


@pytest.mark.parametrize(
    "written,expected",
    [
        ("45 minutes", (10, 45)),
        ("45", (10, 45)),
        ("45m", (10, 45)),
        (45, (10, 45)),
        ("2h", (12, 0)),
        ("14:30", (14, 30)),
        ("2:30 PM", (14, 30)),
        ("11:00 am", (11, 0)),
    ],
)
def test_the_ways_the_model_writes_a_time(written, expected):
    """The prompt asks for minutes or a clock time and the model writes prose.
    One exact token would silently drop a real request."""
    got = agent.parse_wakeup(_reply(written), at(10, 0))
    assert (got.hour, got.minute) == expected


@pytest.mark.parametrize("written", ["later", "soon", "when something happens", "", "25:00"])
def test_an_unreadable_time_is_no_request(written):
    """None means the agent asked for nothing, which the scheduler treats as a
    fallback rather than a choice."""
    assert agent.parse_wakeup(_reply(written), at(10, 0)) is None


def test_a_missing_field_is_no_request():
    assert agent.parse_wakeup('{"reasoning": "x", "orders": []}', at(10, 0)) is None


def test_a_fenced_reply_is_read():
    """This model wraps JSON in code fences often enough that a strict parser
    would throw away usable answers."""
    fenced = "```json\n" + _reply("30 minutes") + "\n```"
    got = agent.parse_wakeup(fenced, at(10, 0))
    assert (got.hour, got.minute) == (10, 30)


# --- what the agent is told about its own cadence ------------------------------


def _wakeups(*acted):
    return [{"at": f"{9 + i}:00 AM", "acted": a} for i, a in enumerate(acted)]


def test_nothing_is_said_before_there_is_a_history():
    assert agent.describe_recent_wakeups([]) == []


def test_an_all_idle_run_is_named_plainly():
    """The failure this exists to catch: asking for the minimum every time and
    spending the session on passes that do nothing."""
    said = "\n".join(agent.describe_recent_wakeups(_wakeups(False, False, False, False)))
    assert "All 4 did nothing" in said
    assert "ask for a later time" in said


def test_a_mixed_run_is_counted_not_scolded():
    said = "\n".join(agent.describe_recent_wakeups(_wakeups(True, False, True, False)))
    assert "2 of the last 4" in said
    assert "All " not in said


def test_a_productive_run_gets_no_advice():
    said = "\n".join(agent.describe_recent_wakeups(_wakeups(True, True, True)))
    assert "did nothing" not in said


def test_the_feedback_reaches_the_prompt():
    prompt = agent.build_prompt(_book(), [], {}, wakeups=_wakeups(False, False, False))
    assert "Your recent wakeups" in prompt
    assert "All 3 did nothing" in prompt


# --- the clock and the cash in the prompt --------------------------------------


def test_the_prompt_starts_with_the_time():
    """It is read against everything below it, and the agent cannot choose a
    wakeup without it."""
    prompt = agent.build_prompt(_book(), [], {})
    assert "Eastern" in prompt.splitlines()[2]


def test_unsettled_cash_is_explained_when_there_is_some():
    prompt = agent.build_prompt(_book(), [], {}, unsettled_cash=250.0)
    assert "$250.00 came from sales that have not settled" in prompt
    assert "cannot carry its stop and" in prompt


def test_nothing_is_said_when_everything_is_settled():
    """The ordinary case. A paragraph about settlement on a day none applies is
    prompt the agent has to read past."""
    assert "not settled" not in agent.build_prompt(_book(), [], {}, unsettled_cash=0.0)


def test_the_rule_offers_the_choice():
    prompt = agent.build_prompt(_book(), [], {})
    assert "next_wakeup" in prompt
    assert "minimum is 5 minutes" in prompt
    assert "five minutes before the close" in prompt


# --- the wakeup surviving a restart --------------------------------------------


class _Run:
    def __init__(self, next_wakeup=None, ran_at=None, placed=0, adjusted=0, orders=None):
        self.next_wakeup = next_wakeup
        self.ran_at = ran_at or datetime.datetime(2026, 9, 3, 14, 0)
        self.placed, self.adjusted, self.orders = placed, adjusted, orders


def test_a_due_wakeup_is_reported(monkeypatch):
    """Read from the stored run, not memory: the pass that asked and the pass
    that answers are different processes an hour apart."""
    wanted = datetime.datetime(2026, 9, 3, 15, 0, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(agent.db, "get_agent_runs", lambda limit: [_Run(next_wakeup=wanted)])

    assert agent.wakeup_due(at(11, 30)) is not None  # 15:00 UTC == 11:00 ET


def test_a_future_wakeup_is_not_due_yet(monkeypatch):
    wanted = datetime.datetime(2026, 9, 3, 18, 0, tzinfo=datetime.timezone.utc)
    monkeypatch.setattr(agent.db, "get_agent_runs", lambda limit: [_Run(next_wakeup=wanted)])

    assert agent.wakeup_due(at(11, 0)) is None


def test_a_naive_stored_time_is_read_as_utc(monkeypatch):
    """SQLite drops the timezone, so the value comes back naive. Reading it as
    local would move the wakeup by the host's offset."""
    monkeypatch.setattr(
        agent.db, "get_agent_runs",
        lambda limit: [_Run(next_wakeup=datetime.datetime(2026, 9, 3, 15, 0))],
    )

    assert agent.wakeup_due(at(11, 30)) is not None


def test_no_request_is_not_a_wakeup(monkeypatch):
    monkeypatch.setattr(agent.db, "get_agent_runs", lambda limit: [_Run(next_wakeup=None)])

    assert agent.wakeup_due(at(15, 0)) is None


def test_no_runs_at_all_is_not_a_wakeup(monkeypatch):
    monkeypatch.setattr(agent.db, "get_agent_runs", lambda limit: [])

    assert agent.wakeup_due(at(15, 0)) is None


# --- what counts as having acted -----------------------------------------------


def test_a_pass_that_only_researched_counts_as_acting(monkeypatch):
    """Choosing what to study is the only way anything new enters the account,
    so a research-only pass reading as idle would be exactly backwards."""
    monkeypatch.setattr(
        agent.db, "get_agent_runs",
        lambda limit: [_Run(orders=json.dumps([{"side": "research", "ticker": "INTC"}]))],
    )

    assert agent._recent_wakeups()[0]["acted"] is True


def test_a_pass_that_only_left_a_note_is_still_idle(monkeypatch):
    """A note is the agent talking, not the agent trading. Counting it would
    tell the agent its cadence is earning more than it is."""
    monkeypatch.setattr(
        agent.db, "get_agent_runs",
        lambda limit: [_Run(orders=json.dumps([{"side": "note", "reason": "I need X"}]))],
    )

    assert agent._recent_wakeups()[0]["acted"] is False


def test_unreadable_orders_do_not_crash_the_history(monkeypatch):
    monkeypatch.setattr(agent.db, "get_agent_runs", lambda limit: [_Run(orders="not json")])

    assert agent._recent_wakeups()[0]["acted"] is False
