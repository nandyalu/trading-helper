"""The real transaction log must never be reconciled against the simulated
account.

broker.run_sync reconciles additively — an unknown holding becomes a synthetic
buy, a quantity difference becomes a delta transaction — so pointing it at the
sandbox writes paper positions into the book that carries real purchase dates
going back to 2021. Nothing is deleted, which is exactly what makes it
dangerous: the corruption looks like data.

This is the test that has to keep passing when the Webull credentials are the
sandbox pair.
"""
import pytest

from backend.services import broker, quotes


@pytest.fixture
def sandbox(monkeypatch):
    monkeypatch.setenv("WEBULL_SANDBOX", "1")


@pytest.fixture
def production(monkeypatch):
    monkeypatch.setenv("WEBULL_SANDBOX", "0")


def test_sync_refuses_to_run_in_sandbox(sandbox, monkeypatch):
    called = False

    def fetch():
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(broker, "fetch_broker_positions", fetch)

    summary = broker.run_sync()

    assert not called, "the sandbox account must never be fetched for the real book"
    assert "sandbox" in summary.lower()


def test_sync_still_runs_against_production(production, monkeypatch):
    monkeypatch.setattr(broker, "fetch_broker_positions", lambda: None)

    # None means "couldn't reach the broker", which is the pre-existing
    # contract — the point here is only that the guard didn't fire.
    assert broker.run_sync() is None


@pytest.mark.parametrize("value,expected", [
    ("1", True), ("true", True), ("TRUE", True), ("yes", True),
    ("0", False), ("false", False), ("", False),
])
def test_sandbox_flag_parsing(monkeypatch, value, expected):
    monkeypatch.setenv("WEBULL_SANDBOX", value)
    assert quotes.is_sandbox() is expected


def test_sandbox_is_false_when_unset(monkeypatch):
    monkeypatch.delenv("WEBULL_SANDBOX", raising=False)
    assert quotes.is_sandbox() is False
