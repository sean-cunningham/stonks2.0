"""Common per-strategy dashboard response schema."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class StrategyIdentity(BaseModel):
    strategy_id: str
    strategy_name: str
    symbol_scope: list[str] = Field(default_factory=list)
    paper_only: bool = True


class StrategyRuntimeView(BaseModel):
    mode: str
    scheduler_enabled: bool
    paused: bool
    entry_enabled: bool
    exit_enabled: bool
    running: bool
    lock_scope: str
    last_cycle_started_at: datetime | None = None
    last_cycle_finished_at: datetime | None = None
    last_cycle_result: str | None = None
    last_error: str | None = None
    market_window_open: bool = False
    runtime_sleep_reason: str | None = None


class StrategyControlsView(BaseModel):
    can_pause_resume: bool = True
    can_toggle_entry: bool = True
    can_toggle_exit: bool = True
    emergency_close_supported: bool = True


class StrategyHeadlineMetrics(BaseModel):
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    current_cash: float | None = None
    trade_count: int
    win_rate: float | None = None
    avg_win: float | None = None
    avg_loss: float | None = None
    expectancy: float | None = None
    max_drawdown: float | None = None
    open_position_count: int


class StrategyOpenPositionCard(BaseModel):
    paper_trade_id: int
    symbol: str
    option_symbol: str
    side: str
    quantity: int
    entry_time: datetime
    entry_price: float
    mark_price: float | None = None
    unrealized_pnl: float | None = None
    quote_is_fresh: bool = False
    exit_actionable: bool = False
    monitor_state: str | None = None


class StrategyClosedTradeCard(BaseModel):
    paper_trade_id: int
    symbol: str
    option_symbol: str
    side: str
    quantity: int
    entry_time: datetime
    exit_time: datetime | None = None
    realized_pnl: float | None = None
    exit_reason: str | None = None


class StrategyCycleHistoryRow(BaseModel):
    started_at: datetime
    finished_at: datetime | None = None
    result: str
    cycle_action: str | None = None
    notes_summary: str | None = None
    error_code: str | None = None


class TimeSeriesPoint(BaseModel):
    timestamp: datetime
    value: float


class StrategyTimeseries(BaseModel):
    # MVP estimate: closed-trade realized steps + current open snapshot, not full historical MTM.
    equity_or_value: list[TimeSeriesPoint] = Field(default_factory=list)
    equity_return_pct: list[TimeSeriesPoint] = Field(default_factory=list)
    cash_over_time: list[TimeSeriesPoint] = Field(default_factory=list)
    realized_pnl_cumulative: list[TimeSeriesPoint] = Field(default_factory=list)
    # Optional; when present it is computed from the same MVP estimated series.
    drawdown: list[TimeSeriesPoint] | None = None
    is_minimal_viable: bool = True
    limitations: list[str] = Field(default_factory=list)


class StrategyCurrentSignal(BaseModel):
    current_decision: str
    current_reasons: list[str] = Field(default_factory=list)
    current_blockers: list[str] = Field(default_factory=list)
    candidate_blocked: bool = False
    candidate_block_reason: str | None = None


class StrategyCycleSummary(BaseModel):
    recent_auto_open_failure_count: int = 0
    primary_recent_blocker: str | None = None
    recent_result_counts: dict[str, int] = Field(default_factory=dict)
    recent_failed_gate_counts: dict[str, int] = Field(default_factory=dict)
    most_common_recent_failed_gate: str | None = None
    current_near_miss_explanation: str | None = None
    recent_affordability_failure_count: int = 0
    latest_affordability_diagnostics: dict[str, Any] | None = None


class StrategyDashboardResponse(BaseModel):
    as_of_timestamp: datetime
    strategy: StrategyIdentity
    runtime: StrategyRuntimeView
    controls: StrategyControlsView
    current_signal: StrategyCurrentSignal | None = None
    cycle_summary: StrategyCycleSummary | None = None
    headline_metrics: StrategyHeadlineMetrics
    open_positions: list[StrategyOpenPositionCard] = Field(default_factory=list)
    recent_closed_trades: list[StrategyClosedTradeCard] = Field(default_factory=list)
    recent_cycle_history: list[StrategyCycleHistoryRow] = Field(default_factory=list)
    timeseries: StrategyTimeseries
    strategy_details: dict[str, Any] = Field(default_factory=dict)
