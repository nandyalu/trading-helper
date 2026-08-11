"""The agent's decision screening.

The model chooses what to buy and how much. These tests cover the narrow thing
Python still owns: that a decision which cannot be executed as stated is
dropped rather than reshaped, and that a set of orders is checked against a
running balance instead of the opening one.

Pure — no LLM, no broker, no DB.
"""
import pytest

from backend.services import agent, agent_book


def _book(cash=1000.0, holdings=None, budget=1000.0):
    return agent_book.Book(
        budget=budget,
        cash=cash,
        realized_pnl=0.0,
        holdings=[
            agent_book.Holding(ticker=t, quantity=q, avg_cost=c)
            for t, q, c in (holdings or [])
        ],
    )


# --- parsing ------------------------------------------------------------------


def test_plain_json_is_read():
    reasoning, orders = agent.parse_decision(
        '{"reasoning": "cheap", "orders": [{"ticker": "AAPL", "side": "buy", "quantity": 2}]}'
    )
    assert reasoning == "cheap"
    assert orders == [{"ticker": "AAPL", "side": "buy", "quantity": 2}]


def test_json_inside_a_code_fence_is_read():
    """This model fences its JSON more often than not."""
    _, orders = agent.parse_decision(
        'Here is my plan:\n```json\n{"reasoning": "x", "orders": []}\n```\nHope that helps.'
    )
    assert orders == []


def test_json_surrounded_by_prose_is_read():
    _, orders = agent.parse_decision(
        'I think we should buy. {"reasoning": "y", "orders": '
        '[{"ticker": "F", "side": "buy", "quantity": 1}]} That is my answer.'
    )
    assert len(orders) == 1


@pytest.mark.parametrize("text", ["", "no json here at all", "{broken", "[1,2,3]"])
def test_unreadable_replies_produce_no_orders(text):
    """Skipping a day is the safe failure; guessing at intent is not."""
    _, orders = agent.parse_decision(text)
    assert orders == []


# --- screening ----------------------------------------------------------------


def test_orders_are_checked_against_a_running_balance():
    """Each of these fits $1,000 alone. Together they do not, and checking each
    against the opening cash would let all three through."""
    book = _book(cash=1000.0)
    prices = {"AAA": 400.0, "BBB": 400.0, "CCC": 400.0}
    orders = [
        {"ticker": "AAA", "side": "buy", "quantity": 1},
        {"ticker": "BBB", "side": "buy", "quantity": 1},
        {"ticker": "CCC", "side": "buy", "quantity": 1},
    ]

    accepted, rejected = agent.screen(orders, book, prices)

    assert [o["ticker"] for o in accepted] == ["AAA", "BBB"]
    assert len(rejected) == 1
    assert rejected[0].ticker == "CCC"


def test_an_unaffordable_order_is_dropped_not_resized():
    """Resizing would turn the model's decision into a different one."""
    book = _book(cash=100.0)
    accepted, rejected = agent.screen(
        [{"ticker": "AAA", "side": "buy", "quantity": 10}], book, {"AAA": 50.0}
    )

    assert accepted == []
    assert len(rejected) == 1


def test_selling_frees_cash_for_a_later_buy_in_the_same_pass():
    book = _book(cash=0.0, holdings=[("AAA", 5, 10.0)])
    orders = [
        {"ticker": "AAA", "side": "sell", "quantity": 5},
        {"ticker": "BBB", "side": "buy", "quantity": 2},
    ]

    accepted, rejected = agent.screen(orders, book, {"AAA": 100.0, "BBB": 200.0})

    assert [o["ticker"] for o in accepted] == ["AAA", "BBB"]
    assert rejected == []


def test_selling_more_than_held_across_two_orders_is_caught():
    book = _book(holdings=[("AAA", 3, 10.0)])
    orders = [
        {"ticker": "AAA", "side": "sell", "quantity": 2},
        {"ticker": "AAA", "side": "sell", "quantity": 2},
    ]

    accepted, rejected = agent.screen(orders, book, {"AAA": 10.0})

    assert len(accepted) == 1
    assert len(rejected) == 1
    assert "no shorting" in rejected[0].why


def test_an_empty_decision_places_nothing():
    accepted, rejected = agent.screen([], _book(), {})
    assert accepted == [] and rejected == []


def test_an_unpriced_sell_goes_through_but_funds_nothing():
    """Exiting a position must always be possible, even when the price feed is
    down. Its proceeds are unknown, so they are counted as zero rather than
    guessed — a guess here would fund a buy with money that may not exist."""
    book = _book(cash=0.0, holdings=[("AAA", 5, 10.0)])
    orders = [
        {"ticker": "AAA", "side": "sell", "quantity": 5},
        {"ticker": "BBB", "side": "buy", "quantity": 1},
    ]

    accepted, rejected = agent.screen(orders, book, {"AAA": None, "BBB": 10.0})

    assert [o["ticker"] for o in accepted] == ["AAA"]
    assert [r.ticker for r in rejected] == ["BBB"]


def test_a_ticker_with_no_price_cannot_be_bought():
    accepted, rejected = agent.screen(
        [{"ticker": "AAA", "side": "buy", "quantity": 1}], _book(), {"AAA": None}
    )
    assert accepted == []
    assert "no price" in rejected[0].why


# --- prompt -------------------------------------------------------------------


def test_the_prompt_states_cash_and_holdings():
    book = _book(cash=250.0, holdings=[("AAA", 2, 100.0)])
    book.holdings[0].price = 120.0

    prompt = agent.build_prompt(book, [], {})

    assert "$250.00" in prompt
    assert "AAA" in prompt
    assert "whole shares only" in prompt.lower()


def test_the_prompt_never_mentions_the_brokers_balance():
    """The simulated account holds $1,000,000. If that number reaches the
    model, the budget is meaningless."""
    prompt = agent.build_prompt(_book(), [], {})
    assert "1,000,000" not in prompt
