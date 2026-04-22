"""Unified Strategy 1 open paper position monitor (read-only; dashboard-oriented)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.context import ContextStatusResponse, ContextSummaryResponse
from app.schemas.market import MarketStatusResponse
from app.schemas.paper_trade import PaperOpenPositionValuationResponse
from app.schemas.strategy_one_exit_evaluation import StrategyOneExitEvaluationResponse

MonitorStateLiteral = Literal["healthy", "blocked", "protected", "trail_active", "close_now"]


class StrategyOnePositionMonitorRow(BaseModel):
    """One open Strategy 1 paper row with valuation + exit readout."""

    paper_trade_id: int
    strategy_id: str
    symbol: str
    option_symbol: str
    side: str
    quantity: int
    entry_time: datetime
    entry_price: float
    entry_decision: str
    entry_reference_basis: str = "option_ask"
    valuation: PaperOpenPositionValuationResponse
    exit_policy: dict[str, Any] | None = None
    sizing_policy: dict[str, Any] | None = None
    exit_evaluation: StrategyOneExitEvaluationResponse
    monitor_state: MonitorStateLiteral


class StrategyOneOpenPositionsMonitorResponse(BaseModel):
    """All open Strategy 1 paper positions at one evaluation instant."""

    evaluation_timestamp: datetime
    context_status: ContextStatusResponse
    context_summary: ContextSummaryResponse
    market_status: MarketStatusResponse
    positions: list[StrategyOnePositionMonitorRow] = Field(default_factory=list)


class StrategyOneOpenPositionMonitorResponse(BaseModel):
    """Single open Strategy 1 paper position monitor payload."""

    evaluation_timestamp: datetime
    context_status: ContextStatusResponse
    context_summary: ContextSummaryResponse
    market_status: MarketStatusResponse
    position: StrategyOnePositionMonitorRow
