"""The agent choosing what to have analysed.

This is the experiment. The live agent is measured on decisions given a fixed
watchlist; this one decides what is worth looking at, under a budget the
research comes out of. Python's job is the same as everywhere else: refuse
what cannot be done, never reshape it.

Pure — no LLM, no broker.
"""
import pytest

from backend.services import agent, agent_book


class Candidate:
    def __init__(self, ticker, price=100.0, volume=5_000_000, change_pct=1.0):
        self.ticker, self.price, self.volume, self.change_pct = ticker, price, volume, change_pct
        self.name = f"{ticker} Inc"

    @property
    def volume_m(self):
        return self.volume / 1_000_000


def _book(cash=1000.0, holdings=None):
    return agent_book.Book(
        budget=10_000.0, cash=cash, realized_pnl=0.0,
        holdings=[agent_book.Holding(ticker=t, quantity=q, avg_cost=c)
                  for t, q, c in (holdings or [])],
    )


@pytest.fixture
def charging(monkeypatch):
    monkeypatch.setattr(agent.research, "get_price", lambda: 0.05)
    monkeypatch.setattr(agent.research, "is_charging", lambda: True)
    monkeypatch.setattr(agent.db, "get_watchlist", lambda: [])


# --- the menu ------------------------------------------------------------------


def test_the_menu_reaches_the_prompt_with_its_price(charging):
    menu = [Candidate("AAA", price=12.5, change_pct=3.2)]

    prompt = agent.build_prompt(_book(), [], {}, menu=menu, price=0.05, max_research=15)

    assert "$0.05 to have a stock analysed" in prompt
    assert "AAA" in prompt and "$12.50" in prompt and "+3.2% today" in prompt
    assert "at most 15" in prompt


def test_the_prompt_says_the_menu_is_unresearched(charging):
    """Screened for being liquid, not for being good. A model told these are
    candidates would reasonably assume somebody vetted them."""
    prompt = agent.build_prompt(_book(), [], {}, menu=[Candidate("AAA")], price=0.05, max_research=15)

    assert "Nothing has been analysed on these yet" in prompt
    assert "not for being good" in prompt


def test_without_a_menu_the_research_action_is_not_offered(charging):
    """Describing an action the agent cannot take invites it to try."""
    prompt = agent.build_prompt(_book(), [], {}, menu=None)

    assert 'side "research"' not in prompt


# --- screening what it asks for ------------------------------------------------


def test_research_is_paid_for_out_of_the_same_cash(charging):
    accepted, rejected = agent.screen(
        [{"ticker": "AAA", "side": "research"}], _book(cash=1.0), {}, {}, {"AAA"}
    )

    assert [o["side"] for o in accepted] == ["research"]
    assert rejected == []


def test_a_ticker_not_on_the_menu_is_refused(charging):
    """Never free-form: a model naming its own tickers invents symbols and
    reaches illiquid things with no price data."""
    accepted, rejected = agent.screen(
        [{"ticker": "MADEUP", "side": "research"}], _book(), {}, {}, {"AAA"}
    )

    assert accepted == []
    assert "not on today's candidate list" in rejected[0].why


def test_the_daily_limit_is_enforced_whatever_the_cash(charging, monkeypatch):
    """Money does not model time. The sweep has to finish before the open, and
    an agent with cash to burn could queue more GPU-hours than there are."""
    monkeypatch.setattr(agent, "_max_research_per_day", lambda: 2)
    orders = [{"ticker": t, "side": "research"} for t in ("AAA", "BBB", "CCC")]

    accepted, rejected = agent.screen(orders, _book(cash=1000.0), {}, {}, {"AAA", "BBB", "CCC"})

    assert len(accepted) == 2
    assert "daily research limit" in rejected[0].why


def test_research_it_cannot_afford_is_refused(charging):
    accepted, rejected = agent.screen(
        [{"ticker": "AAA", "side": "research"}], _book(cash=0.01), {}, {}, {"AAA"}
    )

    assert accepted == []
    assert "only $0.01 is left" in rejected[0].why


def test_something_already_tracked_is_not_researched_twice(charging, monkeypatch):
    """It is analysed every day anyway, and charged for. Paying again to start
    doing what is already happening is the plainest waste available."""
    monkeypatch.setattr(agent.db, "get_watchlist", lambda: ["AAA"])

    accepted, rejected = agent.screen(
        [{"ticker": "AAA", "side": "research"}], _book(), {}, {}, {"AAA"}
    )

    assert accepted == []
    assert "already being researched" in rejected[0].why


def test_research_spends_before_a_later_buy_sees_the_cash(charging):
    """Otherwise the agent commits the same dollar twice."""
    orders = [
        {"ticker": "AAA", "side": "research"},
        {"ticker": "BBB", "side": "buy", "quantity": 1},
    ]

    accepted, rejected = agent.screen(orders, _book(cash=100.02), {"BBB": 100.0}, {}, {"AAA"})

    assert [o["side"] for o in accepted] == ["research"]
    assert "BBB" == rejected[0].ticker, "the buy no longer fits once research is paid for"


# --- commissioning it ----------------------------------------------------------


def test_commissioning_tracks_the_ticker(charging, monkeypatch):
    """Tracking is how the analysis gets run: the morning sweep reads the
    watchlist, so adding the ticker is the commission."""
    tracked = []
    monkeypatch.setattr(agent.db, "add_to_watchlist", lambda t: tracked.append(t))
    run = agent.AgentRun()

    agent._commission_research({"ticker": "AAA", "side": "research"}, run)

    assert tracked == ["AAA"]
    assert run.researched == ["AAA"]
    assert run.acted is True, "a pass that only researched is not an idle pass"


def test_a_failed_commission_is_reported_not_charged(charging, monkeypatch):
    monkeypatch.setattr(
        agent.db, "add_to_watchlist",
        lambda t: (_ for _ in ()).throw(RuntimeError("database is locked")),
    )
    run = agent.AgentRun()

    agent._commission_research({"ticker": "AAA", "side": "research"}, run)

    assert run.researched == [] and len(run.failed) == 1


def test_a_broken_screener_leaves_the_agent_deciding_without_a_menu(monkeypatch):
    """A screen that fails should cost the day's new ideas, not the day."""
    monkeypatch.setattr(
        agent.candidates, "fetch_candidates",
        lambda: (_ for _ in ()).throw(RuntimeError("Webull is down")),
    )

    assert agent._candidate_menu() == []


def test_a_commissioned_ticker_is_charged_once_not_twice(charging, monkeypatch):
    """The charge belongs to the analysis and lands when the analysis runs.
    Billing at the commission too charged a ticker once for asking and once
    for the work."""
    charges = []
    monkeypatch.setattr(agent.db, "add_to_watchlist", lambda t: None)
    monkeypatch.setattr(agent.research, "charge", lambda t, note=None: charges.append(t))
    run = agent.AgentRun()

    agent._commission_research({"ticker": "AAA", "side": "research"}, run)

    assert charges == [], "commissioning must not bill; propagate_ticker does"
    assert run.researched == ["AAA"]
