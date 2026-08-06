"""Intraday alert watchdog and event-driven analysis triggers — all
rule-based, no LLM involved. ``scan_for_alerts`` does one pass over every
tracked ticker (watchlist ∪ open real positions ∪ open paper positions),
alerting on big daily moves, unusual volume, stop-level breaches, and
price-target touches; big moves and volume spikes also nominate the ticker
for an immediate TradingAgents run. ``earnings_tickers_to_analyze`` feeds the
separate pre-market earnings task.

Sent alerts are recorded in the ``alert`` table keyed by ``dedupe_key`` so a
15-minute loop never repeats itself (per ticker per day for moves/volume/
stops, once ever per signal for targets). Everything here is blocking
(yfinance + DB) — call via asyncio.to_thread.
"""
import datetime
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import yfinance as yf
from tradingagents.dataflows.stockstats_utils import yf_retry

from backend.database import db
from backend.database.models import Signal
from backend.services.positions import Position, compute_position
from backend.services.signals import price_crossed_target

US_MARKET_TZ = ZoneInfo("America/New_York")
_MARKET_OPEN = datetime.time(9, 30)
_MARKET_CLOSE = datetime.time(16, 0)

EARNINGS_LOOKAHEAD_DAYS = 2


def is_us_market_hours(now: datetime.datetime | None = None) -> bool:
    """Regular NYSE session, weekdays 9:30–16:00 ET. Holidays aren't modeled —
    on those days the stale-bar guard in scan_for_alerts keeps things quiet."""
    now = (now or datetime.datetime.now(US_MARKET_TZ)).astimezone(US_MARKET_TZ)
    if now.weekday() >= 5:
        return False
    return _MARKET_OPEN <= now.time() <= _MARKET_CLOSE


# --- Config (BotSetting-backed, see /alertconfig) ------------------------------


@dataclass
class AlertConfig:
    move_pct: float = 5.0  # abs daily % move that alerts + triggers an analysis
    stop_pct: float = 10.0  # % below avg cost that fires a stop alert
    volume_mult: float = 2.0  # today's volume vs 20-day average
    enabled: bool = True


_SETTING_KEYS = {"move_pct": "alert_move_pct", "stop_pct": "alert_stop_pct", "volume_mult": "alert_volume_mult"}


def load_config() -> AlertConfig:
    config = AlertConfig()
    for attr, key in _SETTING_KEYS.items():
        raw = db.get_setting(key)
        if raw:
            try:
                setattr(config, attr, float(raw))
            except ValueError:
                pass  # ignore a corrupt setting, keep the default
    config.enabled = db.get_setting("alerts_enabled") != "off"
    return config


# --- Market data ----------------------------------------------------------------


@dataclass
class DailySnapshot:
    price: float  # latest close (the running bar during market hours)
    prev_close: float
    day_change_pct: float
    last_bar_date: datetime.date
    today_volume: float
    avg_volume: float  # mean of the earlier bars in the ~1-month window


def get_daily_snapshot(ticker: str) -> DailySnapshot | None:
    """Best-effort like get_current_price — None on empty/failed fetch."""
    try:
        history = yf_retry(lambda: yf.Ticker(ticker).history(period="1mo"))
        if len(history) < 2:
            return None
        price = float(history["Close"].iloc[-1])
        prev_close = float(history["Close"].iloc[-2])
        return DailySnapshot(
            price=price,
            prev_close=prev_close,
            day_change_pct=(price / prev_close - 1) * 100 if prev_close else 0.0,
            last_bar_date=history.index[-1].date(),
            today_volume=float(history["Volume"].iloc[-1]),
            avg_volume=float(history["Volume"].iloc[:-1].mean()),
        )
    except Exception:
        return None


# --- Alert evaluation (pure) ------------------------------------------------------


@dataclass
class AlertCandidate:
    ticker: str
    alert_type: str  # "big_move" | "volume" | "stop_loss" | "target"
    dedupe_key: str
    message: str
    trigger_analysis: bool = False


def evaluate_ticker(
    ticker: str,
    snapshot: DailySnapshot,
    real_position: Position | None,
    paper_position: Position | None,
    target_signal: Signal | None,
    config: AlertConfig,
    today: datetime.date,
) -> list[AlertCandidate]:
    alerts: list[AlertCandidate] = []

    if abs(snapshot.day_change_pct) >= config.move_pct:
        alerts.append(
            AlertCandidate(
                ticker,
                "big_move",
                f"big_move:{ticker}:{today}",
                f"📊 {ticker} moved {snapshot.day_change_pct:+.1f}% today "
                f"(${snapshot.prev_close:,.2f} → ${snapshot.price:,.2f}).",
                trigger_analysis=True,
            )
        )

    if snapshot.avg_volume > 0 and snapshot.today_volume >= config.volume_mult * snapshot.avg_volume:
        alerts.append(
            AlertCandidate(
                ticker,
                "volume",
                f"volume:{ticker}:{today}",
                f"📊 {ticker} volume is {snapshot.today_volume / snapshot.avg_volume:.1f}× "
                f"its 20-day average.",
                trigger_analysis=True,
            )
        )

    stop_hits = []
    for label, position in (("real", real_position), ("paper", paper_position)):
        if position is not None and position.quantity > 0 and position.avg_cost > 0:
            drop_pct = (1 - snapshot.price / position.avg_cost) * 100
            if drop_pct >= config.stop_pct:
                stop_hits.append(f"{label} avg cost ${position.avg_cost:,.2f} (−{drop_pct:.1f}%)")
    if stop_hits:
        alerts.append(
            AlertCandidate(
                ticker,
                "stop_loss",
                f"stop:{ticker}:{today}",
                f"🛑 {ticker} at ${snapshot.price:,.2f} is over {config.stop_pct:g}% below your "
                + " and ".join(stop_hits)
                + ".",
            )
        )

    held = any(p is not None and p.quantity > 0 for p in (real_position, paper_position))
    if (
        held
        and target_signal is not None
        and target_signal.price_target
        and price_crossed_target(
            target_signal.price_target, target_signal.price_at_signal, high=snapshot.price, low=snapshot.price
        )
    ):
        alerts.append(
            AlertCandidate(
                ticker,
                "target",
                f"target:{target_signal.id}",
                f"🎯 {ticker} reached the ${target_signal.price_target:,.2f} target from the "
                f"{target_signal.decision} signal of {target_signal.signal_date} "
                f"(now ${snapshot.price:,.2f}).",
            )
        )

    return alerts


# --- Orchestration (blocking) ------------------------------------------------------


def _tracked_tickers() -> list[str]:
    """Watchlist plus anything actually held, in either book."""
    tickers = set(db.get_watchlist())
    for ticker in db.get_all_transaction_tickers():
        if compute_position(db.get_transactions(ticker)).quantity > 0:
            tickers.add(ticker)
    for ticker in db.get_all_paper_tickers():
        if compute_position(db.get_paper_transactions(ticker)).quantity > 0:
            tickers.add(ticker)
    return sorted(tickers)


def scan_for_alerts() -> tuple[list[AlertCandidate], list[str]]:
    """One watchdog pass. Returns (fresh alerts, tickers to analyze now).
    Alerts are recorded before being returned, so a crash between recording
    and sending drops an alert rather than ever repeating one."""
    config = load_config()
    if not config.enabled:
        return [], []
    today = datetime.datetime.now(US_MARKET_TZ).date()
    fresh: list[AlertCandidate] = []
    to_analyze: list[str] = []

    for ticker in _tracked_tickers():
        snapshot = get_daily_snapshot(ticker)
        if snapshot is None or snapshot.last_bar_date != today:
            continue  # no fresh bar (fetch failed, holiday) — never alert on stale closes
        real_position = compute_position(db.get_transactions(ticker))
        paper_position = compute_position(db.get_paper_transactions(ticker))
        target_signal = db.get_latest_signal_with_target(ticker)
        for candidate in evaluate_ticker(
            ticker, snapshot, real_position, paper_position, target_signal, config, today
        ):
            if db.alert_already_sent(candidate.dedupe_key):
                continue
            db.record_alert(candidate.ticker, candidate.alert_type, candidate.dedupe_key, candidate.message)
            fresh.append(candidate)
            if candidate.trigger_analysis and ticker not in to_analyze and not db.has_signal_today(ticker):
                to_analyze.append(ticker)

    return fresh, to_analyze


# --- Earnings trigger ---------------------------------------------------------------


def get_next_earnings_date(ticker: str) -> datetime.date | None:
    try:
        calendar = yf_retry(lambda: yf.Ticker(ticker).calendar)
        if not isinstance(calendar, dict):
            return None
        today = datetime.date.today()
        upcoming = sorted(
            entry.date() if isinstance(entry, datetime.datetime) else entry
            for entry in (calendar.get("Earnings Date") or [])
            if isinstance(entry, datetime.date)
        )
        upcoming = [d for d in upcoming if d >= today]
        return upcoming[0] if upcoming else None
    except Exception:
        return None


def earnings_tickers_to_analyze() -> list[tuple[str, datetime.date]]:
    """Tracked tickers reporting within EARNINGS_LOOKAHEAD_DAYS that haven't
    been analyzed today. Re-nominates each day inside the window on purpose —
    a fresh read the day before and the day of the report."""
    results = []
    today = datetime.date.today()
    for ticker in _tracked_tickers():
        if db.has_signal_today(ticker):
            continue
        next_date = get_next_earnings_date(ticker)
        if next_date is not None and (next_date - today).days <= EARNINGS_LOOKAHEAD_DAYS:
            results.append((ticker, next_date))
    return results
