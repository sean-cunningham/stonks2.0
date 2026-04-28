export type RuntimeView = {
  mode: string;
  scheduler_enabled: boolean;
  paused: boolean;
  entry_enabled: boolean;
  exit_enabled: boolean;
  running: boolean;
  lock_scope: string;
  last_cycle_started_at: string | null;
  last_cycle_finished_at: string | null;
  last_cycle_result: string | null;
  last_error: string | null;
  /** US/Eastern regular session (weekday 9:30–16:00) at status time */
  market_window_open?: boolean;
  /** Why the scheduler is idle: paused | outside_rth | null when the window is open and not paused */
  runtime_sleep_reason?: string | null;
};

export type DashboardPoint = {
  timestamp: string;
  value: number;
};

export type DashboardResponse = {
  as_of_timestamp: string;
  strategy: {
    strategy_id: string;
    strategy_name: string;
    symbol_scope: string[];
    paper_only: boolean;
  };
  runtime: RuntimeView;
  controls: {
    can_pause_resume: boolean;
    can_toggle_entry: boolean;
    can_toggle_exit: boolean;
    emergency_close_supported: boolean;
    can_reset_stats?: boolean;
  };
  current_signal?: {
    current_decision: "candidate_call" | "candidate_put" | "no_trade" | string;
    current_reasons: string[];
    current_blockers: string[];
    candidate_blocked: boolean;
    candidate_block_reason: string | null;
  } | null;
  cycle_summary?: {
    recent_auto_open_failure_count: number;
    primary_recent_blocker: string | null;
    recent_result_counts: Record<string, number>;
    recent_failed_gate_counts: Record<string, number>;
    most_common_recent_failed_gate: string | null;
    current_near_miss_explanation: string | null;
    recent_affordability_failure_count: number;
    latest_affordability_diagnostics: Record<string, string> | null;
  } | null;
  stats_baseline?: {
    reset_at: string;
    baseline_cash: number;
  } | null;
  headline_metrics: {
    realized_pnl: number;
    unrealized_pnl: number;
    total_pnl: number;
    current_cash: number | null;
    trade_count: number;
    win_rate: number | null;
    avg_win: number | null;
    avg_loss: number | null;
    expectancy: number | null;
    max_drawdown: number | null;
    open_position_count: number;
  };
  open_positions: Array<{
    paper_trade_id: number;
    symbol: string;
    option_symbol: string;
    side: string;
    quantity: number;
    entry_time: string;
    entry_price: number;
    mark_price: number | null;
    unrealized_pnl: number | null;
    unrealized_pnl_pct?: number | null;
    stop_price?: number | null;
    take_profit_price?: number | null;
    quote_is_fresh: boolean;
    exit_actionable: boolean;
    monitor_state: string | null;
    current_bid?: number | null;
    current_ask?: number | null;
    quote_timestamp?: string | null;
    quote_resolution_source?: string | null;
    quote_blocker_code?: string | null;
    exit_blocked_reasons?: string[];
    entry_underlying_price?: number | null;
    max_unrealized_pnl_percent?: number | null;
    profit_lock_stage?: string | null;
  }>;
  recent_closed_trades: Array<{
    paper_trade_id: number;
    symbol: string;
    option_symbol: string;
    side: string;
    quantity: number;
    entry_time: string;
    exit_time: string | null;
    realized_pnl: number | null;
    exit_reason: string | null;
    /** entry_price × 100 × qty */
    total_purchase_price_usd?: number | null;
    /** exit_price × 100 × qty */
    total_sale_price_usd?: number | null;
  }>;
  recent_cycle_history: Array<{
    started_at: string;
    finished_at: string | null;
    result: string;
    cycle_action: string | null;
    notes_summary: string | null;
    error_code: string | null;
  }>;
  timeseries: {
    equity_or_value: DashboardPoint[];
    equity_return_pct: DashboardPoint[];
    cash_over_time: DashboardPoint[];
    realized_pnl_cumulative: DashboardPoint[];
    drawdown: DashboardPoint[] | null;
    is_minimal_viable: boolean;
    limitations: string[];
  };
  strategy_details: Record<string, unknown>;
};

export type StrategyDashboardViewModel = {
  title: string;
  strategyId: string;
  symbol: string;
  asOf: string;
  runtime: RuntimeView;
  controls: DashboardResponse["controls"];
  currentSignal: NonNullable<DashboardResponse["current_signal"]> | null;
  cycleSummary: NonNullable<DashboardResponse["cycle_summary"]> | null;
  statsBaseline: NonNullable<DashboardResponse["stats_baseline"]> | null;
  metrics: DashboardResponse["headline_metrics"];
  equitySeries: DashboardPoint[];
  equityReturnSeries: DashboardPoint[];
  cashSeries: DashboardPoint[];
  /** Backend marks MVP / estimated equity curve (sparse early session). */
  equitySeriesIsMinimalViable: boolean;
  openPositions: DashboardResponse["open_positions"];
  closedTrades: DashboardResponse["recent_closed_trades"];
  cycleHistory: DashboardResponse["recent_cycle_history"];
  limitations: string[];
  strategyDetails: Record<string, unknown>;
};
