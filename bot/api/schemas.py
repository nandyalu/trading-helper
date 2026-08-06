"""Pydantic response models for the web API — an explicit contract decoupled
from the SQLModel table classes and internal dataclasses, so the frontend
gets a stable shape to mirror as TS interfaces regardless of DB schema
changes. Every model uses ``from_attributes`` so a route can validate
directly off a dataclass/SQLModel instance (including dataclass
``@property`` values, which ``from_attributes`` reads via ``getattr`` same
as a plain field) instead of hand-building dicts.
"""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OhlcBarOut(OrmModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class SignalOut(OrmModel):
    id: int
    ticker: str
    signal_date: date
    decision: str
    rationale: str
    time_horizon_text: str | None
    price_target: float | None
    price_at_signal: float
    evaluation_date: date
    price_at_evaluation: float | None
    outcome: str | None
    evaluated_at: datetime | None
    message_id: str | None
    benchmark_price_at_signal: float | None
    benchmark_price_at_evaluation: float | None
    alpha_pct: float | None
    outcome_vs_benchmark: str | None
    price_target_hit: bool | None


class SignalDetailOut(SignalOut):
    reports: dict[str, str] = {}


class PaperPositionOut(OrmModel):
    ticker: str
    quantity: float
    avg_cost: float
    cost_basis: float
    price: float | None
    value: float | None
    unrealized: float | None
    unrealized_pct: float | None


class PaperPortfolioOut(OrmModel):
    positions: list[PaperPositionOut]
    total_value: float
    total_cost: float
    total_unrealized: float
    total_realized: float
    missing_prices: list[str]


class PaperSnapshotOut(OrmModel):
    snapshot_date: date
    open_value: float
    open_cost: float
    realized_pnl: float
    spy_close: float | None


class PortfolioPositionOut(OrmModel):
    ticker: str
    quantity: float
    avg_cost: float
    weight_pct: float | None
    price: float | None
    value: float | None
    unrealized: float | None
    unrealized_pct: float | None


class BenchmarkComparisonOut(OrmModel):
    book_return_pct: float
    benchmark_return_pct: float
    alpha_pct: float


class PortfolioOut(OrmModel):
    positions: list[PortfolioPositionOut]
    total_value: float
    total_cost: float
    total_realized: float
    missing_prices: list[str]
    comparison: BenchmarkComparisonOut | None
    concentration: list[str]


class DecisionStatsOut(OrmModel):
    total: int
    passes: int
    vs_benchmark_total: int
    vs_benchmark_passes: int
    avg_move_pct: float | None


class ScorecardOut(OrmModel):
    resolved: int
    pending: int
    passes: int
    vs_benchmark_total: int
    vs_benchmark_passes: int
    avg_alpha_pct: float | None
    target_total: int
    target_hits: int
    by_decision: dict[str, DecisionStatsOut]
    by_ticker: dict[str, tuple[int, int]]


class TickerSummaryOut(BaseModel):
    ticker: str
    current_price: float | None
    latest_signal: SignalOut | None


class TickerDetailOut(BaseModel):
    ticker: str
    current_price: float | None
    real_position: PortfolioPositionOut | None
    paper_position: PaperPositionOut | None
    latest_signal: SignalOut | None


class AnalyzeQueuedOut(BaseModel):
    status: str = "queued"
    ticker: str


class AnalyzeAllQueuedOut(BaseModel):
    status: str = "queued"
    count: int


class ActionResultOut(BaseModel):
    message: str


class AlertOut(OrmModel):
    id: int
    ticker: str
    alert_type: str
    message: str
    created_at: datetime


class DigestOut(OrmModel):
    week_start: date
    resolved: list[SignalOut]
    new_signals: list[SignalOut]
    alerts: list[AlertOut]
    win_rate_30d: tuple[int, int]
    win_rate_all: tuple[int, int]
    real_book_line: str | None
    paper_lines: list[str]


class RegimeOut(OrmModel):
    as_of: date
    vix: float | None
    spy_price: float | None
    spy_ma200: float | None
    curve_spread_pct: float | None
    spy_vs_ma_pct: float | None
    label: str
    emoji: str


class SettingsOut(BaseModel):
    paper_notional: float
    risk_equity: float | None
    risk_pct: float
    alert_move_pct: float
    alert_stop_pct: float
    alert_volume_mult: float
    alerts_enabled: bool
    daily_sweep_enabled: bool


class SettingsPatchIn(BaseModel):
    paper_notional: float | None = None
    risk_equity: float | None = None
    risk_pct: float | None = None
    alert_move_pct: float | None = None
    alert_stop_pct: float | None = None
    alert_volume_mult: float | None = None
    alerts_enabled: bool | None = None
    daily_sweep_enabled: bool | None = None


class TransactionIn(BaseModel):
    ticker: str
    price: float
    quantity: float


class AskIn(BaseModel):
    question: str
