"""Read-only Strategy 1 (SPY) evaluation schemas — no execution or persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.market import NearAtmContract

DecisionLiteral = Literal["no_trade", "candidate_call", "candidate_put"]
MarketStatusSourceLiteral = Literal["cached", "refreshed_for_evaluation"]


class StrategyOneMarketEvaluationTrace(BaseModel):
    """Temporary diagnostics: how market readiness was resolved for this evaluation."""

    market_status_source: MarketStatusSourceLiteral
    auto_refresh_attempted: bool
    auto_refresh_trigger_reason: str | None = None
    post_refresh_market_ready: bool
    post_refresh_block_reason: str


class StrategyOneContextSnapshot(BaseModel):
    """Inputs surfaced to the client for audit (subset of context + market chain)."""

    symbol: str = "SPY"
    us_equity_rth_open: bool
    context_ready_for_live_trading: bool
    context_block_reason: str
    latest_price: float | None = None
    session_vwap: float | None = None
    opening_range_high: float | None = None
    opening_range_low: float | None = None
    latest_5m_atr: float | None = None
    recent_swing_high: float | None = None
    recent_swing_low: float | None = None
    market_ready: bool
    market_block_reason: str
    chain_available: bool
    chain_option_quotes_available: bool
    chain_selected_expiration: str | None = None
    underlying_reference_price: float | None = None
    # Temporary diagnostics for quote freshness vs market_ready (same inputs as readiness).
    quote_timestamp_used: datetime | None = None
    quote_age_seconds: float | None = None
    quote_freshness_threshold_seconds: int | None = None
    quote_stale: bool | None = None


class StrategyOneEvaluationResponse(BaseModel):
    """Structured read-only decision for Strategy 1 on SPY."""

    symbol: str = "SPY"
    decision: DecisionLiteral
    blockers: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    context_snapshot_used: StrategyOneContextSnapshot
    contract_candidate: NearAtmContract | None = None
    evaluation_timestamp: datetime
    market_evaluation_trace: StrategyOneMarketEvaluationTrace | None = None
