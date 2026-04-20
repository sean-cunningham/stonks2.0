"""Pydantic schemas for SPY market context (Strategy 1-lite prep)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ContextStatusResponse(BaseModel):
    """Readiness and freshness for SPY intraday context."""

    symbol: str
    context_ready: bool
    block_reason: str
    latest_1m_bar_time: datetime | None
    latest_5m_bar_time: datetime | None
    bars_1m_available: bool
    bars_5m_available: bool
    vwap_available: bool
    opening_range_available: bool
    atr_available: bool
    source_status: str
    bars_source: str


class ContextSummaryResponse(BaseModel):
    """Computed context metrics (fail closed when not ready)."""

    symbol: str
    latest_price: float | None = None
    session_vwap: float | None = None
    opening_range_high: float | None = None
    opening_range_low: float | None = None
    latest_5m_atr: float | None = None
    recent_swing_high: float | None = None
    recent_swing_low: float | None = None
    relative_volume_5m: float | None = None
    relative_volume_available: bool = False
    latest_1m_bar_time: datetime | None = None
    latest_5m_bar_time: datetime | None = None
    context_ready: bool
    block_reason: str
    source_status: str
    bars_source: str


class ContextRefreshResponse(BaseModel):
    """Result of POST /context/spy/refresh."""

    refreshed: bool
    bars_1m_written: int
    bars_5m_written: int
    status: ContextStatusResponse
    summary: ContextSummaryResponse
