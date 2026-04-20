from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class NearAtmContract(BaseModel):
    """Normalized option contract summary near ATM."""

    option_symbol: str
    strike: float
    option_type: Literal["call", "put", "unknown"] = "unknown"
    expiration_date: str | None = None
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    delta: float | None = None
    spread_dollars: float | None = None
    spread_percent: float | None = None
    is_call: bool
    is_put: bool


class MarketStatusResponse(BaseModel):
    """Market readiness status for SPY."""

    symbol: str
    market_ready: bool
    block_reason: str
    quote_available: bool
    chain_available: bool
    quote_age_seconds: float | None
    chain_age_seconds: float | None
    quote_is_fresh: bool
    chain_is_fresh: bool
    latest_quote_time: datetime | None
    latest_chain_time: datetime | None
    source_status: str


class QuoteLatestResponse(BaseModel):
    """Latest normalized quote response."""

    symbol: str
    available: bool
    degraded_reason: str | None = None
    bid: float | None = None
    ask: float | None = None
    mid: float | None = None
    last: float | None = None
    quote_timestamp: datetime | None = None
    source_status: str


class ChainLatestResponse(BaseModel):
    """Latest normalized option chain summary response."""

    underlying_symbol: str
    available: bool
    degraded_reason: str | None = None
    snapshot_timestamp: datetime | None = None
    expiration_dates_found: list[str] = Field(default_factory=list)
    selected_expiration: str | None = None
    underlying_reference_price: float | None = None
    total_contracts_seen: int | None = None
    option_quotes_available: bool = False
    near_atm_contracts: list[NearAtmContract] = Field(default_factory=list)
    source_status: str


class RefreshResponse(BaseModel):
    """Manual market refresh response."""

    refreshed: bool
    quote_refreshed: bool
    chain_refreshed: bool
    status: MarketStatusResponse
