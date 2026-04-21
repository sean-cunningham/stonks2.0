"""Debug visibility for Tastytrade DXLink SPY candle streaming."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.repositories.bars_repository import BarsRepository
from app.services.broker.dxlink_spy_candle_streamer import get_spy_candle_streamer

router = APIRouter(prefix="/debug/dxlink", tags=["debug"])


class DxLinkStatusResponse(BaseModel):
    connected: bool
    subscribed: bool
    last_message_time: datetime | None
    last_candle_time: datetime | None
    quote_token_present: bool
    dxlink_url_present: bool
    reconnect_count: int
    source_status: str
    last_error: str | None = None


class PersistedBarDebug(BaseModel):
    bar_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    source_status: str


class DxLinkLatestCandlesResponse(BaseModel):
    raw_compact_events: list[list[Any]] = Field(
        description="Last few COMPACT Candle tuples (field order matches FEED_SETUP)"
    )
    persisted_1m: list[PersistedBarDebug]


@router.get("/status", response_model=DxLinkStatusResponse)
def dxlink_status() -> DxLinkStatusResponse:
    settings = get_settings()
    h = get_spy_candle_streamer(settings).health_snapshot()
    return DxLinkStatusResponse(
        connected=h.connected,
        subscribed=h.subscribed,
        last_message_time=h.last_message_time,
        last_candle_time=h.last_candle_time,
        quote_token_present=h.quote_token_present,
        dxlink_url_present=h.dxlink_url_present,
        reconnect_count=h.reconnect_count,
        source_status=h.source_status,
        last_error=h.last_error,
    )


@router.get("/spy/candles/latest", response_model=DxLinkLatestCandlesResponse)
def dxlink_spy_candles_latest(
    db: Session = Depends(get_db),
) -> DxLinkLatestCandlesResponse:
    settings = get_settings()
    streamer = get_spy_candle_streamer(settings)
    raw = streamer.recent_raw_candles(12)
    repo = BarsRepository(db)
    bars = repo.list_recent_bars(symbol="SPY", timeframe="1m", limit=12)
    persisted = [
        PersistedBarDebug(
            bar_time=b.bar_time,
            open=b.open,
            high=b.high,
            low=b.low,
            close=b.close,
            volume=b.volume,
            source_status=b.source_status,
        )
        for b in bars
    ]
    return DxLinkLatestCandlesResponse(raw_compact_events=raw, persisted_1m=persisted)
