"""Pydantic schemas for SPY market context (Strategy 1-lite prep)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class ContextStatusResponse(BaseModel):
    """Readiness and freshness for SPY intraday context."""

    symbol: str
    us_equity_rth_open: bool = Field(description="True during US regular session Mon–Fri 09:30–16:00 ET (weekday-only)")
    context_ready_for_live_trading: bool
    context_ready_for_analysis: bool
    context_ready: bool = Field(
        description="Same as context_ready_for_live_trading (strict + RTH open); kept for compatibility"
    )
    block_reason: str = Field(description="Primary blocker for live trading (e.g. market_closed, stale_1m_bars)")
    block_reason_analysis: str = Field(description="Blocker for post-close analysis metrics; none or latest_session_complete when usable")
    latest_session_date_et: date | None = Field(default=None, description="ET calendar date of the anchored latest bar session")
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
    us_equity_rth_open: bool = False
    context_ready_for_live_trading: bool = False
    context_ready_for_analysis: bool = False
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
    latest_session_date_et: date | None = None
    context_ready: bool
    block_reason: str
    block_reason_analysis: str = "none"
    source_status: str
    bars_source: str


class ContextRefreshResponse(BaseModel):
    """Result of POST /context/spy/refresh."""

    refreshed: bool
    bars_1m_written: int
    bars_5m_written: int
    status: ContextStatusResponse
    summary: ContextSummaryResponse
