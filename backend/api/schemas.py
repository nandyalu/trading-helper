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
    horizon: str | None
    model: str | None
    duration_seconds: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    llm_calls: int | None
    entry_price: float | None
    stop_loss: float | None
    win_probability: float | None
    risk_reward: float | None
    expected_value_r: float | None


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
    by_model: dict[str, DecisionStatsOut]
    by_ticker: dict[str, tuple[int, int]]


class TickerSummaryOut(BaseModel):
    ticker: str
    current_price: float | None
    price_updated_at: datetime | None
    latest_signal: SignalOut | None
    # True when the ticker has stopped producing market data (delisted, halted,
    # or simply wrong). Every fetch path skips it, so without saying so the
    # dashboard would just show a stale price and no explanation.
    inactive: bool = False
    inactive_reason: str | None = None


class TickerDetailOut(BaseModel):
    ticker: str
    current_price: float | None
    price_updated_at: datetime | None
    real_position: PortfolioPositionOut | None
    paper_position: PaperPositionOut | None
    latest_signal: SignalOut | None
    inactive: bool = False
    inactive_reason: str | None = None


class TradeOut(BaseModel):
    """A recorded buy or sell, in either book. ``book`` distinguishes them so
    one timeline can carry both without the caller joining two lists."""

    book: str  # "real" | "paper"
    side: str  # "buy" | "sell"
    date: date
    price: float
    quantity: float


class TickerEventsOut(BaseModel):
    """Everything that happened to one ticker, in one call.

    The chart overlays and the timeline below it are the same events drawn two
    ways, so fetching them separately would let the two views disagree while
    one request was still in flight.
    """

    ticker: str
    bars: list[OhlcBarOut]
    signals: list[SignalOut]
    alerts: list[AlertOut]
    trades: list[TradeOut]


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
    horizon: str  # "swing" | "position"
    llm_model: str  # the LLM every analysis runs on
    # Everything the LLM endpoint currently serves. Empty when it couldn't be
    # reached, which the UI shows as a plain text field rather than a dropdown
    # of one — see backend/services/analysis.py list_models().
    llm_model_choices: list[str]
    paper_notional: float
    risk_equity: float | None
    risk_pct: float
    max_position_pct: float
    max_positions: int
    alert_move_pct: float
    alert_stop_pct: float
    alert_volume_mult: float
    alerts_enabled: bool
    daily_sweep_enabled: bool
    agent_enabled: bool
    agent_budget: float


class SettingsPatchIn(BaseModel):
    horizon: str | None = None
    llm_model: str | None = None
    paper_notional: float | None = None
    risk_equity: float | None = None
    risk_pct: float | None = None
    max_position_pct: float | None = None
    max_positions: int | None = None
    alert_move_pct: float | None = None
    alert_stop_pct: float | None = None
    alert_volume_mult: float | None = None
    alerts_enabled: bool | None = None
    daily_sweep_enabled: bool | None = None
    agent_enabled: bool | None = None
    agent_budget: float | None = None


class TransactionIn(BaseModel):
    ticker: str
    price: float
    quantity: float


class AskIn(BaseModel):
    question: str


class AgentHoldingOut(BaseModel):
    ticker: str
    quantity: float
    avg_cost: float
    price: float | None
    market_value: float | None
    cost_basis: float
    unrealized_pnl: float | None


class AgentBookOut(BaseModel):
    enabled: bool
    # False means the app is pointed at production credentials, where the agent
    # refuses to trade at all. The dashboard says so loudly rather than showing
    # an idle agent with no explanation.
    sandbox: bool
    budget: float
    cash: float
    invested: float
    market_value: float
    equity: float
    realized_pnl: float
    return_pct: float
    holdings: list[AgentHoldingOut]


class AgentTradeOut(OrmModel):
    id: int
    ticker: str
    side: str
    quantity: float
    price: float | None  # NULL until the order fills
    placed_at: datetime
    filled_at: datetime | None
    status: str
    reason: str | None
    signal_id: int | None


class AgentOrderOut(BaseModel):
    ticker: str
    side: str
    quantity: float
    reason: str | None = None
    why: str | None = None  # why it was rejected or failed, when it was


class AgentRunOut(BaseModel):
    reasoning: str
    placed: list[AgentOrderOut]
    rejected: list[AgentOrderOut]
    failed: list[AgentOrderOut]


class StrategyOut(OrmModel):
    name: str
    equity: float
    invested: float
    cash: float
    trades: int
    note: str


class AgentComparisonOut(BaseModel):
    """The agent against the two things it could be replaced by. The verdict is
    plain language on purpose — the point is being able to read "switch it off"
    without doing arithmetic."""

    budget: float
    since: date | None
    verdict: str
    strategies: list[StrategyOut]
