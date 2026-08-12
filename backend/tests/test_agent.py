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


# --- settling fills ------------------------------------------------------------

# The exact shape a live sandbox fill came back as on 2026-08-11. The status,
# price, and quantity are inside a one-element `orders` list; the top level
# carries none of them. Reading the top level finds a plausible-looking dict
# that parses to nothing, so every order stays pending forever.
LIVE_ORDER_DETAIL = {
    "client_order_id": "8a19ed7a58094353a96cbaf92877547d",
    "combo_type": "NORMAL",
    "combo_order_id": "6LIM2HGGH4D2AKD3MTCAE9B55B",
    "orders": [
        {
            "symbol": "ZBH",
            "side": "BUY",
            "status": "FILLED",
            "client_order_id": "8a19ed7a58094353a96cbaf92877547d",
            "order_type": "MARKET",
            "order_id": "6LIM2HGGH4D2AKD3MTCAE9B55B",
            "total_quantity": "10",
            "filled_quantity": "10",
            "filled_price": "97.83",
            "filled_time_at": "2026-08-11T16:31:50.370Z",
        }
    ],
}


def test_the_order_detail_wrapper_is_unwrapped():
    """broker.orders_in is the shared unwrapper; sandbox_broker must use it or
    the fill is invisible."""
    from backend.services.broker import orders_in

    order = orders_in(LIVE_ORDER_DETAIL)[0]

    assert order["status"] == "FILLED"
    assert order["filled_price"] == "97.83"


def test_a_filled_order_is_settled_with_its_real_price(monkeypatch):
    from backend.services.broker import orders_in

    settled = {}

    class Trade:
        client_order_id = "8a19ed7a58094353a96cbaf92877547d"
        ticker, side, quantity, is_stop, reason = "ZBH", "buy", 10.0, False, None

    monkeypatch.setattr(agent.db, "get_pending_agent_trades", lambda: [Trade()])
    monkeypatch.setattr(
        agent.sandbox_broker, "get_order_detail", lambda _id: orders_in(LIVE_ORDER_DETAIL)[0]
    )
    monkeypatch.setattr(
        agent.db, "settle_agent_trade", lambda order_id, **kw: settled.update(kw)
    )

    assert len(agent.settle_pending()) == 1
    assert settled["status"] == "filled"
    assert settled["price"] == 97.83
    assert settled["quantity"] == 10.0


def test_a_partial_fill_records_what_filled_not_what_was_asked(monkeypatch):
    """A partial fill recorded at the requested size would put shares in the
    ledger that the account does not hold."""
    settled = {}
    partial = {
        "status": "PARTIAL_FILLED",
        "filled_quantity": "4",
        "filled_price": "97.83",
        "order_id": "x",
    }

    class Trade:
        client_order_id = "abc"
        ticker, side, quantity, is_stop, reason = "AAA", "buy", 4.0, False, None

    monkeypatch.setattr(agent.db, "get_pending_agent_trades", lambda: [Trade()])
    monkeypatch.setattr(agent.sandbox_broker, "get_order_detail", lambda _id: partial)
    monkeypatch.setattr(
        agent.db, "settle_agent_trade", lambda order_id, **kw: settled.update(kw)
    )

    agent.settle_pending()

    assert settled["quantity"] == 4.0


def test_a_rejected_order_is_marked_not_left_pending(monkeypatch):
    settled = {}

    class Trade:
        client_order_id = "abc"
        ticker, side, quantity, is_stop, reason = "AAA", "buy", 4.0, False, None

    monkeypatch.setattr(agent.db, "get_pending_agent_trades", lambda: [Trade()])
    monkeypatch.setattr(
        agent.sandbox_broker, "get_order_detail", lambda _id: {"status": "CANCELLED"}
    )
    monkeypatch.setattr(
        agent.db, "settle_agent_trade", lambda order_id, **kw: settled.update(kw)
    )

    assert len(agent.settle_pending()) == 1
    assert settled["status"] == "rejected"


# --- the budget the model can see ----------------------------------------------


def test_the_prompt_states_what_is_affordable_rather_than_implying_it():
    """The model proposed $1,944 of buys against $1,000 of cash on a live run.
    The share count it got wrong is now arithmetic Python does."""
    book = _book(cash=100.0)

    class S:
        ticker = "AAA"
        signal_date = "2026-08-11"
        decision = "Buy"
        entry_price = stop_loss = price_target = None
        win_probability = risk_reward = expected_value_r = None

    prompt = agent.build_prompt(book, [S()], {"AAA": 30.0})

    assert "afford 3 share(s)" in prompt


def test_the_prompt_says_when_nothing_is_affordable():
    book = _book(cash=5.0)

    class S:
        ticker = "AAA"
        signal_date = "2026-08-11"
        decision = "Buy"
        entry_price = stop_loss = price_target = None
        win_probability = risk_reward = expected_value_r = None

    assert "cannot afford any" in agent.build_prompt(book, [S()], {"AAA": 97.83})


def test_the_prompt_explains_that_selling_funds_a_buy():
    book = _book(cash=10.0, holdings=[("AAA", 10, 90.0)])
    book.holdings[0].price = 97.0

    prompt = agent.build_prompt(book, [], {})

    assert "Selling all 10 would raise about $970.00" in prompt
    assert "sell something" in prompt


def test_the_prompt_says_the_total_is_what_is_capped():
    """"You may only spend uninvested cash" was read as a per-order rule."""
    prompt = agent.build_prompt(_book(cash=250.0), [], {})
    assert "$250.00 or less in total" in prompt
    assert "Not each — in total." in prompt


def test_the_prompt_defines_what_hold_means():
    """It bought 98% of the budget into a stock whose only signal was Hold."""
    prompt = agent.build_prompt(_book(), [], {})
    assert "a Hold is not a reason to buy it" in prompt


def test_rejections_are_fed_back_for_a_second_attempt():
    rejections = [agent_book.Rejection("VT", "buy", 6, "costs $966.06 but only $22.20 is uninvested")]

    prompt = agent.build_prompt(_book(cash=22.20), [], {}, rejected=rejections)

    assert "Your previous answer was refused" in prompt
    assert "costs $966.06" in prompt


def test_an_overspend_triggers_exactly_one_retry(monkeypatch):
    asked = []

    def fake_ask(prompt):
        asked.append(prompt)
        if len(asked) == 1:
            return '{"reasoning": "greedy", "orders": [{"ticker": "AAA", "side": "buy", "quantity": 10}]}'
        return '{"reasoning": "resized", "orders": [{"ticker": "AAA", "side": "buy", "quantity": 2}]}'

    monkeypatch.setattr(agent, "_ask", fake_ask)

    reasoning, accepted, rejected = agent._decide(_book(cash=250.0), [], {"AAA": 100.0})

    assert len(asked) == 2, "one refusal should produce one correction pass, no more"
    assert "Your previous answer was refused" in asked[1]
    assert reasoning == "resized"
    assert [o["quantity"] for o in accepted] == [2.0]
    assert rejected == []


def test_a_clean_answer_is_not_second_guessed(monkeypatch):
    asked = []

    def fake_ask(prompt):
        asked.append(prompt)
        return '{"reasoning": "fine", "orders": [{"ticker": "AAA", "side": "buy", "quantity": 1}]}'

    monkeypatch.setattr(agent, "_ask", fake_ask)
    agent._decide(_book(cash=250.0), [], {"AAA": 100.0})

    assert len(asked) == 1


def test_a_retry_that_proposes_nothing_keeps_the_first_valid_orders(monkeypatch):
    """Standing pat on the retry must not throw away orders that were fine."""
    replies = iter([
        '{"reasoning": "two things", "orders": ['
        '{"ticker": "AAA", "side": "buy", "quantity": 2},'
        '{"ticker": "BBB", "side": "buy", "quantity": 99}]}',
        '{"reasoning": "never mind", "orders": []}',
    ])
    monkeypatch.setattr(agent, "_ask", lambda _p: next(replies))

    _, accepted, _ = agent._decide(_book(cash=250.0), [], {"AAA": 100.0, "BBB": 100.0})

    assert [o["ticker"] for o in accepted] == ["AAA"]


def test_a_still_unaffordable_retry_does_not_loop(monkeypatch):
    asked = []

    def fake_ask(prompt):
        asked.append(prompt)
        return '{"reasoning": "stubborn", "orders": [{"ticker": "AAA", "side": "buy", "quantity": 50}]}'

    monkeypatch.setattr(agent, "_ask", fake_ask)
    _, accepted, rejected = agent._decide(_book(cash=250.0), [], {"AAA": 100.0})

    assert len(asked) == 2
    assert accepted == []
    assert len(rejected) == 1


def test_a_placed_order_is_settled_before_the_run_is_reported(monkeypatch):
    """A market order fills in under a second, but nothing notices until the
    next scheduled pass — so the Discord post and the dashboard would spend a
    day showing cash that was already spent, next to an order marked "waiting
    to fill" that filled immediately."""
    calls = []

    monkeypatch.setattr(agent.quotes, "is_sandbox", lambda: True)
    monkeypatch.setattr(agent, "is_enabled", lambda: True)
    monkeypatch.setattr(agent.watchdog, "is_us_market_hours", lambda: True)
    monkeypatch.setattr(agent, "settle_pending", lambda: calls.append("settle") or [])
    monkeypatch.setattr(agent, "_recent_signals", lambda: [])
    monkeypatch.setattr(agent.db, "get_recent_signals", lambda limit=200: [])
    monkeypatch.setattr(agent.agent_book, "closed_trades", lambda decisions=None: [])
    monkeypatch.setattr(agent, "_price_map", lambda _t: {"AAA": 10.0})
    monkeypatch.setattr(
        agent.agent_book, "build_book",
        lambda price_lookup=None: calls.append("book") or _book(cash=500.0),
    )
    monkeypatch.setattr(
        agent, "_decide",
        lambda *a, **kw: ("go", [{"ticker": "AAA", "side": "buy", "quantity": 1}], []),
    )
    monkeypatch.setattr(
        agent.sandbox_broker, "place_market_order",
        lambda *a: {"client_order_id": "x", "placed_at": None},
    )
    monkeypatch.setattr(agent.db, "record_agent_trade", lambda **kw: 1)

    run = agent.run_once()

    assert run.placed
    # Settled at both ends: once before deciding so the book is current, once
    # after placing so what is reported is what happened.
    assert calls.count("settle") == 2
    assert calls.index("settle") < calls.index("book")


def test_a_run_that_places_nothing_does_not_settle_twice(monkeypatch):
    calls = []
    monkeypatch.setattr(agent.quotes, "is_sandbox", lambda: True)
    monkeypatch.setattr(agent, "is_enabled", lambda: True)
    monkeypatch.setattr(agent.watchdog, "is_us_market_hours", lambda: True)
    monkeypatch.setattr(agent, "settle_pending", lambda: calls.append("settle") or [])
    monkeypatch.setattr(agent, "_recent_signals", lambda: [])
    monkeypatch.setattr(agent.db, "get_recent_signals", lambda limit=200: [])
    monkeypatch.setattr(agent.agent_book, "closed_trades", lambda decisions=None: [])
    monkeypatch.setattr(agent, "_price_map", lambda _t: {})
    monkeypatch.setattr(agent.agent_book, "build_book", lambda price_lookup=None: _book())
    monkeypatch.setattr(agent, "_decide", lambda *a, **kw: ("hold", [], []))

    agent.run_once()

    assert calls.count("settle") == 1


# --- learning from its own record ----------------------------------------------


def _closed(ticker="AAA", entry=100.0, exit=110.0, days=5, decision=None, qty=2):
    import datetime

    return agent_book.ClosedTrade(
        ticker=ticker,
        quantity=qty,
        entry=entry,
        exit=exit,
        opened=datetime.date(2026, 8, 1),
        closed=datetime.date(2026, 8, 1) + datetime.timedelta(days=days),
        signal_decision=decision,
    )


def test_an_empty_record_adds_nothing_to_the_prompt():
    """"You have made no trades" is noise on day one, and the holdings section
    already says the book is empty."""
    assert agent.describe_history([]) == []


def test_the_record_leads_with_the_score():
    lines = agent.describe_history([_closed(exit=110.0), _closed(exit=90.0)])

    assert "2 closed, 1 profitable" in lines[0]
    assert "held 5 days on average" in lines[0]


def test_each_past_trade_shows_its_return_and_what_the_analyst_had_said():
    lines = agent.describe_history([_closed(entry=100.0, exit=110.0, decision="Buy")])

    assert any("+10.0% over 5 day(s) (analyst said Buy)" in line for line in lines)


def test_buying_on_hold_signals_is_called_out_once_there_is_a_pattern():
    """The model put 98% of the budget into a stock whose only signal was Hold.
    One instance is an anecdote; two is worth telling it about."""
    closed = [_closed(decision="Hold", exit=90.0), _closed(decision="Hold", exit=95.0)]

    lines = agent.describe_history(closed)

    assert any("bought on a Hold signal, 0 made money" in line for line in lines)


def test_a_single_hold_trade_is_not_called_a_pattern():
    lines = agent.describe_history([_closed(decision="Hold", exit=90.0)])
    assert not any("Hold signal," in line for line in lines)


def test_only_the_most_recent_trades_are_listed_individually():
    """The list must not crowd out today's actual decision."""
    closed = [_closed(ticker=f"T{i}") for i in range(20)]

    lines = agent.describe_history(closed)

    assert len(lines) - 1 <= agent._HISTORY_SHOWN
    assert "T19" in "\n".join(lines)
    assert "T0:" not in "\n".join(lines)


def test_the_record_reaches_the_prompt():
    prompt = agent.build_prompt(
        _book(), [], {}, closed=[_closed(decision="Buy", entry=100.0, exit=120.0)]
    )
    assert "How your own past trades turned out" in prompt


# --- resting stops -------------------------------------------------------------


def test_a_buy_arms_both_exits(monkeypatch):
    placed = {}
    monkeypatch.setattr(agent, "get_current_price", lambda t: 100.0)
    monkeypatch.setattr(
        agent.sandbox_broker, "place_exit_bracket",
        lambda t, q, stop, target: placed.update(ticker=t, qty=q, stop=stop, target=target)
        or [
            {"client_order_id": "s1", "kind": "stop", "price": stop, "placed_at": None},
            {"client_order_id": "t1", "kind": "target", "price": target, "placed_at": None},
        ],
    )
    recorded = []
    monkeypatch.setattr(agent.db, "record_agent_trade", lambda **kw: recorded.append(kw) or 1)

    agent._arm_exits({"ticker": "AAA", "quantity": 10, "side": "buy"}, 90.0, 120.0)

    assert placed == {"ticker": "AAA", "qty": 10, "stop": 90.0, "target": 120.0}
    assert [r["reason"] for r in recorded] == [
        "stop-loss resting at $90.00",
        "take-profit resting at $120.00",
    ]
    assert all(r["side"] == "sell" and r["is_stop"] for r in recorded)


def test_a_buy_with_neither_level_gets_no_exits(monkeypatch):
    """Inventing one would be inventing the exit price of a real trade."""
    called = []
    monkeypatch.setattr(agent.sandbox_broker, "place_exit_bracket", lambda *a: called.append(a))

    agent._arm_exits({"ticker": "AAA", "quantity": 10, "side": "buy"}, None, None)

    assert called == []


def test_only_the_level_that_exists_is_placed(monkeypatch):
    monkeypatch.setattr(agent, "get_current_price", lambda t: 100.0)
    """The trader states each only when it has a view."""
    monkeypatch.setattr(
        agent.sandbox_broker, "place_exit_bracket",
        lambda t, q, stop, target: [
            {"client_order_id": "t1", "kind": "target", "price": target, "placed_at": None}
        ],
    )
    recorded = []
    monkeypatch.setattr(agent.db, "record_agent_trade", lambda **kw: recorded.append(kw) or 1)

    agent._arm_exits({"ticker": "AAA", "quantity": 10, "side": "buy"}, None, 120.0)

    assert [r["reason"] for r in recorded] == ["take-profit resting at $120.00"]


def test_a_failed_exit_does_not_undo_the_buy(monkeypatch):
    monkeypatch.setattr(agent, "get_current_price", lambda t: 100.0)
    """The shares are already owned either way; raising here would leave the
    ledger disagreeing with the account."""
    def boom(*a):
        raise RuntimeError("broker said no")

    monkeypatch.setattr(agent.sandbox_broker, "place_exit_bracket", boom)
    monkeypatch.setattr(agent.db, "record_agent_trade", lambda **kw: 1)

    agent._arm_exits({"ticker": "AAA", "quantity": 10, "side": "buy"}, 90.0, 120.0)


def test_a_sell_does_not_arm_exits(monkeypatch):
    """An exit under a position being closed would try to sell shares twice."""
    called = []
    monkeypatch.setattr(agent.sandbox_broker, "place_exit_bracket", lambda *a: called.append(a))
    monkeypatch.setattr(agent, "_cancel_resting_exits", lambda t: 0)
    monkeypatch.setattr(agent.quotes, "is_sandbox", lambda: True)
    monkeypatch.setattr(agent, "is_enabled", lambda: True)
    monkeypatch.setattr(agent.watchdog, "is_us_market_hours", lambda: True)
    monkeypatch.setattr(agent, "settle_pending", lambda: [])
    monkeypatch.setattr(agent, "_recent_signals", lambda: [])
    monkeypatch.setattr(agent.db, "get_recent_signals", lambda limit=200: [])
    monkeypatch.setattr(agent.agent_book, "closed_trades", lambda decisions=None: [])
    monkeypatch.setattr(agent, "_price_map", lambda _t: {"AAA": 10.0})
    monkeypatch.setattr(agent.agent_book, "build_book", lambda price_lookup=None: _book())
    monkeypatch.setattr(
        agent, "_decide",
        lambda *a, **kw: ("out", [{"ticker": "AAA", "side": "sell", "quantity": 1}], []),
    )
    monkeypatch.setattr(
        agent.sandbox_broker, "place_market_order",
        lambda *a: {"client_order_id": "x", "placed_at": None},
    )
    monkeypatch.setattr(agent.db, "record_agent_trade", lambda **kw: 1)

    agent.run_once()

    assert called == []


# --- context the model was previously missing ----------------------------------


def _priced_book(cash=100.0, holdings=None):
    import datetime

    book = _book(cash=cash, holdings=holdings or [("AAA", 10, 90.0)])
    for h in book.holdings:
        h.price = 100.0
        h.opened = datetime.date.today() - datetime.timedelta(days=21)
    return book


def test_a_holding_shows_what_share_of_the_account_it_is():
    """It put 98% of the budget into one stock without ever being told that was
    what it was doing."""
    prompt = agent.build_prompt(_priced_book(), [], {})
    assert "% of the account" in prompt


def test_concentration_is_measured_against_equity_not_cost():
    book = _priced_book(cash=0.0, holdings=[("AAA", 10, 50.0)])
    # 10 shares now worth $100 each = $1,000 of a $1,000 book.
    assert book.weight_pct(book.holdings[0]) == pytest.approx(100.0)


def test_a_holding_shows_how_long_it_has_been_held():
    """Nothing else in the book says a thesis has expired."""
    assert "held 21 day(s)" in agent.build_prompt(_priced_book(), [], {})


def test_the_intended_holding_window_is_stated():
    prompt = agent.build_prompt(_priced_book(), [], {}, horizon_days=14)
    assert "meant to be 14-day trades" in prompt
    assert "outlived the thesis" in prompt


def test_no_horizon_means_no_holding_rule():
    """Better silent than asserting a window that was never configured."""
    assert "meant to be" not in agent.build_prompt(_priced_book(), [], {})


def test_the_regime_line_leads_the_prompt():
    prompt = agent.build_prompt(_book(), [], {}, regime_line="Market conditions today: risk-off.")
    assert prompt.index("risk-off") < prompt.index("Your account is")


def test_a_missing_regime_adds_no_line():
    """A failed fetch must drop the line, not the decision."""
    assert "Market conditions" not in agent.build_prompt(_book(), [], {})


def test_an_unreadable_regime_does_not_break_the_run(monkeypatch):
    import backend.services.regime as regime_module

    monkeypatch.setattr(
        regime_module, "fetch_regime", lambda: (_ for _ in ()).throw(RuntimeError("no data"))
    )
    assert agent.current_regime_line() is None


def test_a_target_below_the_market_is_refused(monkeypatch):
    """A limit sell below the price fills at market, so arming it liquidates
    the position at once — and reports a loss as a profit. A live signal really
    did produce a $95.96 target on a stock trading at $97.57."""
    placed = {}
    monkeypatch.setattr(agent, "get_current_price", lambda t: 97.57)
    monkeypatch.setattr(
        agent.sandbox_broker, "place_exit_bracket",
        lambda t, q, stop, target: placed.update(stop=stop, target=target) or [],
    )
    monkeypatch.setattr(agent.db, "record_agent_trade", lambda **kw: 1)

    agent._arm_exits({"ticker": "ZBH", "quantity": 10, "side": "buy"}, 90.15, 95.96)

    assert placed == {"stop": 90.15, "target": None}


def test_a_stop_above_the_market_is_refused(monkeypatch):
    placed = {}
    monkeypatch.setattr(agent, "get_current_price", lambda t: 97.57)
    monkeypatch.setattr(
        agent.sandbox_broker, "place_exit_bracket",
        lambda t, q, stop, target: placed.update(stop=stop, target=target) or [],
    )
    monkeypatch.setattr(agent.db, "record_agent_trade", lambda **kw: 1)

    agent._arm_exits({"ticker": "AAA", "quantity": 1, "side": "buy"}, 99.0, 110.0)

    assert placed == {"stop": None, "target": 110.0}


def test_both_levels_on_the_wrong_side_arms_nothing(monkeypatch):
    called = []
    monkeypatch.setattr(agent, "get_current_price", lambda t: 100.0)
    monkeypatch.setattr(agent.sandbox_broker, "place_exit_bracket", lambda *a: called.append(a))

    agent._arm_exits({"ticker": "AAA", "quantity": 1, "side": "buy"}, 105.0, 95.0)

    assert called == []


def test_an_unknown_price_does_not_block_arming(monkeypatch):
    """The check is a guard against a bad level, not a reason to leave a
    position unguarded when the quote feed is down."""
    placed = {}
    monkeypatch.setattr(agent, "get_current_price", lambda t: None)
    monkeypatch.setattr(
        agent.sandbox_broker, "place_exit_bracket",
        lambda t, q, stop, target: placed.update(stop=stop, target=target) or [],
    )
    monkeypatch.setattr(agent.db, "record_agent_trade", lambda **kw: 1)

    agent._arm_exits({"ticker": "AAA", "quantity": 1, "side": "buy"}, 90.0, 110.0)

    assert placed == {"stop": 90.0, "target": 110.0}


# --- resetting the book --------------------------------------------------------


def _reset_world(monkeypatch, held, held_after=None, sell_fails=False, open_market=True):
    """The broker is the authority here, so ``held`` is what it reports."""
    monkeypatch.setattr(agent.quotes, "is_sandbox", lambda: True)
    monkeypatch.setattr(agent.watchdog, "is_us_market_hours", lambda: open_market)
    monkeypatch.setattr(agent, "_cancel_resting_exits", lambda t: 2)
    monkeypatch.setattr(agent.db, "get_pending_agent_trades", lambda: [])

    positions = iter([held, held_after if held_after is not None else {}])
    monkeypatch.setattr(agent.sandbox_broker, "get_positions", lambda: next(positions, {}))

    def sell(ticker, side, qty):
        if sell_fails:
            raise RuntimeError("market closed")
        return {"client_order_id": "x", "placed_at": None}

    monkeypatch.setattr(agent.sandbox_broker, "place_market_order", sell)
    cleared = []
    monkeypatch.setattr(agent.db, "clear_agent_trades", lambda: cleared.append(1) or 7)
    return cleared


def test_a_reset_closes_positions_and_clears(monkeypatch):
    cleared = _reset_world(monkeypatch, held={"AAA": 10.0})

    result = agent.reset_book()

    assert result.closed == ["10 AAA"]
    assert result.cleared == 7 and cleared == [1]


def test_an_already_flat_account_just_clears_the_ledger(monkeypatch):
    """Reset from Webull's own site: nothing to sell, so the market's hours are
    irrelevant."""
    cleared = _reset_world(monkeypatch, held={}, open_market=False)

    result = agent.reset_book()

    assert result.closed == []
    assert result.cleared == 7 and cleared == [1]


def test_a_reset_refuses_before_touching_anything_when_the_market_is_shut(monkeypatch):
    """Started after the close, a reset cancels the exits, fails to sell, and
    leaves the positions naked overnight. That happened once; this is why the
    check comes before the first cancel."""
    touched = []
    monkeypatch.setattr(agent.quotes, "is_sandbox", lambda: True)
    monkeypatch.setattr(agent.watchdog, "is_us_market_hours", lambda: False)
    monkeypatch.setattr(agent.sandbox_broker, "get_positions", lambda: {"AAA": 1.0})
    monkeypatch.setattr(agent, "_cancel_resting_exits", lambda t: touched.append("cancel") or 1)
    monkeypatch.setattr(agent.sandbox_broker, "place_market_order", lambda *a: touched.append("sell"))
    monkeypatch.setattr(agent.db, "clear_agent_trades", lambda: touched.append("clear") or 0)

    result = agent.reset_book()

    assert touched == [], "nothing may be touched when the reset cannot finish"
    assert "market opens" in result.refused


def test_the_ledger_survives_if_the_account_is_not_flat_afterwards(monkeypatch):
    """Clearing while shares remain leaves the ledger claiming nothing and the
    broker holding stock — the one disagreement reconciliation cannot fix."""
    cleared = _reset_world(monkeypatch, held={"AAA": 10.0}, held_after={"AAA": 10.0})

    result = agent.reset_book()

    assert result.cleared == 0 and cleared == []
    assert "still holds" in result.refused


def test_the_ledger_survives_if_a_sell_fails(monkeypatch):
    cleared = _reset_world(monkeypatch, held={"AAA": 10.0}, sell_fails=True)

    result = agent.reset_book()

    assert cleared == []
    assert "Couldn't close AAA" in result.refused


def test_the_ledger_survives_if_the_account_cannot_be_read(monkeypatch):
    monkeypatch.setattr(agent.quotes, "is_sandbox", lambda: True)
    monkeypatch.setattr(agent.sandbox_broker, "get_positions", lambda: None)
    cleared = []
    monkeypatch.setattr(agent.db, "clear_agent_trades", lambda: cleared.append(1) or 0)

    result = agent.reset_book()

    assert cleared == []
    assert "Couldn't read the account" in result.refused


def test_a_reset_is_refused_outside_the_sandbox(monkeypatch):
    monkeypatch.setattr(agent.quotes, "is_sandbox", lambda: False)
    result = agent.reset_book()
    assert result.cleared == 0
    assert "not in sandbox" in result.refused


def test_a_failed_sell_leaves_the_other_positions_protected(monkeypatch):
    """Cancelling every exit up front means one failure exposes the whole book
    instead of the single position being closed."""
    cancelled = []
    monkeypatch.setattr(agent.quotes, "is_sandbox", lambda: True)
    monkeypatch.setattr(agent.watchdog, "is_us_market_hours", lambda: True)
    monkeypatch.setattr(agent.sandbox_broker, "get_positions", lambda: {"AAA": 1.0, "BBB": 1.0})
    monkeypatch.setattr(agent, "_cancel_resting_exits", lambda t: cancelled.append(t) or 1)

    def sell(*a):
        raise RuntimeError("rejected")

    monkeypatch.setattr(agent.sandbox_broker, "place_market_order", sell)
    monkeypatch.setattr(agent.db, "clear_agent_trades", lambda: 0)

    agent.reset_book()

    assert cancelled == ["AAA"], "BBB's exits must still be resting"


def test_exits_left_over_from_a_site_reset_are_cancelled(monkeypatch):
    """An exit resting against a position that no longer exists is an order to
    sell shares the account does not have."""
    monkeypatch.setattr(agent.quotes, "is_sandbox", lambda: True)
    monkeypatch.setattr(agent.sandbox_broker, "get_positions", lambda: {})

    class Stop:
        client_order_id, is_stop = "s1", True

    monkeypatch.setattr(agent.db, "get_pending_agent_trades", lambda: [Stop()])
    monkeypatch.setattr(agent.sandbox_broker, "cancel_order", lambda _id: True)
    monkeypatch.setattr(agent.db, "clear_agent_trades", lambda: 3)

    result = agent.reset_book()

    assert result.cancelled == 1
    assert result.cleared == 3


def test_a_reset_ahead_of_a_site_flatten_disables_the_agent(monkeypatch):
    """Between the ledger being cleared and the account being flattened the two
    disagree. An agent trading into that gap buys positions the site reset then
    wipes, leaving the ledger claiming stock that is gone."""
    monkeypatch.setattr(agent.quotes, "is_sandbox", lambda: True)
    monkeypatch.setattr(agent.sandbox_broker, "get_positions", lambda: {"AAA": 1.0})
    monkeypatch.setattr(agent, "_cancel_resting_exits", lambda t: 2)
    monkeypatch.setattr(agent.db, "clear_agent_trades", lambda: 5)
    disabled = []
    monkeypatch.setattr(agent, "set_enabled", lambda on: disabled.append(on))

    result = agent.reset_book(pending_external_flatten=True)

    assert result.cleared == 5
    assert result.cancelled == 2, "live exits must not outlive the ledger that tracked them"
    assert disabled == [False]
    assert "switched OFF" in result.refused


def test_the_normal_reset_still_refuses_a_held_account(monkeypatch):
    """The escape hatch must be asked for explicitly, never the default."""
    monkeypatch.setattr(agent.quotes, "is_sandbox", lambda: True)
    monkeypatch.setattr(agent.watchdog, "is_us_market_hours", lambda: False)
    monkeypatch.setattr(agent.sandbox_broker, "get_positions", lambda: {"AAA": 1.0})
    cleared = []
    monkeypatch.setattr(agent.db, "clear_agent_trades", lambda: cleared.append(1) or 0)

    agent.reset_book()

    assert cleared == []


def test_a_run_outside_market_hours_is_refused_before_the_model_is_asked(monkeypatch):
    """Orders go in at market, and the venue refuses those outside the session.
    Deciding first spends a couple of minutes of GPU producing orders that
    cannot be placed — which is exactly what happened at 17:48 ET: it decided
    to buy 6 VT and the broker returned FIXGW_NOT_READY_MARKET."""
    asked = []
    monkeypatch.setattr(agent.quotes, "is_sandbox", lambda: True)
    monkeypatch.setattr(agent, "is_enabled", lambda: True)
    monkeypatch.setattr(agent.watchdog, "is_us_market_hours", lambda: False)
    monkeypatch.setattr(agent, "_decide", lambda *a, **kw: asked.append(1) or ("", [], []))

    run = agent.run_once()

    assert asked == [], "the model must not be asked when nothing could be placed"
    assert "market is closed" in run.skipped
    assert "13:35" in run.skipped, "it should say when it will run on its own"


# --- conviction ----------------------------------------------------------------


class _Sig:
    ticker = "AAA"
    signal_date = "2026-08-12"
    decision = "Buy"
    entry_price = 100.0
    stop_loss = 90.0
    price_target = 130.0
    win_probability = None
    risk_reward = None
    expected_value_r = None


def test_a_signal_carries_how_good_the_bet_was():
    """Without these every Buy reads as equally good and the choice between
    them comes down to what happens to be affordable."""
    sig = _Sig()
    sig.win_probability, sig.risk_reward, sig.expected_value_r = 64.0, 2.4, 0.81

    prompt = agent.build_prompt(_book(), [sig], {"AAA": 100.0})

    assert "64% chance of working" in prompt
    assert "risk/reward 2.4 to 1" in prompt
    assert "expected value +0.81R" in prompt


def test_a_negative_expected_value_keeps_its_sign():
    """A bet that does not pay at its own stated odds must not read as one that
    does."""
    sig = _Sig()
    sig.expected_value_r = -0.35

    assert "expected value -0.35R" in agent.build_prompt(_book(), [sig], {"AAA": 100.0})


def test_a_signal_without_conviction_numbers_says_nothing_about_them():
    """They are optional on the schema — the trader states them only when it
    has a view — and an absent number must not read as a zero."""
    prompt = agent.build_prompt(_book(), [_Sig()], {"AAA": 100.0})

    assert "chance of working" not in prompt
    assert "expected value" not in prompt.split("Rules:")[0]


def test_the_rules_explain_what_the_numbers_mean():
    sig = _Sig()
    sig.expected_value_r = 0.5
    prompt = agent.build_prompt(_book(), [sig], {"AAA": 100.0})

    assert "one R is the amount risked" in prompt
    # Defining them is information; ranking by them would be taking the
    # allocation decision away from the model, which is its to make.
    assert "prefer" not in prompt.lower()
