"""Run the watchlist through a second model, to compare it against the one in use.

The comparison this app is built to make is not "which report reads better".
It is: given the same tickers, on the same day, at the same prices, which model
produces signals that turn out to be right? Every ``Signal`` records the model
that produced it, and the scorecard's ``by_model`` breakdown answers exactly
that question — but only once two models have signals in the same table.

So this records into the live database rather than a separate one. Two
alternatives were considered and are worse:

- **Flipping the deployment's provider and running the sweep again** compares
  models across different days, which means different prices and different
  news. That measures the market as much as the model.
- **A second container with its own database** runs in parallel but splits the
  evidence in two, so the one mechanism built for this comparison — ``by_model``
  — cannot see both halves. It also doubles the requests to the same
  rate-limited data sources and points a second Discord bot at one channel.

The provider is an ordinary config key, so a single run can name a different
vendor without restarting anything. See analysis._build_graph.

Nothing is posted to Discord. A comparison sweep would otherwise announce every
ticker a second time, and these signals are evidence rather than news.

The auto trader ignores them: agent._recent_signals filters to the model the
app is configured to use, so an experiment cannot quietly reach the live book.

Grading needs no help. Each signal carries its own evaluation date and the
nightly pass grades it like any other, which is what turns this from a
comparison of prose into a comparison of outcomes — about two weeks later.

One run:

    python -m backend.scripts.compare_model --model gemini-3.5-flash-lite \\
        --provider google [--tickers GOOG,INTC] --apply

Every day, chained to the morning sweep so both models see the same session:

    python -m backend.scripts.compare_model --model gemini-3.5-flash-lite \\
        --provider google --schedule
    python -m backend.scripts.compare_model --stop
"""
import argparse
import asyncio
import sys

from backend.database import db
from backend.services import analysis, listings


async def _run(model: str, provider: str | None, tickers: list[str]) -> int:
    recorded = failed = 0
    for ticker in tickers:
        print(f"  {ticker} … ", end="", flush=True)
        try:
            final_state, decision = await analysis.propagate_ticker(
                ticker, model=model, provider=provider
            )
        except Exception as exc:
            print(f"FAILED — {str(exc)[:120]}")
            failed += 1
            continue

        signal = await asyncio.to_thread(analysis.record_signal, ticker, final_state, decision)
        if signal is None:
            # No price to record it against — the same reason the daily sweep
            # skips a delisted ticker.
            print("no price, not recorded")
            failed += 1
            continue

        usage = final_state.get("llm_usage")
        cost = ""
        if usage is not None and usage.prompt_tokens:
            cost = (
                f" · {usage.prompt_tokens + usage.completion_tokens:,} tokens"
                f" · {usage.duration_seconds / 60:.1f} min"
            )
        print(f"{decision}{cost}")
        recorded += 1

    print()
    print(f"{recorded} signal(s) recorded as {model}, {failed} failed")
    if recorded:
        print("Compare them on the Scorecard's 'by model' table once they grade.")
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="the model to run, e.g. gemini-3.5-flash-lite")
    parser.add_argument(
        "--provider",
        help="vendor for this run only, e.g. google. Omit to use the configured one.",
    )
    parser.add_argument("--tickers", help="comma-separated. Omit for the whole watchlist.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually run. Without it, prints what would run and stops — an "
        "analysis costs minutes of GPU or real money per ticker.",
    )
    parser.add_argument(
        "--schedule",
        action="store_true",
        help="run this model every day, chained to the morning sweep, until --stop.",
    )
    parser.add_argument(
        "--stop", action="store_true", help="stop the daily comparison."
    )
    args = parser.parse_args()

    if args.stop:
        analysis.set_comparison(None)
        print("Daily comparison stopped. Signals already recorded are kept and still grade.")
        return 0

    if args.schedule:
        analysis.set_comparison(args.model, args.provider)
        print(f"Daily comparison on: {args.model} via {args.provider or 'the configured vendor'}.")
        print("It runs with the morning sweep, so both models see the same session.")
        print("Stop it with --stop. Nothing else changes: the app keeps using "
              f"{analysis.get_model()}.")
        return 0

    if not args.model:
        parser.error("--model is required unless you pass --stop")

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        inactive = set(listings.inactive_tickers())
        tickers = [t for t in db.get_watchlist() if t not in inactive]
        skipped = sorted(set(db.get_watchlist()) & inactive)
        if skipped:
            print(f"Skipping {', '.join(skipped)} — no market data")

    if not tickers:
        print("Nothing to analyse.")
        return 1

    print(f"Model    : {args.model}")
    print(f"Provider : {args.provider or '(the configured one)'}")
    print(f"Tickers  : {', '.join(tickers)}")
    print(f"Current  : {analysis.get_model()} — unchanged by this run")
    print()
    if not args.apply:
        print("Dry run — pass --apply to run. Each ticker is a full analysis.")
        return 0

    return asyncio.run(_run(args.model, args.provider, tickers))


if __name__ == "__main__":
    raise SystemExit(main())
