"""Pydantic schemas for intraday bar API responses."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BarRow(BaseModel):
    """Single OHLCV bar."""

    symbol: str
    timeframe: str
    bar_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    source_status: str


class BarListResponse(BaseModel):
    """List of bars with metadata."""

    symbol: str
    timeframe: str
    bars: list[BarRow] = Field(default_factory=list)
    bars_source: str
    fetched_at: datetime
