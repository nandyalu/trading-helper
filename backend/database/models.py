"""SQLModel table definitions. Alembic (backend/database/alembic/) owns schema migrations —
tables are never created via ``SQLModel.metadata.create_all`` at runtime.
"""
import datetime

from sqlmodel import Field, SQLModel


class WatchlistTicker(SQLModel, table=True):
    ticker: str = Field(primary_key=True)


class BotSetting(SQLModel, table=True):
    """Generic key/value store — covers channel_id and anything added later
    without a schema change."""

    key: str = Field(primary_key=True)
    value: str


class Transaction(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    side: str  # "buy" | "sell"
    date: datetime.date
    price: float
    quantity: float
    note: str | None = None  # provenance, e.g. "webull sync" — manual entries stay NULL


class Signal(SQLModel, table=True):
    """One row per completed TradingAgents analysis. ``outcome`` stays NULL
    until ``evaluation_date`` has passed and a follow-up price is fetched.

    ``message_id`` is the Discord message the analysis embed was posted as —
    reacting ✅ to that message executes the signal as a paper trade.
    Benchmark fields are filled at evaluation time alongside ``outcome``;
    they stay NULL on rows resolved before the columns existed or when the
    SPY window couldn't be fetched.
    """

    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    signal_date: datetime.date
    decision: str
    rationale: str
    time_horizon_text: str | None = None
    price_target: float | None = None
    price_at_signal: float
    evaluation_date: datetime.date = Field(index=True)
    price_at_evaluation: float | None = None
    outcome: str | None = None  # "pass" | "fail"
    evaluated_at: datetime.datetime | None = None
    message_id: str | None = Field(default=None, index=True)
    benchmark_price_at_signal: float | None = None
    benchmark_price_at_evaluation: float | None = None
    alpha_pct: float | None = None  # ticker % move − benchmark % move over the window
    outcome_vs_benchmark: str | None = None  # "pass" | "fail"
    price_target_hit: bool | None = None  # price touched the target within the window


class SignalReport(SQLModel, table=True):
    """Full analyst/researcher text attached to a signal (market, news,
    sentiment, fundamentals reports, investment plans) — the raw material for
    /ask and post-mortems. One row per (signal, report_type)."""

    id: int | None = Field(default=None, primary_key=True)
    signal_id: int = Field(foreign_key="signal.id", index=True)
    report_type: str  # final_state key, e.g. "market_report"
    content: str


class PaperSnapshot(SQLModel, table=True):
    """End-of-day valuation of the paper book, recorded by the daily task —
    the series behind the equity curve in /paper. One row per day (re-runs
    the same day overwrite)."""

    id: int | None = Field(default=None, primary_key=True)
    snapshot_date: datetime.date = Field(unique=True, index=True)
    open_value: float  # market value of open positions (priced tickers only)
    open_cost: float  # cost basis of the same positions
    realized_pnl: float  # cumulative, across all paper tickers
    spy_close: float | None = None  # for the buy-and-hold comparison


class Alert(SQLModel, table=True):
    """Sent-alert log for the intraday watchdog. ``dedupe_key`` is what stops
    a 15-minute loop from repeating itself: per ticker per day for
    moves/volume/stops, once ever per signal for target touches.
    """

    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    alert_type: str  # "big_move" | "volume" | "stop_loss" | "target"
    dedupe_key: str = Field(unique=True, index=True)
    message: str
    created_at: datetime.datetime


class PaperTransaction(SQLModel, table=True):
    """Virtual buy/sell log for signals the user chose to follow (via ✅
    reaction or /paperclose). Same shape as ``Transaction`` so the FIFO math
    in backend/services/positions.py works on both; ``signal_id`` links an entry back to
    the signal that produced it (and dedupes repeat reactions).
    """

    id: int | None = Field(default=None, primary_key=True)
    ticker: str = Field(index=True)
    side: str  # "buy" | "sell"
    date: datetime.date
    price: float
    quantity: float
    signal_id: int | None = Field(default=None, foreign_key="signal.id")
    note: str | None = None
