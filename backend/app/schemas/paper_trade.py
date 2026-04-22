"""Paper trade API schemas (Strategy 1 SPY; no live execution)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PaperCloseRequest(BaseModel):
    exit_reason: str = Field(min_length=1, description="Human-readable reason for closing the paper position.")


class PaperTradeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    strategy_id: str
    symbol: str
    option_symbol: str
    side: str
    quantity: int
    status: str
    entry_time: datetime
    entry_price: float
    entry_decision: str
    entry_reference_basis: str
    entry_evaluation_fingerprint: str = ""
    exit_time: datetime | None = None
    exit_price: float | None = None
    exit_reference_basis: str | None = None
    exit_reason: str | None = None
    realized_pnl: float | None = None
    exit_policy: dict[str, Any] | None = None
    sizing_policy: dict[str, Any] | None = None


class PaperTradeEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    paper_trade_id: int
    event_time: datetime
    event_type: str
    details_json: dict[str, Any] | None = None


class PaperOpenPositionValuationResponse(BaseModel):
    """Mark-to-market for one open paper row against the latest chain snapshot (read-only)."""

    paper_trade_id: int
    option_symbol: str
    side: str
    quantity: int
    entry_time: datetime
    entry_price: float
    current_bid: float | None = None
    current_ask: float | None = None
    current_mid: float | None = None
    quote_timestamp_used: datetime | None = None
    quote_age_seconds: float | None = None
    quote_is_fresh: bool = False
    exit_actionable: bool = False
    unrealized_pnl_bid_basis: float | None = None
    unrealized_pnl_mid_basis: float | None = None
    underlying_reference_price: float | None = None
    evaluation_snapshot_reference: dict[str, Any] | None = None
    valuation_error: str | None = None
    exit_policy: dict[str, Any] | None = None
    sizing_policy: dict[str, Any] | None = None


