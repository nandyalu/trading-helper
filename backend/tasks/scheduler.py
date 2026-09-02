"""Scheduled jobs, on quiv. quiv's real job here is the interval/delay timer
(replacing discord.ext.tasks.loop) — each registered handler is a trivial
sync function that hops straight back to the main event loop via quiv's
run_on_main(). That hop is required, not optional: quiv runs a handler on
its own worker thread with a fresh, isolated event loop, but the actual job
bodies below touch main-loop-bound resources (the Discord client, the
analysis semaphore/asyncio.to_thread machinery in backend/services/analysis.py) that
aren't safe to touch from any other loop.

quiv has no cron/calendar scheduling (interval + delay only) — the five
daily jobs below approximate a fixed UTC time via interval=86400 plus a
delay computed to the next occurrence of that time, keeping each job's
existing internal weekday/Friday-only gate. alert_watchdog is a true
interval and maps over 1:1.
"""
import asyncio
import datetime
import logging
import os

from quiv import Quiv, run_on_main

from backend.database import db
from backend.services import (
    agent,
    analysis,
    candidates,
    journey,
    listings,
    quotes,
    regime,
    watchdog,
)
from backend.services.digest import build_weekly_digest_embed
from backend.discord_bot.notify import notify
from backend.services.positions import PriceWindow, get_price_window
from backend.services.signals import SignalEvaluation, evaluate_signal_window, horizon_params

log = logging.getLogger("trading-bot.scheduler")

scheduler = Quiv(pool_size=int(os.environ.get("QUIV_POOL_SIZE", "10")))


def _seconds_until(hour: int, minute: int) -> float:
    """Seconds from now (UTC) until the next occurrence of hour:minute UTC —
    today if still ahead, tomorrow otherwise."""
    now = datetime.datetime.now(datetime.timezone.utc)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()


def _format_outcome_line(signal, evaluation: SignalEvaluation, price_now: float) -> str:
    verdict = "PASS" if evaluation.outcome == "pass" else "FAIL"
    line = (
        f"{signal.ticker} {signal.decision} from {signal.signal_date}: **{verdict}** "
        f"(${signal.price_at_signal:,.2f} → ${price_now:,.2f}, {evaluation.pct_change:+.1f}%)"
    )
    if evaluation.outcome_vs_benchmark is not None:
        benchmark_verdict = "PASS" if evaluation.outcome_vs_benchmark == "pass" else "FAIL"
        line += (
            f" · vs SPY {evaluation.benchmark_pct_change:+.1f}%: **{benchmark_verdict}**"
            f" (alpha {evaluation.alpha_pct:+.1f}%)"
        )
    else:
        line += " · vs SPY: n/a"
    if signal.price_target and evaluation.price_target_hit is not None:
        line += f" · target ${signal.price_target:,.2f}: {'hit' if evaluation.price_target_hit else 'not hit'}"
    return line


async def _evaluate_pending_signals() -> None:
    spy_windows: dict[datetime.date, PriceWindow | None] = {}  # per-run cache, keyed by signal_date
    for signal in db.get_pending_signals(datetime.date.today()):
        window = get_price_window(signal.ticker, signal.signal_date)
        if window is None:
            continue  # retry next day rather than guessing
        if signal.signal_date not in spy_windows:
            spy_windows[signal.signal_date] = get_price_window("SPY", signal.signal_date)
        spy = spy_windows[signal.signal_date]
        evaluation = evaluate_signal_window(
            decision=signal.decision,
            price_at_signal=signal.price_at_signal,
            price_now=window.last_close,
            benchmark_price_at_signal=spy.first_close if spy else None,
            benchmark_price_now=spy.last_close if spy else None,
            price_target=signal.price_target,
            window_high=window.high,
            window_low=window.low,
            # Per-signal, not the current setting: a Hold graded over two weeks
            # needs a much tighter band than one graded over six months, and
            # changing the horizon must not re-grade older signals by new rules.
            hold_band_pct=horizon_params(signal.horizon)["hold_band_pct"],
        )
        db.resolve_signal(
            signal.id,
            price_at_evaluation=window.last_close,
            outcome=evaluation.outcome,
            benchmark_price_at_signal=spy.first_close if spy else None,
            benchmark_price_at_evaluation=spy.last_close if spy else None,
            alpha_pct=evaluation.alpha_pct,
            outcome_vs_benchmark=evaluation.outcome_vs_benchmark,
            price_target_hit=evaluation.price_target_hit,
        )
        await notify(_format_outcome_line(signal, evaluation, window.last_close))


async def _run_triggered_analyses(reasons: dict[str, str]) -> None:
    """``reasons`` maps ticker to why it was triggered, for the log.

    Runs them together — the shared semaphore is the backpressure, not this
    function, so several triggered tickers use several GPUs instead of queueing
    behind each other. Nothing is announced: an analysis starting is not
    something the agent did, and Discord carries only what it did.
    """
    for ticker, reason in reasons.items():
        log.info("Triggered analysis for %s: %s", ticker, reason)
    await analysis.run_analyses(
        list(reasons),
        on_failure=lambda ticker: notify(f"Triggered analysis failed for {ticker} — check the logs."),
    )
    await _maybe_run_agent()


# Event-driven agent runs are rate-limited. A triggered analysis takes about
# seven minutes and the watchdog ticks every fifteen, so a busy morning could
# otherwise have the model re-plan the whole book several times an hour against
# a book that has barely moved.
_AGENT_COOLDOWN = datetime.timedelta(minutes=30)
_last_agent_run: datetime.datetime | None = None


async def _settle_agent_fills() -> None:
    """Bring the agent's ledger up to date with the broker, and say so when a
    stop fired. Cheap — one request per still-open order, usually none."""
    if not agent.is_enabled():
        return
    try:
        settled = await asyncio.to_thread(agent.settle_pending)
    except Exception:
        log.exception("Couldn't settle agent orders")
        return
    for fill in settled:
        # A stop firing is the only trade here nobody chose to make, so it is
        # the one worth interrupting for. Ordinary fills already showed up in
        # the run that placed them.
        if fill["was_stop"] and fill["status"] == "filled":
            await notify(agent.format_stop_fill(fill))


async def _maybe_run_agent() -> None:
    """Let the agent act on fresh intraday signals, but only when it could
    actually trade on them.

    The morning sweep is deliberately *not* wired here. It runs at 11:00 UTC,
    two and a half hours before the open, so nothing placed then could fill —
    and deciding its nine signals one at a time would hand the budget out
    first-come-first-served instead of comparing them against each other, which
    is the entire job. Those go to the 13:35 batch, which decides on all of
    them at once, on opening prices.

    Intraday triggers are the opposite case: they arrive while the market is
    open, and a move worth analyzing at 11:00 is worth nothing by tomorrow
    morning. The earnings check reaches this too, but runs pre-market, so it
    falls through the market-hours gate to the batch — which is right.
    """
    global _last_agent_run
    if not agent.is_enabled() or not watchdog.is_us_market_hours():
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    if _last_agent_run is not None and now - _last_agent_run < _AGENT_COOLDOWN:
        log.info("Agent ran %s ago — inside the cooldown, skipping", now - _last_agent_run)
        return
    _last_agent_run = now
    try:
        run = await asyncio.to_thread(agent.run_once)
    except Exception:
        log.exception("Event-driven agent run failed")
        return
    # A note is worth posting even on a day it did nothing else: it is the
    # agent saying it is short of something, which is the point of having it.
    if run.acted or run.rejected or run.failed or run.notes:
        await notify(embed=agent.format_run_embed(run))


async def _daily_signals_job() -> None:
    """21:30 UTC (17:30 ET): grade what matured, then write the journal.

    Stays after the close because grading reads the day's closing price. The
    watchlist sweep used to run here too and now runs in the morning instead —
    see _morning_sweep_job.
    """
    # Weekday-only: US markets are closed Sat/Sun, running would just waste a GPU pass.
    if datetime.datetime.now(datetime.timezone.utc).weekday() >= 5:
        return
    await _evaluate_pending_signals()
    # Written every evening, after grading, so the day's verdicts are in the
    # story rather than a day behind. Each run regenerates the month files
    # from the book, so today lands in the current month's file beside
    # yesterday — a timeline, not a folder of one-day notes.
    try:
        written = await asyncio.to_thread(journey.write_month_files)
        if written:
            log.info("Journey written: %s", ", ".join(written))
    except Exception:
        log.exception("Could not write the journey")


def daily_signals() -> None:
    run_on_main(_daily_signals_job)


async def _morning_sweep_job() -> None:
    """11:00 UTC (07:00 ET): analyse the watchlist before the market opens.

    Moved here from 21:30 UTC, and the reason is news rather than prices. The
    newest completed session is the same one either way — an evening run and
    the next morning's run both reason over yesterday's bar — but an evening
    run at 17:30 ET misses the entire overnight cycle, which is when earnings
    are released. Its signals then sat unchanged until the agent acted on them
    sixteen hours later.

    07:00 rather than closer to the open, for two reasons that have nothing to
    do with GPU time. The pre-open window is already busy — morning_regime at
    12:45 and earnings_check at 13:00, the second of which
    runs its own analyses on the same pool — and a sweep that overran into the
    agent's 13:35 decision would hand it half a picture. This leaves two and a
    half hours of margin for a slow run or a retry.

    Signals recorded before the open are priced at the last completed close
    rather than a pre-market print — see analysis.signal_price.
    """
    if datetime.datetime.now(datetime.timezone.utc).weekday() >= 5:
        return
    if db.get_setting("daily_sweep") == "off":
        return  # event-triggered analyses only (/dailysweep)
    # Dispatched together, not one await at a time: a sequential loop keeps
    # exactly one LLM request in flight regardless of how many backends the
    # Ollama pool has, so every GPU past the first sits idle for the whole
    # sweep. analysis.run_analyses bounds concurrency with the shared semaphore
    # (TRADINGAGENTS_MAX_CONCURRENT_ANALYSES) instead.
    # Delisted and halted tickers are dropped here rather than inside
    # run_analyses: an analysis of something with no market costs minutes of
    # GPU and then cannot even be recorded, because there is no price to record
    # it against.
    inactive = set(listings.inactive_tickers())
    tickers = [t for t in db.get_watchlist() if t not in inactive]
    skipped = sorted(set(db.get_watchlist()) & inactive)
    if skipped:
        log.info("Daily sweep skipping %s — no market data", ", ".join(skipped))
    await analysis.run_analyses(
        tickers,
        on_failure=lambda ticker: notify(f"Daily analysis failed for {ticker} — check the logs."),
    )

    # Then the same tickers through a second model, when one is being
    # evaluated. Chained to this job rather than scheduled separately so the
    # two models always see the same day, the same prices and the same news —
    # a comparison run on its own clock would drift onto a different session
    # and measure the market as much as the model.
def morning_sweep() -> None:
    run_on_main(_morning_sweep_job)


async def _place_queued_exits() -> None:
    """Arm the positions someone queued while the market was shut, and say so."""
    try:
        results = await asyncio.to_thread(agent.process_queued_arms)
    except Exception:
        log.exception("Could not process queued exit arming")
        return
    for result in results:
        icon = "🛡️" if result["ok"] else "⚠️"
        await notify(f"{icon} {result['message']}")


async def _alert_watchdog_job() -> None:
    """Rule-based intraday scan (no LLM): move/volume/stop/target alerts,
    plus event-triggered analyses. Long triggered runs just delay the next
    tick, which doubles as backpressure on the shared GPU."""
    if not watchdog.is_us_market_hours():
        return
    # Before the scan: a resting stop can trigger at any moment, and it is the
    # one fill nobody is waiting for. Settled only when the agent next decided,
    # the book would show a position that had already been sold — for the rest
    # of the day, and into the next morning's decision.
    await _settle_agent_fills()
    # Then the exits someone asked for while the market was shut. First tick
    # after the open drains the queue, which is the whole promise of the button
    # — a request made in the evening and silently dropped would be worse than
    # not offering to remember it.
    await _place_queued_exits()
    try:
        alerts, to_analyze = await asyncio.to_thread(watchdog.scan_for_alerts)
    except Exception:
        log.exception("Alert watchdog scan failed")
        return
    for alert in alerts:
        await notify(alert.message)
    if to_analyze:
        await _run_triggered_analyses(
            {ticker: "Unusual price/volume action" for ticker in to_analyze}
        )


def alert_watchdog() -> None:
    run_on_main(_alert_watchdog_job)


async def _earnings_check_job() -> None:
    """Pre-market (13:00 UTC = 8/9am ET): fresh analysis for tracked tickers
    reporting within the next couple of days."""
    if datetime.datetime.now(datetime.timezone.utc).weekday() >= 5:
        return
    try:
        upcoming = await asyncio.to_thread(watchdog.earnings_tickers_to_analyze)
    except Exception:
        log.exception("Earnings calendar check failed")
        return
    if upcoming:
        await _run_triggered_analyses(
            {
                ticker: (
                    f"{ticker} reports earnings "
                    f"{'today' if earnings_date == datetime.date.today() else f'on {earnings_date}'}"
                )
                for ticker, earnings_date in upcoming
            }
        )


def earnings_check() -> None:
    run_on_main(_earnings_check_job)



async def _morning_regime_job() -> None:
    """Pre-market context post (12:45 UTC, before the earnings task): VIX,
    SPY vs 200-day, yield curve — rule-based, no LLM."""
    if datetime.datetime.now(datetime.timezone.utc).weekday() >= 5:
        return
    try:
        message = regime.format_regime_message(await asyncio.to_thread(regime.fetch_regime))
    except Exception:
        log.exception("Morning regime snapshot failed")
        return
    await notify(message)


def morning_regime() -> None:
    run_on_main(_morning_regime_job)


async def _weekly_digest_job() -> None:
    """Friday 23:00 UTC — after the daily 21:30 sweep has had time to finish."""
    if datetime.datetime.now(datetime.timezone.utc).weekday() != 4:
        return
    try:
        embed = await asyncio.to_thread(build_weekly_digest_embed)
    except Exception:
        log.exception("Weekly digest failed")
        return
    await notify(embed=embed)
    # Once a week, with the digest. Following a ticker costs about seven
    # minutes of GPU on every sweep from then on, so this is a decision to
    # make deliberately rather than a feed to skim daily.
    try:
        found = await asyncio.to_thread(candidates.fetch_candidates)
    except Exception:
        log.exception("Candidate screen failed")
        return


def weekly_digest() -> None:
    run_on_main(_weekly_digest_job)


async def _agent_run_job() -> None:
    """13:35 UTC — 09:35 ET, five minutes after the open.

    Deliberately *not* chained to the 21:30 sweep that produces the signals.
    21:30 UTC is 17:30 ET, ninety minutes after the close, and Webull rejects
    a market order then outright (``CAN_NOT_TRADING_FOR_FIXGW_NOT_READY_NIGHT``).
    An agent wired to run after the sweep would look healthy and never fill a
    single order. So the sweep decides overnight and the agent acts at the next
    open, which is also how the trade would really be placed.

    The five-minute delay past 09:30 lets the opening auction settle, so the
    price the agent is shown is a traded price rather than the first print.
    """
    global _last_agent_run
    if datetime.datetime.now(datetime.timezone.utc).weekday() >= 5:
        return
    if not agent.is_enabled():
        return
    # Shares the cooldown clock with the event-driven path, so a trigger firing
    # minutes after the batch doesn't re-plan a book that just moved.
    _last_agent_run = datetime.datetime.now(datetime.timezone.utc)
    try:
        run = await asyncio.to_thread(agent.run_once)
    except Exception:
        log.exception("Agent decision pass failed")
        return
    # A quiet day is the common case and posting it every morning would train
    # you to ignore the channel. Rejections and broker failures are worth
    # hearing about even when nothing was placed.
    # A note is worth posting even on a day it did nothing else: it is the
    # agent saying it is short of something, which is the point of having it.
    if run.acted or run.rejected or run.failed or run.notes:
        await notify(embed=agent.format_run_embed(run))


def agent_run() -> None:
    run_on_main(_agent_run_job)


def register_jobs() -> None:
    """Registers all 7 scheduled jobs on the shared `scheduler`. Called once
    from backend/app.py's lifespan on every startup — quiv's task state is an
    in-memory/temp-file affair (see quiv's own docs), nothing persists
    across restarts."""
    scheduler.add_task(task_name="alert_watchdog", func=alert_watchdog, interval=900)
    scheduler.add_task(task_name="daily_signals", func=daily_signals, interval=86400, delay=_seconds_until(21, 30))
    scheduler.add_task(task_name="morning_sweep", func=morning_sweep, interval=86400, delay=_seconds_until(11, 0))
    scheduler.add_task(task_name="earnings_check", func=earnings_check, interval=86400, delay=_seconds_until(13, 0))
    scheduler.add_task(task_name="morning_regime", func=morning_regime, interval=86400, delay=_seconds_until(12, 45))
    scheduler.add_task(task_name="weekly_digest", func=weekly_digest, interval=86400, delay=_seconds_until(23, 0))
    scheduler.add_task(task_name="agent_run", func=agent_run, interval=86400, delay=_seconds_until(13, 35))
