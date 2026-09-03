"""The stream callbacks must match what the SDK actually calls them with.

`on_connect` and `on_events_message` take a *different* number of arguments,
which is not documented anywhere. A handler written to the wrong shape does not
fail at startup — it fails on the first real event, and the reconnect loop hides
it behind a cheerful "stream connected" every 60 seconds.

That is what happened on 2026-09-03: the stream had never delivered a single
event. Fills were still recorded, because the 15-minute poll is the guarantee
and the stream is only a latency improvement, so nothing looked broken.

These tests read the signatures out of the installed SDK rather than restating
them, so an SDK upgrade that changes either one fails here instead of in a live
run.
"""
import inspect
import re

import pytest

from backend.services import trade_stream

webull_client = pytest.importorskip(
    "webull.trade.trade_events_client",
    reason="the Webull SDK is only installed in the container image",
)


def _sdk_call_arity(callback_name: str) -> int:
    """How many positional arguments the SDK passes to ``callback_name``."""
    source = inspect.getsource(webull_client)
    # The call to on_events_message spans two lines, so flatten first.
    flat = re.sub(r"\s+", " ", source)
    # ``def on_connect(self)`` and its setter match the same name, so drop
    # anything that is a definition rather than a call.
    calls = [
        m.group(1)
        for m in re.finditer(rf"(?<![_.\w])(?<!def ){callback_name}\((.*?)\)", flat)
    ]
    assert calls, f"no call to {callback_name} found in the SDK"
    # The last one is the invocation; the earlier ones are the property pair.
    return len([a for a in calls[-1].split(",") if a.strip()])


def _handler_arity(func) -> int:
    return len(inspect.signature(func).parameters)


def test_the_event_handler_takes_what_the_sdk_sends():
    assert _handler_arity(trade_stream._on_event) == _sdk_call_arity("on_events_message")


def test_the_connect_handler_takes_what_the_sdk_sends():
    assert _handler_arity(trade_stream._on_connect) == _sdk_call_arity("on_connect")


def test_the_two_callbacks_still_disagree():
    """The whole trap. If an SDK release makes them match, this fails and
    whoever reads it can simplify both handlers deliberately rather than
    discovering the difference the way it was discovered the first time."""
    assert _sdk_call_arity("on_events_message") != _sdk_call_arity("on_connect")
