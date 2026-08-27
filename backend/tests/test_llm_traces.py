"""Capturing every LLM call so a fine-tune is possible later.

A dataset of past runs cannot be collected afterwards, which is the whole
reason this exists before anyone has decided to train anything. The tests that
matter most here are the ones proving it never breaks a run: a trace is
telemetry, and losing telemetry must never lose the analysis it describes.

Pure — no LLM, no network.
"""
import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from backend.services import llm_traces


def _result(message) -> LLMResult:
    return LLMResult(generations=[[ChatGeneration(message=message)]])


@pytest.fixture
def recorder(tmp_path):
    return llm_traces.TraceRecorder(
        "20260827T120000-abcd1234", "AAPL", "gemma4-e4b-qat-128k", root=str(tmp_path)
    )


def _lines(recorder) -> list[dict]:
    with open(recorder.path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle]


# --- what gets written ---------------------------------------------------------


def test_one_call_writes_one_line_with_both_sides(recorder):
    recorder.on_chat_model_start(
        {}, [[SystemMessage("You are an analyst."), HumanMessage("Analyse AAPL.")]],
        run_id="call-1",
    )
    recorder.on_llm_end(_result(AIMessage("AAPL closed at $313.45.")), run_id="call-1")

    line = _lines(recorder)[0]
    assert [m["role"] for m in line["messages"]] == ["system", "human"]
    assert line["output"][0]["content"] == "AAPL closed at $313.45."
    assert line["ticker"] == "AAPL" and line["model"] == "gemma4-e4b-qat-128k"


def test_tool_calls_are_kept_apart_from_content(recorder):
    """The tool call is the part a fine-tune is learning, and a model writing
    it into the content field instead is the exact failure the dataset exists
    to fix. Flattening the two would hide it."""
    reply = AIMessage(
        content="",
        tool_calls=[{"name": "get_YFin_data", "args": {"symbol": "AAPL"}, "id": "t1"}],
    )
    recorder.on_chat_model_start({}, [[HumanMessage("Get prices.")]], run_id="c")
    recorder.on_llm_end(_result(reply), run_id="c")

    output = _lines(recorder)[0]["output"][0]
    assert output["tool_calls"] == [{"name": "get_YFin_data", "args": {"symbol": "AAPL"}}]


def test_a_tool_result_records_which_call_it_answers(recorder):
    recorder.on_chat_model_start(
        {}, [[ToolMessage(content="313.45", tool_call_id="t1", name="get_YFin_data")]],
        run_id="c",
    )
    recorder.on_llm_end(_result(AIMessage("ok")), run_id="c")

    message = _lines(recorder)[0]["messages"][0]
    assert message["tool_call_id"] == "t1" and message["name"] == "get_YFin_data"


def test_concurrent_calls_do_not_pair_the_wrong_prompt_with_the_wrong_answer(recorder):
    """The tool-calling nodes may finish off the main thread, so two calls can
    overlap inside one analysis."""
    recorder.on_chat_model_start({}, [[HumanMessage("first")]], run_id="a")
    recorder.on_chat_model_start({}, [[HumanMessage("second")]], run_id="b")
    recorder.on_llm_end(_result(AIMessage("answer-b")), run_id="b")
    recorder.on_llm_end(_result(AIMessage("answer-a")), run_id="a")

    by_output = {l["output"][0]["content"]: l["messages"][0]["content"] for l in _lines(recorder)}
    assert by_output == {"answer-a": "first", "answer-b": "second"}


def test_the_file_is_named_by_day_ticker_and_run(recorder, tmp_path):
    assert recorder.path == str(
        tmp_path / "20260827" / "AAPL-20260827T120000-abcd1234.jsonl"
    )


def test_a_runaway_context_is_clipped_rather_than_written_whole(recorder):
    recorder.on_chat_model_start(
        {}, [[HumanMessage("x" * (llm_traces.MAX_CHARS_PER_FIELD + 5_000))]], run_id="c"
    )
    recorder.on_llm_end(_result(AIMessage("ok")), run_id="c")

    content = _lines(recorder)[0]["messages"][0]["content"]
    assert "clipped" in content
    assert len(content) < llm_traces.MAX_CHARS_PER_FIELD + 200


# --- what must never happen ----------------------------------------------------


def test_an_unwritable_directory_does_not_raise(tmp_path):
    """Losing the telemetry for a run must never lose the run."""
    recorder = llm_traces.TraceRecorder("20260827T120000-x", "AAPL", "m", root="/proc/nope")

    recorder.on_chat_model_start({}, [[HumanMessage("hi")]], run_id="c")
    recorder.on_llm_end(_result(AIMessage("ok")), run_id="c")

    assert recorder.calls == 0


def test_a_malformed_response_does_not_raise(recorder):
    recorder.on_llm_end(object(), run_id="c")

    assert recorder.calls == 0


def test_recording_is_off_when_no_directory_is_configured(monkeypatch):
    """No default path, so a deployment that does not want the disk cost pays
    nothing and no volume fills up quietly."""
    monkeypatch.setattr(llm_traces, "TRACE_DIR", "")

    assert llm_traces.recorder_for("AAPL", "m") is None
    assert llm_traces.is_recording() is False


def test_recording_is_on_when_a_directory_is_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_traces, "TRACE_DIR", str(tmp_path))

    recorder = llm_traces.recorder_for("AAPL", "m")

    assert recorder is not None and recorder.ticker == "AAPL"


def test_a_run_id_sorts_by_date_and_is_unique():
    first, second = llm_traces.new_run_id(), llm_traces.new_run_id()

    assert first != second
    assert first.split("T")[0].isdigit() and len(first.split("T")[0]) == 8


# --- turning traces into a training set ----------------------------------------


def _call(run_id="r1", content="AAPL closed at $313.45.", tool_calls=None):
    output = {"role": "ai", "content": content}
    if tool_calls:
        output["tool_calls"] = tool_calls
    return {
        "run_id": run_id, "ticker": "AAPL", "model": "gemma4-e4b-qat-128k",
        "messages": [{"role": "system", "content": "You are an analyst."},
                     {"role": "human", "content": "Analyse AAPL."}],
        "output": [output],
    }


def test_a_call_becomes_a_messages_row_ending_in_the_assistant_turn():
    from backend.scripts.export_training_set import to_example

    example = to_example(_call())

    assert [m["role"] for m in example["messages"]] == ["system", "user", "assistant"]
    assert example["messages"][-1]["content"] == "AAPL closed at $313.45."


def test_the_tool_call_survives_the_export():
    """It is the part the fine-tune is learning. Losing it here would produce a
    dataset that teaches the model to answer without calling anything, which is
    the failure the whole exercise exists to fix."""
    from backend.scripts.export_training_set import to_example

    example = to_example(_call(tool_calls=[{"name": "get_stock_data", "args": {"symbol": "AAPL"}}]))

    assert example["messages"][-1]["tool_calls"][0]["name"] == "get_stock_data"


def test_a_call_with_no_assistant_turn_is_dropped():
    """Nothing to learn to produce. Happens when a run dies between the prompt
    and the response."""
    from backend.scripts.export_training_set import to_example

    call = _call()
    call["output"] = []

    assert to_example(call) is None
