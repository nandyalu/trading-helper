"""Concurrent dispatch of multi-ticker analyses.

The Ollama pool fronts several GPUs, one request per backend. A caller that
awaits each ticker in a loop keeps exactly one LLM request in flight no matter
how many backends exist, so every GPU past the first idles for the whole sweep.
That is what the daily sweep, the watchdog triggers, and the earnings check all
used to do — the semaphore meant to bound concurrency never saw more than one
caller at a time.

These tests pin the dispatch shape. They never touch an LLM:
``run_analysis_and_notify`` is replaced with a stub that records how many calls
overlap. Plain sync tests driving ``asyncio.run`` — this suite has no
pytest-asyncio and needs none for five tests.
"""
import asyncio

from backend.services import analysis


class _Tracker:
    """Stands in for run_analysis_and_notify, recording peak overlap."""

    def __init__(self, delay: float = 0.02, fail: set[str] | None = None):
        self.delay = delay
        self.fail = fail or set()
        self.active = 0
        self.peak = 0
        self.seen: list[str] = []

    async def __call__(self, ticker: str):
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.seen.append(ticker)
        try:
            await asyncio.sleep(self.delay)
            if ticker in self.fail:
                raise RuntimeError(f"{ticker} blew up")
            return f"signal:{ticker}"
        finally:
            self.active -= 1


def _run(monkeypatch, tracker, tickers, on_failure=None):
    monkeypatch.setattr(analysis, "run_analysis_and_notify", tracker)
    return asyncio.run(analysis.run_analyses(tickers, on_failure=on_failure))


def test_tickers_run_concurrently_not_one_at_a_time(monkeypatch):
    tracker = _Tracker()
    _run(monkeypatch, tracker, ["AAA", "BBB", "CCC", "DDD"])

    assert tracker.peak > 1, "sequential dispatch would leave every extra GPU idle"
    assert sorted(tracker.seen) == ["AAA", "BBB", "CCC", "DDD"]


def test_one_failure_does_not_stop_the_others(monkeypatch):
    tracker = _Tracker(fail={"BBB"})
    signals = _run(monkeypatch, tracker, ["AAA", "BBB", "CCC"])

    assert sorted(tracker.seen) == ["AAA", "BBB", "CCC"]
    # The failure is dropped from the results, not raised out of the gather.
    assert sorted(signals) == ["signal:AAA", "signal:CCC"]


def test_failures_are_reported_once_each(monkeypatch):
    reported: list[str] = []

    async def on_failure(ticker: str) -> None:
        reported.append(ticker)

    _run(monkeypatch, _Tracker(fail={"AAA", "CCC"}), ["AAA", "BBB", "CCC"], on_failure)
    assert sorted(reported) == ["AAA", "CCC"]


def test_a_broken_notifier_does_not_lose_the_other_results(monkeypatch):
    async def on_failure(ticker: str) -> None:
        raise RuntimeError("Discord is down")

    signals = _run(monkeypatch, _Tracker(fail={"BBB"}), ["AAA", "BBB"], on_failure)
    assert signals == ["signal:AAA"]


def test_empty_list_is_a_no_op(monkeypatch):
    assert _run(monkeypatch, _Tracker(), []) == []
