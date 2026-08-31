"""Turn recorded traces into a training file, filtered by how the run turned out.

Traces alone are not a dataset. What makes this one better than anything
public is that every trace joins to a ``Signal``, and that signal is graded
weeks later against what the market actually did. Training on the runs that
were *right* is a different and better thing than training on every run.

    python -m backend.scripts.export_training_set --out train.jsonl
    python -m backend.scripts.export_training_set --graded-pass --out train.jsonl
    python -m backend.scripts.export_training_set --model gemma4-e4b-qat-128k --out train.jsonl

Output is one JSON object per line, in the messages format every fine-tuning
tool accepts:

    {"messages": [{"role": "system", ...}, {"role": "user", ...},
                  {"role": "assistant", "content": ..., "tool_calls": [...]}]}

Filters stack. The strictest useful set is ``--graded-pass --model <teacher>``,
which is the distillation set described in docs/model-training.md: the runs a
model that works produced, keeping only those the market later agreed with.
"""
import argparse
import collections
import json
import os
import sys

from sqlmodel import Session, select

from backend.database.engine import engine
from backend.database.models import Signal
from backend.services import llm_traces

# langchain's message types, mapped to the role names fine-tuning tools expect.
ROLES = {"system": "system", "human": "user", "ai": "assistant", "tool": "tool"}


def signals_by_trace(model: str | None, graded_pass: bool) -> dict[str, Signal]:
    """The signals worth keeping, keyed by their trace id."""
    with Session(engine) as session:
        rows = session.exec(select(Signal).where(Signal.trace_id.is_not(None))).all()
    keep = {}
    for signal in rows:
        if model and signal.model != model:
            continue
        # "pass", not "correct". The column has only ever held pass/fail/NULL,
        # and the wrong string here matched nothing while looking exactly like
        # a dataset that had not graded yet.
        if graded_pass and signal.outcome != "pass":
            continue
        keep[signal.trace_id] = signal
    return keep


def trace_files(root: str) -> list[str]:
    found = []
    for day, _dirs, files in os.walk(root):
        found.extend(os.path.join(day, f) for f in files if f.endswith(".jsonl"))
    return sorted(found)


def to_example(call: dict) -> dict | None:
    """One recorded call as one training example.

    A call with no assistant turn is dropped: there is nothing to learn to
    produce. So is one with no input, which happens when the process died
    between the prompt and the response.
    """
    messages = []
    for message in call.get("messages") or []:
        role = ROLES.get(message.get("role"))
        if not role:
            continue
        entry = {"role": role, "content": message.get("content", "")}
        if message.get("tool_call_id"):
            entry["tool_call_id"] = message["tool_call_id"]
        if message.get("name"):
            entry["name"] = message["name"]
        messages.append(entry)
    if not messages:
        return None

    for output in call.get("output") or []:
        entry = {"role": "assistant", "content": output.get("content", "")}
        if output.get("tool_calls"):
            entry["tool_calls"] = output["tool_calls"]
        messages.append(entry)
    if messages[-1]["role"] != "assistant":
        return None
    return {"messages": messages}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--traces", default=llm_traces.TRACE_DIR,
                        help="trace directory (default: $LLM_TRACE_DIR)")
    parser.add_argument("--out", required=True, help="output .jsonl path")
    parser.add_argument("--model", help="keep only runs from this model")
    parser.add_argument("--graded-pass", action="store_true",
                        help="keep only runs whose signal the Scorecard graded a pass")
    args = parser.parse_args()

    if not args.traces:
        print("No trace directory. Set LLM_TRACE_DIR or pass --traces.", file=sys.stderr)
        return 2
    if not os.path.isdir(args.traces):
        print(f"No such directory: {args.traces}", file=sys.stderr)
        return 2

    keep = signals_by_trace(args.model, args.graded_pass)
    counts = collections.Counter()
    written = 0

    with open(args.out, "w", encoding="utf-8") as out:
        for path in trace_files(args.traces):
            for raw in open(path, encoding="utf-8"):
                try:
                    call = json.loads(raw)
                except json.JSONDecodeError:
                    counts["unreadable line"] += 1
                    continue
                if call.get("run_id") not in keep:
                    counts["no matching signal"] += 1
                    continue
                example = to_example(call)
                if example is None:
                    counts["no assistant turn"] += 1
                    continue
                out.write(json.dumps(example) + "\n")
                written += 1

    print(f"{written:,} example(s) written to {args.out}")
    print(f"from {len(keep):,} signal(s) matching the filters")
    for reason, n in counts.most_common():
        print(f"  skipped {n:,}: {reason}")
    if not written:
        print()
        print("Nothing was written. Either no traces have been recorded yet "
              "(LLM_TRACE_DIR unset when the analyses ran), or no signal has "
              "been graded a pass yet — grading needs the trade horizon to pass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
