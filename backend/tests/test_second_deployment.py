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


# --- which deployment this is --------------------------------------------------


def test_the_ordinary_deployment_is_the_default(monkeypatch):
    from backend.services import deployment

    monkeypatch.delenv("AGENT_ONLY", raising=False)
    assert deployment.is_agent_only() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_the_experiment_deployment_is_opt_in(monkeypatch, value):
    from backend.services import deployment

    monkeypatch.setenv("AGENT_ONLY", value)
    assert deployment.is_agent_only() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "", "off", "maybe"])
def test_anything_else_means_the_ordinary_deployment(monkeypatch, value):
    """A flag that hides pages must fail towards showing them. Guessing that an
    unrecognised value means "experiment" would silently hide the real book
    from someone who relies on it."""
    from backend.services import deployment

    monkeypatch.setenv("AGENT_ONLY", value)
    assert deployment.is_agent_only() is False


def test_the_mode_decides_nothing_about_safety():
    """AGENT_ONLY hides pages and skips jobs. Whether orders are simulated,
    which account they reach, and whether the app may short are decided in
    sandbox_broker and are identical in both deployments — a flag about what
    to display must never become a flag about what is safe."""
    import inspect

    from backend.services import deployment

    source = inspect.getsource(deployment)
    for forbidden in ("sandbox", "account", "short", "order"):
        assert forbidden not in source.lower().replace("# ", "").split("'''")[0].split('"""')[0]


# --- a deployment comes up correct without hand-correction ---------------------


def test_the_budget_defaults_per_deployment(monkeypatch):
    """A fresh database has no setting, and the two deployments start at
    different amounts. Correcting it by hand on first run is exactly the step
    that gets forgotten once and then reported as a bug."""
    from backend.services import agent_book

    monkeypatch.setattr(agent_book.db, "get_setting", lambda k: None)

    monkeypatch.delenv("AGENT_BUDGET", raising=False)
    assert agent_book.get_budget() == agent_book.DEFAULT_BUDGET

    monkeypatch.setenv("AGENT_BUDGET", "10000")
    assert agent_book.get_budget() == 10_000.0


def test_a_stored_budget_beats_the_env_default(monkeypatch):
    """The env var is only the default for an unset setting — the settings
    page still wins, same as the model."""
    from backend.services import agent_book

    monkeypatch.setenv("AGENT_BUDGET", "10000")
    monkeypatch.setattr(agent_book.db, "get_setting", lambda k: "2500")

    assert agent_book.get_budget() == 2500.0


@pytest.mark.parametrize("bad", ["nonsense", "-5", "0", ""])
def test_a_bad_budget_falls_back_rather_than_breaking(monkeypatch, bad):
    from backend.services import agent_book

    monkeypatch.setattr(agent_book.db, "get_setting", lambda k: None)
    monkeypatch.setenv("AGENT_BUDGET", bad)

    assert agent_book.get_budget() == agent_book.DEFAULT_BUDGET


def test_research_stays_free_unless_a_deployment_asks(monkeypatch):
    """The live deployment must not start charging just because this code
    reached it."""
    from backend.services import research

    monkeypatch.setattr(research.db, "get_setting", lambda k: None)

    monkeypatch.delenv("RESEARCH_PRICE_USD", raising=False)
    assert research.get_price() == 0.0

    monkeypatch.setenv("RESEARCH_PRICE_USD", "0.05")
    assert research.get_price() == 0.05


# --- one trade stream per app key ----------------------------------------------


def test_the_stream_can_be_switched_off(monkeypatch):
    """Webull allows one subscription per app key, so a second deployment
    sharing a key would only ever be refused. Not starting is better than
    being told no on a timer."""
    from backend.services import trade_stream

    monkeypatch.setenv("TRADE_STREAM", "0")
    assert trade_stream.start() is False


def test_a_permanent_refusal_stops_retrying(monkeypatch):
    """The refusal lasts as long as the other process runs, so a 60-second
    reconnect loop is pure noise against someone else's API."""
    from backend.services import trade_stream

    attempts = []

    class Client:
        on_connect = on_events_message = on_log = None

        def __init__(self, *a, **k):
            attempts.append(1)

        def do_subscribe(self, accounts):
            raise RuntimeError("RESOURCE_EXHAUSTED:appKey already has an active subscription")

    import webull.trade.trade_events_client as module

    monkeypatch.setattr(module, "TradeEventsClient", Client)
    monkeypatch.setattr(
        trade_stream._stop, "wait",
        lambda *a: pytest.fail("a permanent refusal must not be retried on a timer"),
    )

    trade_stream._run("DEM1", "key", "secret")

    assert attempts == [1], "it should give up after the first refusal"


def test_an_ordinary_drop_still_reconnects(monkeypatch):
    """A network blip is temporary and worth retrying — only the
    already-subscribed refusal is permanent."""
    from backend.services import trade_stream

    attempts = []

    class Client:
        on_connect = on_events_message = on_log = None

        def __init__(self, *a, **k):
            attempts.append(1)

        def do_subscribe(self, accounts):
            raise RuntimeError("connection reset by peer")

    import webull.trade.trade_events_client as module

    monkeypatch.setattr(module, "TradeEventsClient", Client)
    # Stop after the first sleep so the loop terminates.
    monkeypatch.setattr(trade_stream._stop, "wait", lambda *a: True)

    trade_stream._run("DEM1", "key", "secret")

    assert attempts == [1]
