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

    ``horizon`` records which trade horizon the run used ("swing" or
    "position", see backend/services/signals.py HORIZONS). It decides how long
    to wait before grading and how wide the Hold band is, so a scorecard that
    mixed horizons would be comparing two different questions. NULL means a row
    predating the column.

    The trade-plan fields (``entry_price`` through ``expected_value_r``) come
    from the trader stage rather than the final decision text — see
    backend/services/signals.py. They are the exit level and the quality of the
    bet, which the portfolio manager's own output doesn't carry. All nullable:
    NULL means "the model didn't state it", never zero, so a missing stop can
    never be read as a stop at $0.
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
    horizon: str | None = Field(default=None, index=True)  # "swing" | "position"
    entry_price: float | None = None  # the level the trader proposed entering at
    stop_loss: float | None = None  # the level at which the thesis is wrong
    win_probability: float | None = None  # 0-100, the model's own estimate
    risk_reward: float | None = None  # reward ÷ risk, computed from entry/stop/target
    expected_value_r: float | None = None  # p×rr − (1−p), in R-multiples; signed


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


class TickerStatus(SQLModel, table=True):
    """Tickers that have stopped producing market data, so every fetch path can
    skip them instead of asking again.

    A delisted symbol does not fail cleanly. yfinance keeps answering for the
    shell — AILEQ returned five bars in two months, all at $0.000001 — which
    looks to a cache like a ticker that is merely behind, so it refetches
    forever. The daily sweep meanwhile spends minutes of GPU analyzing
    something that no longer trades.

    ``inactive`` is set automatically once no fresh bar has appeared for
    ``STALE_AFTER_TRADING_DAYS`` (see backend/services/listings.py), and cleared
    if the ticker ever produces one again — a halt can lift, and a manual
    override should not be needed for that. ``checked_at`` throttles the
    once-a-day recheck that makes recovery possible.
    """

    ticker: str = Field(primary_key=True)
    inactive: bool = False
    reason: str | None = None
    # Last bar seen, and when we last asked. Both NULL until the first check.
    last_bar_date: datetime.date | None = None
    checked_at: datetime.datetime | None = None
    # Set by a person, and never overwritten by detection. Lets a ticker be
    # force-ignored (or force-kept) when the heuristic gets it wrong.
    manual: bool = False


class DailyBar(SQLModel, table=True):
    """Cached daily OHLCV, one row per (ticker, date).

    Only *completed* sessions are stored. A bar for the day in progress keeps
    changing, so caching it would serve a frozen mid-session snapshot as though
    it were a close — see backend/services/bars.py.

    Every yfinance history call in the app reads through this table. Before it
    existed the intraday watchdog refetched roughly a month of bars per ticker
    every 15 minutes to use two closes and a volume average, and the chart, the
    ATR, and signal grading each fetched the same bars again independently.
    Past bars never change, so refetching them is pure waste and pure
    rate-limit risk.
    """

    ticker: str = Field(primary_key=True)
    date: datetime.date = Field(primary_key=True)
    open: float
    high: float
    low: float
    close: float
    volume: float


class TickerPrice(SQLModel, table=True):
    """Last-known price cache, one row per ticker. Dashboard reads (the
    ticker list/detail routes) serve from this table instead of a live quote
    call. Every live fetch anywhere in the app (get_current_price, the
    watchdog's daily snapshot, the frontend's manual refresh) writes its
    result here, so the cache builds up passively over time."""

    ticker: str = Field(primary_key=True)
    price: float
    fetched_at: datetime.datetime
    source: str | None = None  # "webull" | "yfinance", for debugging


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
