"""Running a second model alongside the one in use.

The scorecard's by-model table is what decides whether a model is worth
switching to, and it needs two models' signals in one table to say anything.
These cover the parts that keep the experiment from leaking into live
behaviour.

Pure — no LLM, no broker.
"""
import asyncio
from unittest import mock

import pytest

from backend.services import analysis


def test_the_provider_applies_to_one_graph_not_the_deployment(monkeypatch):
    """llm_provider is an ordinary config key, which is what makes a
    comparison possible without restarting the container — and therefore
    without running the two models on different days."""
    seen = {}

    class FakeGraph:
        def __init__(self, config=None):
            seen.update(config)
            self.deep_thinking_llm = self.quick_thinking_llm = object()

    monkeypatch.setattr(analysis, "TradingAgentsGraph", FakeGraph)

    analysis._build_graph("gemini-3.5-flash-lite", None, "google")

    assert seen["llm_provider"] == "google"
    assert seen["deep_think_llm"] == "gemini-3.5-flash-lite"


def test_omitting_the_provider_leaves_the_configured_one(monkeypatch):
    seen = {}

    class FakeGraph:
        def __init__(self, config=None):
            seen.update(config)
            self.deep_thinking_llm = self.quick_thinking_llm = object()

    monkeypatch.setattr(analysis, "TradingAgentsGraph", FakeGraph)
    configured = analysis.DEFAULT_CONFIG["llm_provider"]

    analysis._build_graph("some-model", None, None)

    assert seen["llm_provider"] == configured


def test_a_comparison_sweep_posts_nothing(monkeypatch):
    """It would otherwise announce the whole watchlist a second time. These
    signals are evidence, not news."""
    monkeypatch.setattr(
        analysis, "propagate_ticker",
        mock.AsyncMock(return_value=({}, "Hold")),
    )
    monkeypatch.setattr(analysis, "record_signal", lambda *a: object())
    monkeypatch.setattr(
        analysis, "notify", mock.AsyncMock(side_effect=AssertionError("must not post")),
        raising=False,
    )

    recorded = asyncio.run(analysis.run_comparison(["GOOG", "INTC"], "m", "google"))

    assert len(recorded) == 2


def test_one_failing_ticker_does_not_cost_the_day_s_sample(monkeypatch):
    """A vendor that 503s on a single call should cost one comparison point,
    not every other ticker."""
    async def flaky(ticker, model=None, provider=None):
        if ticker == "BAD":
            raise RuntimeError("503 UNAVAILABLE")
        return {}, "Hold"

    monkeypatch.setattr(analysis, "propagate_ticker", flaky)
    monkeypatch.setattr(analysis, "record_signal", lambda *a: object())

    recorded = asyncio.run(analysis.run_comparison(["BAD", "GOOG"], "m", "google"))

    assert len(recorded) == 1


def test_the_comparison_setting_starts_and_stops(monkeypatch):
    store = {}
    monkeypatch.setattr(analysis.db, "set_setting", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(analysis.db, "get_setting", lambda k: store.get(k))

    analysis.set_comparison("gemini-3.5-flash-lite", "google")
    assert analysis.get_comparison() == ("gemini-3.5-flash-lite", "google")

    # An empty model stops it, rather than needing a separate flag to unset.
    analysis.set_comparison(None)
    assert analysis.get_comparison() == (None, None)
