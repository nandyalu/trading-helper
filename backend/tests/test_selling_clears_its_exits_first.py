"""A sell must clear its own resting exits before it goes to the broker.

**The broker refuses a sell while exits rest on the position.** A bracketed buy
leaves a stop and a target, each for the full quantity, so four shares held
already carry eight shares of sells. A third sell reads as going short and
returns OPENAPI_ORDER_NOT_SUPPORT_REVERSE_OPTION.

Until 2026-09-05 the cancel ran after the sell, so it never ran: the sell
raised, and the loop skipped past the cancel. A bracketed position could only
close through its own stop or target, and the agent could not choose to leave
one. It asked to sell MARA on 2026-09-04 and could not.
"""
import pytest

from backend.services import agent


@pytest.fixture
def broker(monkeypatch):
    """Records the order the app does things in."""
    steps = []

    monkeypatch.setattr(
        agent, "_cancel_resting_exits",
        lambda ticker: steps.append(("cancel", ticker))
        or [{"kind": "stop", "price": 9.68, "quantity": 4},
            {"kind": "target", "price": 12.37, "quantity": 4}],
    )
    monkeypatch.setattr(
        agent.sandbox_broker, "place_market_order",
        lambda ticker, side, qty: steps.append(("sell", ticker, side, qty))
        or {"client_order_id": "x", "placed_at": None},
    )
    monkeypatch.setattr(
        agent.sandbox_broker, "place_exit_bracket",
        lambda ticker, qty, stop, target: steps.append(("restore", ticker, stop, target)) or [],
    )
    return steps


def _sell():
    return {"ticker": "MARA", "side": "sell", "quantity": 4}


def test_the_exits_are_cancelled_before_the_sell(broker):
    """The whole defect, in one assertion. The reverse order is what the broker
    refuses, and what shipped."""
    agent._place(_sell(), price=10.0, stops={}, targets={})

    assert [s[0] for s in broker] == ["cancel", "sell"]


def test_the_sell_still_goes_out(broker):
    agent._place(_sell(), price=10.0, stops={}, targets={})

    assert ("sell", "MARA", "SELL", 4) in broker


def test_a_failed_sell_puts_the_exits_back(broker, monkeypatch):
    """Between the cancel and the fill the shares have nothing under them.
    Leaving them bare would replace one defect with a worse one."""
    monkeypatch.setattr(
        agent.sandbox_broker, "place_market_order",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("broker said no")),
    )

    with pytest.raises(RuntimeError):
        agent._place(_sell(), price=10.0, stops={}, targets={})

    assert [s[0] for s in broker] == ["cancel", "restore"]


def test_the_restore_uses_the_levels_that_were_resting(broker, monkeypatch):
    """Not the signal's levels. The agent moves its stops and targets during the
    day — it moved AVGO's twice on 2026-09-04 — so the signal is stale."""
    monkeypatch.setattr(
        agent.sandbox_broker, "place_market_order",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")),
    )

    with pytest.raises(RuntimeError):
        agent._place(_sell(), price=10.0, stops={"MARA": 1.0}, targets={"MARA": 99.0})

    restore = next(s for s in broker if s[0] == "restore")
    assert restore[2] == 9.68 and restore[3] == 12.37


def test_a_sell_with_nothing_resting_needs_no_restore(broker, monkeypatch):
    """A position bought without a bracket has no exits to put back, and a
    restore would invent an exit nobody chose."""
    monkeypatch.setattr(agent, "_cancel_resting_exits", lambda ticker: [])
    monkeypatch.setattr(
        agent.sandbox_broker, "place_market_order",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no")),
    )

    with pytest.raises(RuntimeError):
        agent._place(_sell(), price=10.0, stops={}, targets={})

    assert [s[0] for s in broker] == []


def test_a_buy_is_untouched_by_any_of_this(broker, monkeypatch):
    """A buy has no position to clear. Cancelling on one would remove the exits
    of a holding the agent is adding to."""
    monkeypatch.setattr(
        agent.sandbox_broker, "place_bracket_order",
        lambda *a, **k: {"client_order_id": "b", "placed_at": None, "exits": []},
    )

    agent._place({"ticker": "MARA", "side": "buy", "quantity": 4}, 10.0, {"MARA": 9.0}, {"MARA": 12.0})

    assert not any(s[0] == "cancel" for s in broker)


# --- the buying power margin ---------------------------------------------------


def test_the_affordable_count_leaves_room_for_the_margin():
    """Webull wants buying power 2% above a market order's estimated cost during
    regular hours. Without that margin the top share of every count was an order
    that could only fail — OPENAPI_DAY_BUYING_POWER_INSUFFICIENT_M_NEW, live on
    2026-09-04."""
    from backend.services import agent_book

    book = agent_book.Book(budget=10_000.0, cash=1_000.0, realized_pnl=0.0, holdings=[])

    class _Signal:
        ticker, decision, signal_date = "AAPL", "Buy", "2026-09-04"
        entry_price = stop_loss = price_target = None
        win_probability = risk_reward = expected_value_r = None
        trigger = None

    prompt = agent.build_prompt(book, [_Signal()], {"AAPL": 100.0})

    # 1000 / 100 is 10; 1000 / 102 is 9.
    assert "afford 9 share(s)" in prompt
