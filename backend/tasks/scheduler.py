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
from backend.services import analysis, broker, listings, paper, regime, watchdog
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
    """``reasons`` maps ticker to why it was triggered. Announces each, then
    runs them together — the shared semaphore is the backpressure, not this
    function, so several triggered tickers use several GPUs instead of queueing
    behind each other."""
    for ticker, reason in reasons.items():
        await notify(f"⚡ {reason} — running an analysis of {ticker}...")
    await analysis.run_analyses(
        list(reasons),
        on_failure=lambda ticker: notify(f"Triggered analysis failed for {ticker} — check the logs."),
    )


async def _daily_signals_job() -> None:
    # Weekday-only: US markets are closed Sat/Sun, running would just waste a GPU pass.
    if datetime.datetime.now(datetime.timezone.utc).weekday() >= 5:
        return
    await _evaluate_pending_signals()
    try:
        await asyncio.to_thread(paper.record_daily_snapshot)  # equity-curve point for /paper
    except Exception:
        log.exception("Paper snapshot failed")
    if db.get_setting("daily_sweep") == "off":
        return  # event-triggered analyses only (/dailysweep); evaluation above still ran
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


def daily_signals() -> None:
    run_on_main(_daily_signals_job)


async def _alert_watchdog_job() -> None:
    """Rule-based intraday scan (no LLM): move/volume/stop/target alerts,
    plus event-triggered analyses. Long triggered runs just delay the next
    tick, which doubles as backpressure on the shared GPU."""
    if not watchdog.is_us_market_hours():
        return
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


async def _broker_sync_job() -> None:
    """Pre-market (before regime/earnings): mirror Webull holdings into the
    watchlist and position log so today's analyses cover everything held.
    Posts only when something changed."""
    if datetime.datetime.now(datetime.timezone.utc).weekday() >= 5:
        return
    if not broker.is_configured():
        return
    try:
        summary = await asyncio.to_thread(broker.run_sync)
    except Exception:
        log.exception("Webull sync failed")
        return
    if summary is None or "Everything already in sync" in summary:
        return
    await notify(summary)


def broker_sync() -> None:
    run_on_main(_broker_sync_job)


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


def weekly_digest() -> None:
    run_on_main(_weekly_digest_job)


def register_jobs() -> None:
    """Registers all 6 scheduled jobs on the shared `scheduler`. Called once
    from backend/app.py's lifespan on every startup — quiv's task state is an
    in-memory/temp-file affair (see quiv's own docs), nothing persists
    across restarts."""
    scheduler.add_task(task_name="alert_watchdog", func=alert_watchdog, interval=900)
    scheduler.add_task(task_name="daily_signals", func=daily_signals, interval=86400, delay=_seconds_until(21, 30))
    scheduler.add_task(task_name="earnings_check", func=earnings_check, interval=86400, delay=_seconds_until(13, 0))
    scheduler.add_task(task_name="broker_sync", func=broker_sync, interval=86400, delay=_seconds_until(12, 35))
    scheduler.add_task(task_name="morning_regime", func=morning_regime, interval=86400, delay=_seconds_until(12, 45))
    scheduler.add_task(task_name="weekly_digest", func=weekly_digest, interval=86400, delay=_seconds_until(23, 0))
