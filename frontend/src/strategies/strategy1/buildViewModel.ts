import type { DashboardResponse, StrategyDashboardViewModel } from "../../types/dashboard";

export function buildStrategy1ViewModel(payload: DashboardResponse): StrategyDashboardViewModel {
  return {
    title: payload.strategy.strategy_name,
    strategyId: payload.strategy.strategy_id,
    symbol: payload.strategy.symbol_scope[0] ?? "SPY",
    asOf: payload.as_of_timestamp,
    runtime: payload.runtime,
    controls: payload.controls,
    currentSignal: payload.current_signal ?? null,
    cycleSummary: payload.cycle_summary ?? null,
    statsBaseline: payload.stats_baseline ?? null,
    metrics: payload.headline_metrics,
    equitySeries: payload.timeseries.equity_or_value,
    equityReturnSeries: payload.timeseries.equity_return_pct ?? [],
    cashSeries: payload.timeseries.cash_over_time ?? [],
    equitySeriesIsMinimalViable: payload.timeseries.is_minimal_viable,
    openPositions: payload.open_positions,
    closedTrades: payload.recent_closed_trades,
    cycleHistory: payload.recent_cycle_history,
    limitations: payload.timeseries.limitations,
    strategyDetails: payload.strategy_details,
  };
}
