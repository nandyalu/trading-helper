"""Live trade events.

The stream exists to cut the latency on a resting exit from fifteen minutes to
about a second. It must never become the thing correctness depends on: a stream
that silently stops looks exactly like a quiet market, so the poll stays and
these tests pin that an event only ever *triggers* the already-verified settle
path rather than parsing the payload itself.
"""
import pytest

from backend.services import trade_stream


@pytest.fixture(autouse=True)
def not_started(monkeypatch):
    monkeypatch.setattr(trade_stream, "_thread", None)
    monkeypatch.setattr(trade_stream, "_loop", None)


def test_an_event_settles_through_the_verified_path(monkeypatch):
    """Parsing the payload would put the fill price on a code path never seen
    in production. The last unverified payload shape left every fill pending
    forever."""
    from backend.services import agent

    called = []
    monkeypatch.setattr(agent, "settle_pending", lambda: called.append(1) or [])

    trade_stream._on_event(None, "any payload at all", None)

    assert called == [1]


def test_a_filled_stop_is_announced(monkeypatch):
    from backend.services import agent

    posted = []
    monkeypatch.setattr(
        agent, "settle_pending",
        lambda: [{"ticker": "ZBH", "quantity": 10, "price": 95.3,
                  "was_stop": True, "status": "filled", "reason": "stop-loss resting at $95.30"}],
    )
    monkeypatch.setattr(trade_stream, "_notify_from_thread", lambda fill: posted.append(fill))

    trade_stream._on_event(None, "payload", None)

    assert posted and posted[0]["ticker"] == "ZBH"


def test_an_ordinary_fill_is_not_announced(monkeypatch):
    """The run that placed it already reported it."""
    from backend.services import agent

    posted = []
    monkeypatch.setattr(
        agent, "settle_pending",
        lambda: [{"ticker": "ZBH", "quantity": 10, "price": 97.8,
                  "was_stop": False, "status": "filled"}],
    )
    monkeypatch.setattr(trade_stream, "_notify_from_thread", lambda fill: posted.append(fill))

    trade_stream._on_event(None, "payload", None)

    assert posted == []


def test_a_settle_failure_does_not_kill_the_stream(monkeypatch):
    """The callback runs on the gRPC thread; an exception escaping it would
    take the subscription down and the app would not notice."""
    from backend.services import agent

    def boom():
        raise RuntimeError("db locked")

    monkeypatch.setattr(agent, "settle_pending", boom)

    trade_stream._on_event(None, "payload", None)  # must not raise


def test_notifying_without_a_loop_is_a_no_op(monkeypatch):
    """Started outside the app there is no loop to hand the post back to."""
    monkeypatch.setattr(trade_stream, "_loop", None)
    trade_stream._notify_from_thread({"ticker": "AAA", "quantity": 1, "price": 1.0})


def test_the_stream_does_not_start_outside_the_sandbox(monkeypatch):
    monkeypatch.setattr(trade_stream.quotes, "is_sandbox", lambda: False)
    assert trade_stream.start() is False


def test_the_stream_does_not_start_without_an_account(monkeypatch):
    monkeypatch.setattr(trade_stream.quotes, "is_sandbox", lambda: True)
    monkeypatch.setenv("WEBULL_APP_KEY", "k")
    monkeypatch.setenv("WEBULL_APP_SECRET", "s")
    monkeypatch.setattr(trade_stream.sandbox_broker, "get_paper_account_id", lambda: None)

    assert trade_stream.start() is False


def test_an_unresolvable_account_does_not_raise(monkeypatch):
    """Never fatal: the app runs fine without the stream, just slower to
    notice a fill."""
    monkeypatch.setattr(trade_stream.quotes, "is_sandbox", lambda: True)
    monkeypatch.setenv("WEBULL_APP_KEY", "k")
    monkeypatch.setenv("WEBULL_APP_SECRET", "s")

    def boom():
        raise RuntimeError("no client")

    monkeypatch.setattr(trade_stream.sandbox_broker, "get_paper_account_id", boom)

    assert trade_stream.start() is False
