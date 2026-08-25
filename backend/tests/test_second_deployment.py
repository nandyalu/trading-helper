"""Guards that only matter once a second deployment exists.

The autonomous-analyst experiment runs against the sandbox's *margin* account
so the two books never mix. Two things change when it does, and both are
safety-shaped: the account has to be selectable, and the broker stops
enforcing long-only for us.

Pure — no broker calls.
"""
import pytest

from backend.services import sandbox_broker


# --- choosing the account ------------------------------------------------------


def test_the_cash_account_is_the_default(monkeypatch):
    monkeypatch.delenv("WEBULL_ACCOUNT_CLASS", raising=False)
    assert sandbox_broker.tradeable_account_class() == "INDIVIDUAL_CASH"


def test_a_deployment_can_select_the_margin_account(monkeypatch):
    monkeypatch.setenv("WEBULL_ACCOUNT_CLASS", "individual_margin")
    assert sandbox_broker.tradeable_account_class() == "INDIVIDUAL_MARGIN"


@pytest.mark.parametrize("bad", ["CRYPTO", "FUTURES", "EVENTS_CASH", "INDIVIDUAL_CASHH", "cash"])
def test_only_the_two_equities_classes_are_accepted(monkeypatch, bad):
    """A typo in an env var must not be able to point order flow at the crypto
    or futures account, and must fail loudly rather than matching nothing."""
    monkeypatch.setenv("WEBULL_ACCOUNT_CLASS", bad)
    with pytest.raises(ValueError, match="WEBULL_ACCOUNT_CLASS"):
        sandbox_broker.tradeable_account_class()


# --- long-only, once the broker stops enforcing it -----------------------------


def test_selling_more_than_held_is_refused(monkeypatch):
    """A cash account rejects this for free with GENERATE_NEW_SHORT_POSITION.
    A margin account accepts it and opens a short, so the rule has to live in
    this app the moment a deployment points at margin."""
    monkeypatch.setattr(sandbox_broker, "get_positions", lambda: {"ZBH": 3.0})

    with pytest.raises(ValueError, match="long-only"):
        sandbox_broker._assert_not_short("ZBH", 5)


def test_selling_what_is_held_is_allowed(monkeypatch):
    monkeypatch.setattr(sandbox_broker, "get_positions", lambda: {"ZBH": 3.0})

    sandbox_broker._assert_not_short("ZBH", 3)  # must not raise


def test_selling_a_ticker_not_held_at_all_is_refused(monkeypatch):
    monkeypatch.setattr(sandbox_broker, "get_positions", lambda: {})

    with pytest.raises(ValueError, match="holds 0"):
        sandbox_broker._assert_not_short("AAPL", 1)


def test_an_unreadable_position_allows_the_sell(monkeypatch):
    """Unknown is not zero. We cannot prove the sell is covered, but we cannot
    prove it is naked either — and refusing every exit because a position read
    failed would leave real positions unprotected."""
    monkeypatch.setattr(sandbox_broker, "get_positions", lambda: None)

    sandbox_broker._assert_not_short("ZBH", 3)  # must not raise


def test_a_market_sell_goes_through_the_check(monkeypatch):
    """The guard has to be on the order path, not merely available."""
    monkeypatch.setattr(sandbox_broker.quotes, "is_sandbox", lambda: True)
    monkeypatch.setattr(sandbox_broker, "get_positions", lambda: {"ZBH": 1.0})

    with pytest.raises(ValueError, match="long-only"):
        sandbox_broker.place_market_order("ZBH", "SELL", 10)


def test_a_buy_is_never_checked_against_holdings(monkeypatch):
    """Buying something not held is the normal case."""
    monkeypatch.setattr(sandbox_broker.quotes, "is_sandbox", lambda: True)
    monkeypatch.setattr(
        sandbox_broker, "get_positions",
        lambda: pytest.fail("a buy must not need a position read"),
    )
    monkeypatch.setattr(sandbox_broker.quotes, "get_api_client", lambda: None)

    # Fails for want of a client, which is past the long-only check.
    with pytest.raises(RuntimeError, match="No simulated account"):
        sandbox_broker.place_market_order("AAPL", "BUY", 1)
