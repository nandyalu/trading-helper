"""The agent chooses when it sees research, and is told why each analysis ran.

Both exist for the same reason, recorded in CLAUDE.md under "What the
experiment is for": give the agent proper tools inside reasonable
restrictions. A stock can move enough in a day to be worth taking the profit
or cutting the loss, and an agent that cannot ask to look until tomorrow
cannot act on that.
"""
import pytest

from backend.services import agent, agent_book


def _book(cash=1000.0):
    return agent_book.Book(budget=10_000.0, cash=cash, realized_pnl=0.0, holdings=[])


@pytest.fixture
def researchable(monkeypatch):
    monkeypatch.setattr(agent.research, "get_price", lambda: 0.05)
    monkeypatch.setattr(agent.research, "is_charging", lambda: True)
    monkeypatch.setattr(agent.db, "get_watchlist", lambda: [])
    monkeypatch.setattr(agent, "_max_watchlist", lambda: 30)


# --- when the answer arrives ---------------------------------------------------


@pytest.mark.parametrize("asked", ["now", "NOW", "immediately", "today", "asap"])
def test_asking_for_it_now_is_accepted(researchable, asked):
    """Several spellings, because the model writes prose and one exact token
    would silently downgrade a real request to the overnight default."""
    accepted, rejected = agent.screen(
        [{"ticker": "NEW", "side": "research", "when": asked}],
        _book(), {}, None, {"NEW"},
    )

    assert rejected == []
    assert accepted[0]["when"] == "now"


@pytest.mark.parametrize("asked", [None, "", "tomorrow", "next week", "whenever"])
def test_anything_else_waits_for_the_sweep(researchable, asked):
    """Overnight is the default, so an unreadable answer is the cheap one and
    never an unrequested burst of GPU work."""
    order = {"ticker": "NEW", "side": "research"}
    if asked is not None:
        order["when"] = asked

    accepted, _ = agent.screen([order], _book(), {}, None, {"NEW"})

    assert accepted[0]["when"] == "tomorrow"


def test_the_timing_does_not_change_the_price(researchable):
    """Both cost $0.05. The work is identical, so a price difference would be
    an invented cost dressed up as a rule."""
    now, _ = agent.screen(
        [{"ticker": "AAA", "side": "research", "when": "now"}], _book(cash=1.0), {}, None, {"AAA"},
    )
    later, _ = agent.screen(
        [{"ticker": "BBB", "side": "research"}], _book(cash=1.0), {}, None, {"BBB"},
    )

    assert now and later  # both affordable at the same cash


class _Candidate:
    """The shape build_prompt reads, matching the stub in test_agent_research."""

    def __init__(self, ticker, price=88.99, volume=17_400_000, change_pct=-1.2):
        self.ticker, self.price, self.volume, self.change_pct = ticker, price, volume, change_pct
        self.name = f"{ticker} Inc"

    @property
    def volume_m(self):
        return self.volume / 1_000_000


def test_the_prompt_offers_the_choice(researchable):
    prompt = agent.build_prompt(
        _book(), [], {}, menu=[_Candidate("INTC")], price=0.05, max_research=15,
    )

    assert '"when": "now"' in prompt
    assert "runs straight after this pass" in prompt
    # The shape is what the model copies, so the field has to appear there too.
    assert '"side": "research", "when": "now"' in prompt


# --- why an analysis ran -------------------------------------------------------


class _Sig:
    ticker, signal_date, decision = "AAA", "2026-09-03", "Buy"
    entry_price = stop_loss = price_target = None
    win_probability = risk_reward = expected_value_r = None
    trigger = None


def _line(trigger):
    sig = _Sig()
    sig.trigger = trigger
    prompt = agent.build_prompt(_book(), [sig], {"AAA": 10.0})
    return next(l for l in prompt.splitlines() if l.startswith("- AAA"))


def test_a_move_triggered_signal_says_so():
    """The one that matters most: the analyst was reacting to a move the price
    already holds, which is not the same as a scheduled opinion."""
    assert "moved unusually" in _line("move")
    assert "already holds" in _line("move")


@pytest.mark.parametrize(
    "trigger,phrase",
    [
        ("sweep", "normal morning schedule"),
        ("commissioned", "you asked to see it today"),
        ("earnings", "reports earnings soon"),
        ("manual", "Run by hand"),
    ],
)
def test_each_trigger_reads_as_plain_words(trigger, phrase):
    assert phrase in _line(trigger)


def test_an_unrecorded_trigger_says_nothing():
    """Rows written before the column existed have no honest value. Inventing
    one would put a guess in the record the agent reads as fact."""
    line = _line(None)
    assert "Run " not in line
    assert line.startswith("- AAA on 2026-09-03: Buy")
