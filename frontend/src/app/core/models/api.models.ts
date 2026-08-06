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
  by_ticker: Record<string, [number, number]>;
}

export interface TickerSummary {
  ticker: string;
  current_price: number | null;
  latest_signal: Signal | null;
}

export interface TickerDetail {
  ticker: string;
  current_price: number | null;
  real_position: PortfolioPosition | null;
  paper_position: PaperPosition | null;
  latest_signal: Signal | null;
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
  paper_notional: number;
  risk_equity: number | null;
  risk_pct: number;
  alert_move_pct: number;
  alert_stop_pct: number;
  alert_volume_mult: number;
  alerts_enabled: boolean;
  daily_sweep_enabled: boolean;
}

export type SettingsPatch = Partial<Settings>;

export interface TransactionRequest {
  ticker: string;
  price: number;
  quantity: number;
}

export interface AskRequest {
  question: string;
}
