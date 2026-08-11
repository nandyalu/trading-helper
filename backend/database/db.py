"""CRUD operations, all going through backend/database/engine.py's read_session/write_session
decorators (retry-on-lock, write-serializing lock).
"""
import datetime

from sqlmodel import Session, func, select

from backend.database.engine import read_session, write_session
from backend.database.models import (
    Alert,
    BotSetting,
    DailyBar,
    PaperSnapshot,
    PaperTransaction,
    Signal,
    SignalReport,
    TickerPrice,
    TickerStatus,
    Transaction,
    WatchlistTicker,
)

# --- Watchlist ---------------------------------------------------------------


@read_session
def get_watchlist(*, _session: Session = None) -> list[str]:
    return [row.ticker for row in _session.exec(select(WatchlistTicker)).all()]


@write_session
def add_to_watchlist(ticker: str, *, _session: Session = None) -> None:
    if _session.get(WatchlistTicker, ticker) is None:
        _session.add(WatchlistTicker(ticker=ticker))
        _session.commit()


@write_session
def remove_from_watchlist(ticker: str, *, _session: Session = None) -> None:
    row = _session.get(WatchlistTicker, ticker)
    if row is not None:
        _session.delete(row)
        _session.commit()


@read_session
def get_all_transaction_tickers(*, _session: Session = None) -> list[str]:
    """Every ticker with at least one recorded buy/sell, not just watchlisted ones."""
    return list(_session.exec(select(Transaction.ticker).distinct()).all())


# --- Settings -----------------------------------------------------------------


@read_session
def get_setting(key: str, *, _session: Session = None) -> str | None:
    row = _session.get(BotSetting, key)
    return row.value if row else None


@write_session
def set_setting(key: str, value: str, *, _session: Session = None) -> None:
    row = _session.get(BotSetting, key)
    if row is None:
        row = BotSetting(key=key, value=value)
    else:
        row.value = value
    _session.add(row)
    _session.commit()


# --- Transactions (feed backend/services/positions.py's compute_position) -----------------


@read_session
def get_transactions(ticker: str, *, _session: Session = None) -> list[dict]:
    rows = _session.exec(
        select(Transaction).where(Transaction.ticker == ticker).order_by(Transaction.date)
    ).all()
    return [
        {
            "side": r.side,
            "date": r.date.isoformat(),
            "price": r.price,
            "quantity": r.quantity,
            "note": r.note,
        }
        for r in rows
    ]


@write_session
def add_transaction(
    ticker: str,
    side: str,
    price: float,
    quantity: float,
    date: datetime.date | None = None,
    note: str | None = None,
    *,
    _session: Session = None,
) -> None:
    """``date`` defaults to today; pass an explicit date to backdate a transaction."""
    _session.add(
        Transaction(
            ticker=ticker,
            side=side,
            date=date or datetime.date.today(),
            price=price,
            quantity=quantity,
            note=note,
        )
    )
    _session.commit()


# --- Signals ------------------------------------------------------------------


@write_session
def record_signal(
    ticker: str,
    decision: str,
    rationale: str,
    price_at_signal: float,
    evaluation_date: datetime.date,
    time_horizon_text: str | None = None,
    price_target: float | None = None,
    message_id: str | None = None,
    horizon: str | None = None,
    model: str | None = None,
    entry_price: float | None = None,
    stop_loss: float | None = None,
    win_probability: float | None = None,
    risk_reward: float | None = None,
    expected_value_r: float | None = None,
    *,
    _session: Session = None,
) -> int:
    """Returns the new signal's id so callers can attach reports to it."""
    row = Signal(
        ticker=ticker,
        signal_date=datetime.date.today(),
        decision=decision,
        rationale=rationale,
        time_horizon_text=time_horizon_text,
        price_target=price_target,
        price_at_signal=price_at_signal,
        evaluation_date=evaluation_date,
        message_id=message_id,
        horizon=horizon,
        model=model,
        entry_price=entry_price,
        stop_loss=stop_loss,
        win_probability=win_probability,
        risk_reward=risk_reward,
        expected_value_r=expected_value_r,
    )
    _session.add(row)
    _session.commit()
    _session.refresh(row)
    return row.id


@read_session
def get_pending_signals(as_of: datetime.date, *, _session: Session = None) -> list[Signal]:
    return list(
        _session.exec(
            select(Signal).where(Signal.evaluation_date <= as_of, Signal.outcome.is_(None))
        ).all()
    )


@write_session
def resolve_signal(
    signal_id: int,
    price_at_evaluation: float,
    outcome: str,
    benchmark_price_at_signal: float | None = None,
    benchmark_price_at_evaluation: float | None = None,
    alpha_pct: float | None = None,
    outcome_vs_benchmark: str | None = None,
    price_target_hit: bool | None = None,
    *,
    _session: Session = None,
) -> None:
    row = _session.get(Signal, signal_id)
    row.price_at_evaluation = price_at_evaluation
    row.outcome = outcome
    row.benchmark_price_at_signal = benchmark_price_at_signal
    row.benchmark_price_at_evaluation = benchmark_price_at_evaluation
    row.alpha_pct = alpha_pct
    row.outcome_vs_benchmark = outcome_vs_benchmark
    row.price_target_hit = price_target_hit
    row.evaluated_at = datetime.datetime.now(datetime.timezone.utc)
    _session.add(row)
    _session.commit()


@read_session
def get_recent_signals(ticker: str | None = None, limit: int = 10, *, _session: Session = None) -> list[Signal]:
    query = select(Signal)
    if ticker:
        query = query.where(Signal.ticker == ticker)
    query = query.order_by(Signal.signal_date.desc()).limit(limit)
    return list(_session.exec(query).all())


@read_session
def get_signal_by_message_id(message_id: str, *, _session: Session = None) -> Signal | None:
    return _session.exec(select(Signal).where(Signal.message_id == message_id)).first()


@read_session
def get_signal(signal_id: int, *, _session: Session = None) -> Signal | None:
    return _session.get(Signal, signal_id)


@read_session
def get_resolved_signals(ticker: str | None = None, *, _session: Session = None) -> list[Signal]:
    query = select(Signal).where(Signal.outcome.is_not(None))
    if ticker:
        query = query.where(Signal.ticker == ticker)
    return list(_session.exec(query.order_by(Signal.signal_date)).all())


@read_session
def count_pending_signals(ticker: str | None = None, *, _session: Session = None) -> int:
    query = select(Signal).where(Signal.outcome.is_(None))
    if ticker:
        query = query.where(Signal.ticker == ticker)
    return len(_session.exec(query).all())


# --- Paper transactions (virtual portfolio, same FIFO math as real ones) ------


@write_session
def add_paper_transaction(
    ticker: str,
    side: str,
    price: float,
    quantity: float,
    signal_id: int | None = None,
    note: str | None = None,
    *,
    _session: Session = None,
) -> None:
    _session.add(
        PaperTransaction(
            ticker=ticker,
            side=side,
            date=datetime.date.today(),
            price=price,
            quantity=quantity,
            signal_id=signal_id,
            note=note,
        )
    )
    _session.commit()


@read_session
def get_paper_transactions(ticker: str, *, _session: Session = None) -> list[dict]:
    rows = _session.exec(
        select(PaperTransaction)
        .where(PaperTransaction.ticker == ticker)
        .order_by(PaperTransaction.date, PaperTransaction.id)
    ).all()
    return [
        {"side": r.side, "date": r.date.isoformat(), "price": r.price, "quantity": r.quantity}
        for r in rows
    ]


@read_session
def get_all_paper_tickers(*, _session: Session = None) -> list[str]:
    return list(_session.exec(select(PaperTransaction.ticker).distinct()).all())


@read_session
def has_paper_transaction_for_signal(signal_id: int, *, _session: Session = None) -> bool:
    return (
        _session.exec(
            select(PaperTransaction).where(PaperTransaction.signal_id == signal_id)
        ).first()
        is not None
    )


# --- Signal reports (full analyst text, feeds /ask) ---------------------------


@write_session
def add_signal_reports(signal_id: int, reports: dict[str, str], *, _session: Session = None) -> None:
    for report_type, content in reports.items():
        _session.add(SignalReport(signal_id=signal_id, report_type=report_type, content=content))
    _session.commit()


@read_session
def get_signal_reports(signal_id: int, *, _session: Session = None) -> dict[str, str]:
    rows = _session.exec(
        select(SignalReport).where(SignalReport.signal_id == signal_id)
    ).all()
    return {row.report_type: row.content for row in rows}


# --- Paper snapshots (equity curve) --------------------------------------------


@write_session
def record_paper_snapshot(
    snapshot_date: datetime.date,
    open_value: float,
    open_cost: float,
    realized_pnl: float,
    spy_close: float | None,
    *,
    _session: Session = None,
) -> None:
    """Upsert on date — a same-day re-run (bot restart) refreshes the row."""
    row = _session.exec(
        select(PaperSnapshot).where(PaperSnapshot.snapshot_date == snapshot_date)
    ).first()
    if row is None:
        row = PaperSnapshot(
            snapshot_date=snapshot_date,
            open_value=open_value,
            open_cost=open_cost,
            realized_pnl=realized_pnl,
            spy_close=spy_close,
        )
    else:
        row.open_value = open_value
        row.open_cost = open_cost
        row.realized_pnl = realized_pnl
        row.spy_close = spy_close
    _session.add(row)
    _session.commit()


@read_session
def get_paper_snapshots(limit: int = 90, *, _session: Session = None) -> list[PaperSnapshot]:
    """Most recent ``limit`` snapshots, returned oldest-first for charting."""
    rows = _session.exec(
        select(PaperSnapshot).order_by(PaperSnapshot.snapshot_date.desc()).limit(limit)
    ).all()
    return list(reversed(rows))


# --- Ticker status (delisted / halted symbols, see services/listings.py) -----


@read_session
def get_ticker_status(ticker: str, *, _session: Session = None) -> TickerStatus | None:
    return _session.get(TickerStatus, ticker)


@read_session
def get_inactive_tickers(*, _session: Session = None) -> list[TickerStatus]:
    return list(_session.exec(select(TickerStatus).where(TickerStatus.inactive.is_(True))).all())


@write_session
def set_ticker_status(
    ticker: str,
    inactive: bool | None = None,
    reason: str | None = None,
    last_bar_date: datetime.date | None = None,
    manual: bool | None = None,
    *,
    _session: Session = None,
) -> None:
    """Upsert. Only the fields passed are changed, so a detection pass can
    update freshness without clearing a manual override, and vice versa.
    ``checked_at`` is always stamped — the point of a check is that it
    happened, whatever it found."""
    row = _session.get(TickerStatus, ticker) or TickerStatus(ticker=ticker)
    if inactive is not None:
        row.inactive = inactive
        row.reason = reason
    if last_bar_date is not None:
        row.last_bar_date = last_bar_date
    if manual is not None:
        row.manual = manual
    row.checked_at = datetime.datetime.now(datetime.timezone.utc)
    _session.add(row)
    _session.commit()


# --- Daily bar cache (every yfinance history read goes through this) ---------


@read_session
def get_daily_bars(
    ticker: str,
    start: datetime.date,
    end: datetime.date | None = None,
    *,
    _session: Session = None,
) -> list[DailyBar]:
    """Cached bars in [start, end], oldest first. ``end`` defaults to open-ended."""
    query = select(DailyBar).where(DailyBar.ticker == ticker, DailyBar.date >= start)
    if end is not None:
        query = query.where(DailyBar.date <= end)
    return list(_session.exec(query.order_by(DailyBar.date)).all())


@read_session
def get_bar_coverage(
    ticker: str, *, _session: Session = None
) -> tuple[datetime.date | None, datetime.date | None]:
    """(oldest, newest) cached dates for a ticker, (None, None) when empty.
    Callers use this to decide whether a fetch is needed at all."""
    row = _session.exec(
        select(func.min(DailyBar.date), func.max(DailyBar.date)).where(DailyBar.ticker == ticker)
    ).one()
    return (row[0], row[1]) if row else (None, None)


@write_session
def upsert_daily_bars(ticker: str, bars: list[dict], *, _session: Session = None) -> int:
    """Insert or replace bars. ``bars`` items carry date/open/high/low/close/volume.

    Replacing rather than skipping duplicates matters: a bar fetched moments
    after the close can be revised by the exchange, and the later fetch is the
    better one."""
    written = 0
    for bar in bars:
        row = _session.get(DailyBar, (ticker, bar["date"]))
        if row is None:
            row = DailyBar(ticker=ticker, **bar)
        else:
            for field in ("open", "high", "low", "close", "volume"):
                setattr(row, field, bar[field])
        _session.add(row)
        written += 1
    _session.commit()
    return written


# --- Ticker price cache (dashboard reads; written by every live quote fetch) --


@read_session
def get_cached_price(ticker: str, *, _session: Session = None) -> TickerPrice | None:
    return _session.get(TickerPrice, ticker)


@read_session
def get_cached_prices(tickers: list[str], *, _session: Session = None) -> dict[str, TickerPrice]:
    rows = _session.exec(select(TickerPrice).where(TickerPrice.ticker.in_(tickers))).all()
    return {row.ticker: row for row in rows}


@write_session
def set_cached_price(
    ticker: str, price: float, source: str | None = None, *, _session: Session = None
) -> None:
    """Upsert on ticker — called by every live quote fetch, not just the
    frontend's manual refresh, so the cache builds up passively over time."""
    row = _session.get(TickerPrice, ticker)
    if row is None:
        row = TickerPrice(ticker=ticker, price=price, fetched_at=datetime.datetime.now(datetime.timezone.utc), source=source)
    else:
        row.price = price
        row.fetched_at = datetime.datetime.now(datetime.timezone.utc)
        row.source = source
    _session.add(row)
    _session.commit()


# --- Watchdog alerts + trigger dedupe ------------------------------------------


@read_session
def has_signal_today(ticker: str, *, _session: Session = None) -> bool:
    """Used to stop event triggers from re-analyzing a ticker the same day."""
    return (
        _session.exec(
            select(Signal).where(Signal.ticker == ticker, Signal.signal_date == datetime.date.today())
        ).first()
        is not None
    )


@read_session
def get_latest_signal_with_target(ticker: str, *, _session: Session = None) -> Signal | None:
    return _session.exec(
        select(Signal)
        .where(Signal.ticker == ticker, Signal.price_target.is_not(None))
        .order_by(Signal.signal_date.desc(), Signal.id.desc())
    ).first()


@read_session
def get_latest_signal_with_stop(ticker: str, *, _session: Session = None) -> Signal | None:
    """Newest signal that named a stop-loss level. The newest one is the
    current thesis, so its stop is the one still worth watching — an older
    signal's stop was superseded, not merely graded."""
    return _session.exec(
        select(Signal)
        .where(Signal.ticker == ticker, Signal.stop_loss.is_not(None))
        .order_by(Signal.signal_date.desc(), Signal.id.desc())
    ).first()


@read_session
def get_signals_created_since(since: datetime.date, *, _session: Session = None) -> list[Signal]:
    return list(
        _session.exec(
            select(Signal).where(Signal.signal_date >= since).order_by(Signal.signal_date)
        ).all()
    )


@read_session
def get_recent_alerts(limit: int = 200, *, _session: Session = None) -> list[Alert]:
    return list(_session.exec(select(Alert).order_by(Alert.id.desc()).limit(limit)).all())


@read_session
def alert_already_sent(dedupe_key: str, *, _session: Session = None) -> bool:
    return _session.exec(select(Alert).where(Alert.dedupe_key == dedupe_key)).first() is not None


@write_session
def record_alert(
    ticker: str, alert_type: str, dedupe_key: str, message: str, *, _session: Session = None
) -> None:
    _session.add(
        Alert(
            ticker=ticker,
            alert_type=alert_type,
            dedupe_key=dedupe_key,
            message=message,
            created_at=datetime.datetime.now(datetime.timezone.utc),
        )
    )
    _session.commit()
