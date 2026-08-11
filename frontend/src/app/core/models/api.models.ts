// Mirrors bot/api/schemas.py field-for-field, including the snake_case
// naming — kept as-is (no camelCase translation layer) since the API is
// same-origin, internal-only, and a mapping layer would add nothing here.

export interface OhlcBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface Signal {
  id: number;
  ticker: string;
  signal_date: string;
  decision: string;
  rationale: string;
  time_horizon_text: string | null;
  price_target: number | null;
  price_at_signal: number;
  evaluation_date: string;
  price_at_evaluation: number | null;
  outcome: 'pass' | 'fail' | null;
  evaluated_at: string | null;
  message_id: string | null;
  benchmark_price_at_signal: number | null;
  benchmark_price_at_evaluation: number | null;
  alpha_pct: number | null;
  outcome_vs_benchmark: 'pass' | 'fail' | null;
  price_target_hit: boolean | null;
  horizon: string | null; // "swing" | "position"
  model: string | null; // the LLM that produced it; null on rows predating the column
  // What the run cost. Null means it wasn't measured, never that it was free.
  duration_seconds: number | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  llm_calls: number | null;
  // The trade plan, from TradingAgents' trader stage. Null means the model did
  // not state it — never zero.
  entry_price: number | null;
  stop_loss: number | null;
  win_probability: number | null; // 0-100
  risk_reward: number | null;
  expected_value_r: number | null; // signed, in R-multiples
}

export interface SignalDetail extends Signal {
  reports: Record<string, string>;
}

export interface PaperPosition {
  ticker: string;
  quantity: number;
  avg_cost: number;
  cost_basis: number;
  price: number | null;
  value: number | null;
  unrealized: number | null;
  unrealized_pct: number | null;
}

export interface PaperPortfolio {
  positions: PaperPosition[];
  total_value: number;
  total_cost: number;
  total_unrealized: number;
  total_realized: number;
  missing_prices: string[];
}

export interface PaperSnapshot {
  snapshot_date: string;
  open_value: number;
  open_cost: number;
  realized_pnl: number;
  spy_close: number | null;
}

export interface PortfolioPosition {
  ticker: string;
  quantity: number;
  avg_cost: number;
  weight_pct: number | null;
  price: number | null;
  value: number | null;
  unrealized: number | null;
  unrealized_pct: number | null;
}

export interface BenchmarkComparison {
  book_return_pct: number;
  benchmark_return_pct: number;
  alpha_pct: number;
}

export interface Portfolio {
  positions: PortfolioPosition[];
  total_value: number;
  total_cost: number;
  total_realized: number;
  missing_prices: string[];
  comparison: BenchmarkComparison | null;
  concentration: string[];
}

export interface DecisionStats {
  total: number;
  passes: number;
  vs_benchmark_total: number;
  vs_benchmark_passes: number;
  avg_move_pct: number | null;
}

export interface Scorecard {
  resolved: number;
  pending: number;
  passes: number;
  vs_benchmark_total: number;
  vs_benchmark_passes: number;
  avg_alpha_pct: number | null;
  target_total: number;
  target_hits: number;
  by_decision: Record<string, DecisionStats>;
  by_model: Record<string, DecisionStats>;
  by_ticker: Record<string, [number, number]>;
}

export interface TickerSummary {
  ticker: string;
  current_price: number | null;
  price_updated_at: string | null;
  latest_signal: Signal | null;
  /** No market data any more — delisted, halted, or a wrong symbol. Every
   * fetch path skips it, so the UI has to say why the price is stale. */
  inactive: boolean;
  inactive_reason: string | null;
}

export interface TickerDetail {
  ticker: string;
  current_price: number | null;
  price_updated_at: string | null;
  real_position: PortfolioPosition | null;
  paper_position: PaperPosition | null;
  latest_signal: Signal | null;
  inactive: boolean;
  inactive_reason: string | null;
}

export interface AnalyzeQueued {
  status: string;
  ticker: string;
}

export interface AnalyzeAllQueued {
  status: string;
  count: number;
}

export interface ActionResult {
  message: string;
}

export interface Alert {
  id: number;
  ticker: string;
  alert_type: string;
  message: string;
  created_at: string;
}

export interface Trade {
  book: 'real' | 'paper';
  side: 'buy' | 'sell';
  date: string;
  price: number;
  quantity: number;
}

/** Everything that happened to one ticker, from GET /api/tickers/{t}/events.
 * The chart overlays and the timeline are this same data drawn two ways. */
export interface TickerEvents {
  ticker: string;
  bars: OhlcBar[];
  signals: Signal[];
  alerts: Alert[];
  trades: Trade[];
}

export interface Digest {
  week_start: string;
  resolved: Signal[];
  new_signals: Signal[];
  alerts: Alert[];
  win_rate_30d: [number, number];
  win_rate_all: [number, number];
  real_book_line: string | null;
  paper_lines: string[];
}

export interface Regime {
  as_of: string;
  vix: number | null;
  spy_price: number | null;
  spy_ma200: number | null;
  curve_spread_pct: number | null;
  spy_vs_ma_pct: number | null;
  label: string;
  emoji: string;
}

export interface Settings {
  horizon: string; // "swing" | "position"
  llm_model: string;
  /** Everything the LLM endpoint serves. Empty when it couldn't be reached —
   * the settings page then falls back to a text field. Read-only: it isn't
   * part of SettingsPatch. */
  llm_model_choices: string[];
  paper_notional: number;
  risk_equity: number | null;
  risk_pct: number;
  max_position_pct: number;
  max_positions: number;
  alert_move_pct: number;
  alert_stop_pct: number;
  alert_volume_mult: number;
  alerts_enabled: boolean;
  daily_sweep_enabled: boolean;
  agent_enabled: boolean;
  agent_budget: number;
}

export type SettingsPatch = Partial<Omit<Settings, 'llm_model_choices'>>;

export interface TransactionRequest {
  ticker: string;
  price: number;
  quantity: number;
}

export interface AskRequest {
  question: string;
}

export interface AgentHolding {
  ticker: string;
  quantity: number;
  avg_cost: number;
  price: number | null;
  market_value: number | null;
  cost_basis: number;
  unrealized_pnl: number | null;
}

export interface AgentBook {
  enabled: boolean;
  /** False means the app holds production credentials, where the agent refuses
   * to trade at all. The page says so rather than showing an idle agent. */
  sandbox: boolean;
  budget: number;
  cash: number;
  invested: number;
  market_value: number;
  equity: number;
  realized_pnl: number;
  return_pct: number;
  holdings: AgentHolding[];
}

export interface AgentTrade {
  id: number;
  ticker: string;
  side: string;
  quantity: number;
  price: number | null; // null until the order fills
  placed_at: string;
  filled_at: string | null;
  status: string; // "pending" | "filled" | "rejected"
  /** A protective stop resting at the broker. It is meant to sit pending
   * indefinitely, so it is listed apart from orders awaiting a fill. */
  is_stop: boolean;
  reason: string | null;
  signal_id: number | null;
}

export interface AgentOrder {
  ticker: string;
  side: string;
  quantity: number;
  reason: string | null;
  why: string | null;
}

export interface AgentRun {
  reasoning: string;
  placed: AgentOrder[];
  rejected: AgentOrder[];
  failed: AgentOrder[];
}

export interface Strategy {
  name: string;
  equity: number;
  invested: number;
  cash: number;
  trades: number;
  note: string;
}

/** The agent against the two things it could be replaced by. If the mechanical
 * follower wins, the model is costing money for nothing. */
export interface AgentComparison {
  budget: number;
  since: string | null;
  verdict: string;
  strategies: Strategy[];
}

/** A screened ticker worth considering. Never followed automatically — each
 * one added costs about seven minutes of GPU on every later sweep. */
export interface Candidate {
  ticker: string;
  name: string;
  price: number;
  volume: number;
  change_pct: number | null;
  source: string;
}
