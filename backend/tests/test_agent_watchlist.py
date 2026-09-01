"""The agent choosing what to stop watching, and the cap that forces the choice.

Research adds to the watchlist permanently, so without an untrack the list is a
ratchet: it only ever grows, and the morning sweep grows with it until it runs
past the open. The cap makes the limit visible and the untrack action makes it
the agent's decision rather than a wall it hits.

Python's job here is the same as everywhere else: refuse what must not happen,
never reshape what was asked. The one thing it refuses outright is untracking a
held position, because a holding nobody analyses is a holding with nothing
watching for its exit.

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
def watching(monkeypatch):
    """A watchlist of three, a cap of four, and research priced at 5 cents."""
    def _setup(tickers=("AAA", "BBB", "CCC"), cap=4):
        monkeypatch.setattr(agent.research, "get_price", lambda: 0.05)
        monkeypatch.setattr(agent.research, "is_charging", lambda: True)
        monkeypatch.setattr(agent.db, "get_watchlist", lambda: list(tickers))
        monkeypatch.setattr(agent, "_max_watchlist", lambda: cap)
        return list(tickers)
    return _setup


# --- what the agent is shown ---------------------------------------------------


def test_the_prompt_lists_the_watchlist_and_its_cap(watching):
    watchlist = watching()

    prompt = agent.build_prompt(_book(), [], {}, watchlist=watchlist, max_watchlist=4)

    assert "analysed every morning" in prompt
    assert "at most 4" in prompt
    assert "AAA" in prompt and "BBB" in prompt and "CCC" in prompt


def test_held_and_watched_only_are_listed_apart(watching):
    """Only a watched-only ticker can be dropped. A single undifferentiated
    list invites orders Python then refuses, which wastes the retry."""
    watchlist = watching()

    prompt = agent.build_prompt(
        _book(holdings=[("AAA", 3, 10.0)]), [], {},
        watchlist=watchlist, max_watchlist=4,
    )

    assert "cannot be dropped: AAA" in prompt
    assert "droppable: BBB, CCC" in prompt


def test_a_full_watchlist_says_so_rather_than_waiting_to_refuse(watching):
    watchlist = watching(tickers=("AAA", "BBB", "CCC", "DDD"), cap=4)

    prompt = agent.build_prompt(_book(), [], {}, watchlist=watchlist, max_watchlist=4)

    assert "That is the limit" in prompt


def test_the_rules_explain_untracking_as_a_swap(watching):
    """The identical wording had to be added for sells funding buys before the
    model worked out it could reorder. Do not assume it generalizes."""
    watching()

    prompt = agent.build_prompt(_book(), [], {}, watchlist=["AAA"], max_watchlist=4)

    assert 'side "untrack"' in prompt
    assert "list the untrack" in prompt and "research after it" in prompt
    assert "cannot untrack something you hold" in prompt


def test_no_watchlist_section_when_there_is_no_cap():
    """The live deployment does not run this feature. A rule about a limit that
    is not enforced is prompt tokens spent on a lie."""
    prompt = agent.build_prompt(_book(), [], {}, watchlist=["AAA"], max_watchlist=0)

    assert "untrack" not in prompt


def test_a_menu_renders_for_a_book_that_holds_something(watching):
    """Regression. The holdings loop used a local named `price`, which rebound
    the research-price parameter to a string, and the menu block below then
    formatted that string as a float. It needed a holding and a menu in the
    same prompt, so it survived every existing test and would have raised on
    the analyst's first pass after its first buy.
    """
    watching()
    book = _book(holdings=[("GOOG", 2, 343.66)])
    book.holdings[0].price = 344.0

    prompt = agent.build_prompt(
        book, [], {}, menu=[Candidate("NVDA")], price=0.05, max_research=15,
        watchlist=["GOOG", "NVDA"], max_watchlist=4,
    )

    assert "$0.05 to have a stock analysed" in prompt
    assert "now $344.00 each" in prompt


def test_signals_do_not_rebind_the_research_price_either(watching):
    """The same shadowing existed in the signals loop, where it would have set
    the research price to a float and quietly printed the wrong number."""
    watching()

    class Signal:
        ticker, signal_date, decision = "NVDA", "2026-08-27", "Buy"
        entry_price = stop_loss = price_target = None
        win_probability = risk_reward = expected_value_r = None

    prompt = agent.build_prompt(
        _book(), [Signal()], {"NVDA": 180.0}, menu=[Candidate("AMD")],
        price=0.05, max_research=15, watchlist=["NVDA"], max_watchlist=4,
    )

    assert "$0.05 to have a stock analysed" in prompt
    assert "now $180.00" in prompt


# --- what Python enforces ------------------------------------------------------


def test_untracking_a_watched_ticker_is_accepted(watching):
    watching()

    accepted, rejected = agent.screen(
        [{"ticker": "BBB", "side": "untrack"}], _book(), {}, None, None,
    )

    assert rejected == []
    assert accepted[0]["ticker"] == "BBB" and accepted[0]["side"] == "untrack"
    assert accepted[0]["quantity"] == 0


def test_a_held_ticker_cannot_be_untracked(watching):
    """The rule that must never be relaxed. Stopping the analysis of a position
    leaves nothing looking for its exit, and the daily analysis of a holding is
    what the charge already pays for."""
    watching()

    accepted, rejected = agent.screen(
        [{"ticker": "AAA", "side": "untrack"}],
        _book(holdings=[("AAA", 3, 10.0)]), {}, None, None,
    )

    assert accepted == []
    assert rejected[0].side == "untrack"
    assert "sell it first" in rejected[0].why


def test_untracking_something_unwatched_is_refused(watching):
    watching()

    _, rejected = agent.screen(
        [{"ticker": "ZZZ", "side": "untrack"}], _book(), {}, None, None,
    )

    assert "nothing to stop watching" in rejected[0].why


def test_research_is_refused_when_the_watchlist_is_full(watching):
    watching(tickers=("AAA", "BBB", "CCC", "DDD"), cap=4)

    _, rejected = agent.screen(
        [{"ticker": "NEW", "side": "research"}], _book(), {}, None, {"NEW"},
    )

    assert "watchlist is full at 4" in rejected[0].why
    assert "untrack something first" in rejected[0].why


def test_an_untrack_frees_a_slot_for_a_research_listed_after_it(watching):
    """The point of the whole design. A full watchlist is a swap, not a wall,
    so the agent trades one name's coverage for another in the same pass."""
    watching(tickers=("AAA", "BBB", "CCC", "DDD"), cap=4)

    accepted, rejected = agent.screen(
        [{"ticker": "DDD", "side": "untrack"},
         {"ticker": "NEW", "side": "research"}],
        _book(), {}, None, {"NEW"},
    )

    assert rejected == []
    assert [o["side"] for o in accepted] == ["untrack", "research"]


def test_the_order_matters_the_same_way_a_sell_funding_a_buy_does(watching):
    """Research listed first sees the full watchlist and is refused. This is
    the behaviour the prompt warns about, and it must actually happen."""
    watching(tickers=("AAA", "BBB", "CCC", "DDD"), cap=4)

    accepted, rejected = agent.screen(
        [{"ticker": "NEW", "side": "research"},
         {"ticker": "DDD", "side": "untrack"}],
        _book(), {}, None, {"NEW"},
    )

    assert [o["side"] for o in accepted] == ["untrack"]
    assert rejected[0].ticker == "NEW" and "full at 4" in rejected[0].why


def test_two_researches_cannot_share_one_freed_slot(watching):
    """The running-watchlist equivalent of three buys that each fit the opening
    cash but not each other."""
    watching(tickers=("AAA", "BBB", "CCC", "DDD"), cap=4)

    accepted, rejected = agent.screen(
        [{"ticker": "DDD", "side": "untrack"},
         {"ticker": "ONE", "side": "research"},
         {"ticker": "TWO", "side": "research"}],
        _book(), {}, None, {"ONE", "TWO"},
    )

    assert [o["ticker"] for o in accepted] == ["DDD", "ONE"]
    assert rejected[0].ticker == "TWO" and "full at 4" in rejected[0].why


def test_researching_something_already_watched_is_still_refused(watching):
    """Unchanged by the cap, and worth pinning: paying twice for the same
    analysis is the failure the check was written for."""
    watching()

    _, rejected = agent.screen(
        [{"ticker": "AAA", "side": "research"}], _book(), {}, None, {"AAA"},
    )

    assert "already being researched" in rejected[0].why


# --- what happens after it is accepted -----------------------------------------


def test_an_accepted_untrack_removes_it_and_is_recorded(watching, monkeypatch):
    watching()
    removed = []
    monkeypatch.setattr(agent.db, "remove_from_watchlist", removed.append)
    run = agent.AgentRun()

    agent._untrack({"ticker": "BBB", "side": "untrack"}, run)

    assert removed == ["BBB"]
    assert run.untracked == ["BBB"] and run.failed == []


def test_a_failed_removal_is_reported_rather_than_raising(watching, monkeypatch):
    """A pass that traded successfully must not die because a note could not
    be filed."""
    watching()

    def boom(_ticker):
        raise RuntimeError("database is gone")

    monkeypatch.setattr(agent.db, "remove_from_watchlist", boom)
    run = agent.AgentRun()

    agent._untrack({"ticker": "BBB", "side": "untrack"}, run)

    assert run.untracked == [] and len(run.failed) == 1


def test_a_run_that_only_untracked_is_not_an_idle_run():
    """It changes what tomorrow's sweep costs, so reporting it as "no action"
    would hide a real decision."""
    run = agent.AgentRun(untracked=["BBB"])

    assert run.acted is True


def test_the_retry_says_how_to_fix_a_full_watchlist(watching):
    """The retry is the one chance to correct a refusal, and advice about cash
    does not help here. Observed on the first live probe: the model asked to
    research two names without untracking anything."""
    watching()
    refusal = agent_book.Rejection(
        ticker="NVDA", side="research", quantity=0,
        why="the watchlist is full at 4 — untrack something first",
    )

    prompt = agent.build_prompt(
        _book(), [], {}, rejected=[refusal], watchlist=["AAA"], max_watchlist=4,
    )

    assert "untrack something first and list the untrack before the research" in prompt


def test_a_cash_refusal_does_not_mention_the_watchlist(watching):
    """Every extra line is prompt tokens on a model that already reads 100k."""
    watching()
    refusal = agent_book.Rejection(
        ticker="NVDA", side="buy", quantity=2, why="costs more than the cash left",
    )

    prompt = agent.build_prompt(
        _book(), [], {}, rejected=[refusal], watchlist=["AAA"], max_watchlist=4,
    )

    assert "list the untrack before the research" not in prompt


def test_the_watchlist_section_states_the_daily_cost(watching):
    """The agent had every part and never used them: the menu section gives the
    price, this section gave the count, and the rules say untracking saves
    future analyses. Across five passes it never mentioned the watchlist while
    writing that it had little cash. Multiplying is the app's job — the same
    reason the signal section computes affordable shares in Python."""
    watching()

    prompt = agent.build_prompt(
        _book(), [], {}, watchlist=["AAA", "BBB", "CCC"], max_watchlist=12, price=0.05,
    )

    assert "paying $0.15 every morning" in prompt


def test_it_says_what_dropping_the_droppable_ones_would_save(watching):
    watching()

    prompt = agent.build_prompt(
        _book(holdings=[("AAA", 3, 10.0)]), [], {},
        watchlist=["AAA", "BBB", "CCC"], max_watchlist=12, price=0.05,
    )

    assert "droppable: BBB, CCC" in prompt
    assert "save $0.10 a day" in prompt


def test_a_free_deployment_states_no_figure(watching):
    """The live bot does not charge for research. "$0.00 every morning" would
    be true and would invite the agent to reason about a cost that is not one."""
    watching()

    prompt = agent.build_prompt(
        _book(), [], {}, watchlist=["AAA", "BBB"], max_watchlist=12, price=0.0,
    )

    cost_line = next(l for l in prompt.splitlines() if l.startswith("You are paying"))

    # Scoped to the line under test: "$0.00" appears elsewhere in every prompt,
    # for realized profit and an empty cash balance.
    assert cost_line == "You are paying to have 2 tickers analysed every morning, and you may track at most 12."
    assert "would save" not in prompt


# --- an empty balance ----------------------------------------------------------


def test_an_empty_balance_says_so_instead_of_quoting_itself_as_a_limit(watching):
    """The rules block opened with "must cost $-8.00 or less in total", which is
    not an instruction anybody can follow. The agent reached that balance on
    2026-08-28 and stayed there."""
    watching()

    prompt = agent.build_prompt(
        _book(cash=-8.0), [], {}, watchlist=["AAA"], max_watchlist=12, price=0.05,
    )

    assert "You have no money to spend. The balance is $-8.00." in prompt
    assert "must cost $-8.00 or less" not in prompt


def test_it_names_the_only_thing_that_raises_cash(watching):
    watching()

    prompt = agent.build_prompt(
        _book(cash=0.0), [], {}, watchlist=["AAA"], max_watchlist=12, price=0.05,
    )

    assert "Selling is the only thing that raises cash" in prompt


def test_it_says_the_charge_continues_and_untracking_stops_part_of_it(watching):
    """The reason this is not a stable state: propagate_ticker bills every
    ticker the sweep touches, so a book at zero keeps drifting down."""
    watching()

    prompt = agent.build_prompt(
        _book(cash=-8.0), [], {}, watchlist=["AAA"], max_watchlist=12, price=0.05,
    )

    assert "charged tomorrow whether" in prompt
    assert "Untracking raises no cash and stops part of the charge" in prompt


def test_a_book_with_money_keeps_the_spending_limit(watching):
    """The normal case must not change. The limit is the one rule three live
    failures were fixed by wording carefully."""
    watching()

    prompt = agent.build_prompt(
        _book(cash=812.40), [], {}, watchlist=["AAA"], max_watchlist=12, price=0.05,
    )

    assert "must cost $812.40 or less in total" in prompt
    assert "no money to spend" not in prompt


def test_the_threshold_is_what_python_actually_refuses_at(watching):
    """Cash above the research price is not "no money": the agent can still
    commission an analysis, and screen() will accept it."""
    watching()

    prompt = agent.build_prompt(
        _book(cash=0.06), [], {}, watchlist=["AAA"], max_watchlist=12, price=0.05,
    )

    assert "must cost $0.06 or less" in prompt
    assert "no money to spend" not in prompt
