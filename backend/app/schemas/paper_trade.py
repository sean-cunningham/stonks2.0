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


class PaperTradeEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    paper_trade_id: int
    event_time: datetime
    event_type: str
    details_json: dict[str, Any] | None = None


