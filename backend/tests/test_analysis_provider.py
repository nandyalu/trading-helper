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
    """llm_provider is an ordinary config key, so a model or vendor can be
    changed without restarting the container — which is what keeps a switch
    readable, since a redeploy would change the model between one morning and
    the next."""
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
