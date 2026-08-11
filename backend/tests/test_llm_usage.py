"""Per-run LLM cost telemetry.

The numbers exist to be multiplied by a cloud price per million tokens, so the
failure that matters is a run that silently reports zero — it reads as free.
These tests pin the two shapes providers report usage in, and that an
unmeasured run stays empty rather than becoming a confident zero.
"""
from types import SimpleNamespace

from backend.services import llm_usage
from backend.services.analysis import format_run_cost


def _response(input_tokens=None, output_tokens=None, llm_output=None):
    """A LangChain LLMResult, near enough: generations carrying a message with
    usage_metadata, plus the raw llm_output dict."""
    message = SimpleNamespace(
        usage_metadata=(
            {"input_tokens": input_tokens, "output_tokens": output_tokens}
            if input_tokens is not None
            else None
        )
    )
    return SimpleNamespace(
        generations=[[SimpleNamespace(message=message)]], llm_output=llm_output
    )


def test_tokens_accumulate_across_calls():
    tracker = llm_usage.UsageTracker()

    tracker.on_llm_end(_response(100, 20))
    tracker.on_llm_end(_response(300, 50))
    usage = tracker.finish(12.5)

    assert usage.prompt_tokens == 400
    assert usage.completion_tokens == 70
    assert usage.total_tokens == 470
    assert usage.llm_calls == 2
    assert usage.duration_seconds == 12.5


def test_falls_back_to_the_raw_openai_usage_block():
    """Not every client populates usage_metadata; the OpenAI-shaped
    llm_output is the other place the same numbers arrive."""
    tracker = llm_usage.UsageTracker()

    tracker.on_llm_end(
        _response(llm_output={"token_usage": {"prompt_tokens": 7, "completion_tokens": 3}})
    )

    assert tracker.usage.prompt_tokens == 7
    assert tracker.usage.completion_tokens == 3


def test_a_response_with_no_usage_still_counts_as_a_call():
    """Zero tokens over several calls means the endpoint stopped reporting
    usage; zero over zero calls means the run died. Keeping the call count
    apart from the totals is what separates them."""
    tracker = llm_usage.UsageTracker()

    tracker.on_llm_end(_response())
    usage = tracker.finish(1.0)

    assert usage.llm_calls == 1
    assert usage.total_tokens == 0


def test_attach_keeps_callbacks_the_client_already_had():
    tracker = llm_usage.UsageTracker()
    existing = object()
    llm = SimpleNamespace(callbacks=[existing])

    llm_usage.attach(tracker, llm)

    assert llm.callbacks == [existing, tracker]


def test_attach_handles_a_client_with_no_callbacks():
    tracker = llm_usage.UsageTracker()
    llm = SimpleNamespace(callbacks=None)

    llm_usage.attach(tracker, llm)

    assert llm.callbacks == [tracker]


def test_an_unmeasured_run_renders_no_cost_at_all():
    """A blank footer is right; "0s · 0 tokens" would read as a free run."""
    assert format_run_cost(None) is None
    assert format_run_cost(llm_usage.Usage()) is None


def test_run_cost_reads_as_time_then_tokens():
    usage = llm_usage.Usage(
        prompt_tokens=44_100, completion_tokens=4_100, llm_calls=23, duration_seconds=134.0
    )

    assert format_run_cost(usage) == "2m 14s · 48.2k tokens (44.1k in / 4.1k out)"


def test_run_cost_omits_the_minutes_on_a_short_run():
    usage = llm_usage.Usage(prompt_tokens=500, completion_tokens=100, duration_seconds=42.0)

    assert format_run_cost(usage) == "42s · 600 tokens (500 in / 100 out)"
