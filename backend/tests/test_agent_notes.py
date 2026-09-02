"""The agent can say what it needs, and saying it must never count as doing it.

A note is the agent addressing whoever maintains it — asking for a tool it
lacks, data it cannot see, a rule it finds contradictory. It buys nothing and
is refused for nothing.

The reason it is safe is the reason it is useful: it acts on nothing. The agent
talking is not a second decision-maker in the record; the agent trading would
be.
"""
from backend.services import agent, agent_book


def _book(cash=1000.0, holdings=()):
    return agent_book.Book(
        budget=1000.0, cash=cash, realized_pnl=0.0, holdings=list(holdings)
    )


def _screen(orders, cash=1000.0, prices=None):
    return agent.screen(orders, _book(cash), prices or {"AAPL": 100.0})


# --- what screening does with one -----------------------------------------------


def test_a_note_is_accepted():
    accepted, rejected = _screen([{"side": "note", "reason": "I cannot see sector data."}])
    assert rejected == []
    assert accepted == [
        {"side": "note", "ticker": "", "quantity": 0, "reason": "I cannot see sector data."}
    ]


def test_an_empty_note_is_dropped_rather_than_recorded():
    """A blank note is the model filling in the shape, not saying something.
    Recording it would put empty rows in the record it was added to improve."""
    accepted, rejected = _screen([{"side": "note", "reason": "   "}])
    assert accepted == []
    assert rejected == []


def test_a_note_never_spends_cash():
    """The whole guarantee. A note is checked before anything that touches
    cash, so an empty account can still leave one."""
    accepted, _ = _screen(
        [{"side": "note", "reason": "no money left"}], cash=0.0
    )
    assert len(accepted) == 1
    assert accepted[0]["quantity"] == 0


def test_a_note_does_not_consume_the_budget_for_a_buy_beside_it():
    accepted, rejected = _screen(
        [
            {"side": "note", "reason": "a thought"},
            {"side": "buy", "ticker": "AAPL", "quantity": 5},
        ],
        cash=1000.0,
    )
    sides = [a["side"] for a in accepted]
    assert sides == ["note", "buy"]
    assert rejected == []


def test_a_note_is_never_refused_even_when_everything_else_is():
    accepted, rejected = _screen(
        [
            {"side": "buy", "ticker": "AAPL", "quantity": 100},  # far too expensive
            {"side": "note", "reason": "I could not afford what I wanted."},
        ],
        cash=10.0,
    )
    assert [a["side"] for a in accepted] == ["note"]
    assert len(rejected) == 1
    assert rejected[0].side == "buy"


# --- what it means for the run ---------------------------------------------------


def test_a_note_alone_is_not_acting():
    """Load-bearing. If a note counted as action, "I need better data" would
    stand in for the decision the agent still owed that morning."""
    run = agent.AgentRun(notes=["I would like sector data."])
    assert run.acted is False


def test_a_pass_that_traded_and_noted_still_counts_as_acting():
    run = agent.AgentRun(placed=[{"side": "buy", "ticker": "AAPL", "quantity": 1}],
                         notes=["a thought"])
    assert run.acted is True


def test_notes_reach_the_decisions_page():
    run = agent.AgentRun(notes=["I cannot see analyst estimates."])
    import json

    orders = json.loads(agent._orders_json(run))
    assert {"side": "note", "ticker": "", "quantity": 0,
            "reason": "I cannot see analyst estimates."} in orders


# --- the prompt ------------------------------------------------------------------


def test_the_prompt_offers_the_note_and_says_it_replaces_nothing():
    """Both halves matter. Without the first the agent never leaves one;
    without the second a note becomes a way to avoid deciding."""
    import inspect

    src = inspect.getsource(agent.build_prompt)
    assert 'side "note"' in src
    assert "never a substitute for a decision" in src


# --- yesterday's broker failures, in today's prompt --------------------------------


def test_a_broker_failure_reaches_the_next_prompt():
    """The gap this closes: an order the broker refused yesterday was invisible
    this morning, so the agent formed it again and was refused again."""
    lines = agent.describe_recent_failures(
        [{"side": "buy", "ticker": "AAPL", "quantity": 3,
          "why": "CANT_USE_UNSETTLE_FUNDS_FOR_COMBO_ORDER"}]
    )
    text = "\n".join(lines)
    assert "BUY 3 AAPL" in text
    assert "CANT_USE_UNSETTLE_FUNDS_FOR_COMBO_ORDER" in text


def test_it_says_these_were_not_arithmetic():
    """A screening refusal and a broker failure mean different things, and the
    agent needs the difference: one says its sums were wrong, the other says
    the order was right and the world would not take it."""
    text = "\n".join(agent.describe_recent_failures([{"side": "buy", "ticker": "A", "why": "x"}]))
    assert "not refused for arithmetic" in text


def test_no_failures_adds_no_section():
    """A prompt that says "nothing failed" every morning is noise, and the
    signals that matter get pushed further down for it."""
    assert agent.describe_recent_failures([]) == []


def test_only_the_last_few_are_shown():
    many = [{"side": "buy", "ticker": f"T{i}", "quantity": 1, "why": "no"} for i in range(20)]
    text = "\n".join(agent.describe_recent_failures(many))
    assert "T19" in text
    assert "T0:" not in text


def test_failures_are_stored_so_they_survive_the_process():
    """It has to cross days, and the process that saw the failure has exited."""
    import json

    run = agent.AgentRun(failed=[({"side": "sell", "ticker": "NVDA", "quantity": 2}, "no shares")])
    stored = json.loads(agent._failures_json(run))
    assert stored == [
        {"side": "sell", "ticker": "NVDA", "quantity": 2, "why": "no shares"}
    ]


def test_nothing_failed_stores_nothing():
    assert agent._failures_json(agent.AgentRun()) is None
