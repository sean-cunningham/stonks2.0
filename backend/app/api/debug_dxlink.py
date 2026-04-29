"""Debug visibility for Tastytrade DXLink SPY candle streaming."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.repositories.bars_repository import BarsRepository
from app.services.broker.dxlink_spy_candle_streamer import get_spy_candle_streamer

router = APIRouter(prefix="/debug/dxlink", tags=["debug"])


def _latest_persisted_dxlink_from_db(repo: BarsRepository) -> tuple[datetime | None, float | None]:
    """Single source of truth: newest SPY 1m row with DXLink candle source."""
    bar = repo.latest_spy_1m_dxlink()
    if bar is None:
        return None, None
    bt = bar.bar_time if bar.bar_time.tzinfo else bar.bar_time.replace(tzinfo=timezone.utc)
    bt = bt.astimezone(timezone.utc)
    return bt, float(bar.close)


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
    subscribed_symbol: str
    event_type: str
    parser_mode: str
    latest_raw_period_time: datetime | None = Field(
        default=None, description="Max Candle.period (time field) seen on this session, UTC"
    )
    latest_raw_event_time: datetime | None = Field(
        default=None, description="Latest dxFeed eventTime among decoded debug rows, UTC"
    )
    latest_raw_close: float | None = None
    latest_persisted_1m_bar_time: datetime | None = None
    latest_persisted_1m_close: float | None = None
    quote_token_refresh_attempted: bool = False
    quote_token_refresh_succeeded: bool = False
    quote_token_refresh_failed: bool = False
    dxlink_reconnect_after_auth_error: bool = False
    dxlink_reconnect_succeeded: bool = False
    dxlink_reconnect_failed: bool = False


class PersistedBarDebug(BaseModel):
    bar_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    source_status: str


class DecodedCandleDebug(BaseModel):
    """Candle COMPACT row decoded with the same field map as the persistence path."""

    event_symbol: str
    time_ms: int
    period_time_utc: datetime
    event_time_ms: int | None = None
    event_time_utc: datetime | None = None
    event_flags: int
    open_price: float
    high: float
    low: float
    close_price: float
    volume: float | None = None
    parser_mode: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DecodedCandleDebug:
        return cls(
            event_symbol=str(row.get("eventSymbol") or ""),
            time_ms=int(row["time_ms"]),
            period_time_utc=row["period_time_utc"],
            event_time_ms=row.get("event_time_ms"),
            event_time_utc=row.get("event_time_utc"),
            event_flags=int(row.get("eventFlags") or 0),
            open_price=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close_price=float(row["close"]),
            volume=float(row["volume"]) if row.get("volume") is not None else None,
            parser_mode=str(row.get("parser_mode") or ""),
        )


class DxLinkLatestCandlesResponse(BaseModel):
    decoded_candles: list[DecodedCandleDebug] = Field(
        description="Latest Candle periods (time key); same parser as SQLite 1m writes"
    )
    persisted_1m: list[PersistedBarDebug]
    subscribed_symbol: str
    event_type: str
    parser_mode: str
    latest_raw_period_time: datetime | None = None
    latest_raw_event_time: datetime | None = None
    latest_raw_close: float | None = None
    latest_persisted_1m_bar_time: datetime | None = None
    latest_persisted_1m_close: float | None = None


@router.get("/status", response_model=DxLinkStatusResponse)
def dxlink_status(db: Session = Depends(get_db)) -> DxLinkStatusResponse:
    settings = get_settings()
    h = get_spy_candle_streamer(settings).health_snapshot()
    repo = BarsRepository(db)
    p_time, p_close = _latest_persisted_dxlink_from_db(repo)
    merged_last = h.last_candle_time
    if p_time is not None and (merged_last is None or p_time > merged_last):
        merged_last = p_time
    return DxLinkStatusResponse(
        connected=h.connected,
        subscribed=h.subscribed,
        last_message_time=h.last_message_time,
        last_candle_time=merged_last,
        quote_token_present=h.quote_token_present,
        dxlink_url_present=h.dxlink_url_present,
        reconnect_count=h.reconnect_count,
        source_status=h.source_status,
        last_error=h.last_error,
        subscribed_symbol=h.subscribed_symbol,
        event_type=h.event_type,
        parser_mode=h.parser_mode,
        latest_raw_period_time=h.latest_raw_period_time,
        latest_raw_event_time=h.latest_raw_event_time,
        latest_raw_close=h.latest_raw_close,
        latest_persisted_1m_bar_time=p_time,
        latest_persisted_1m_close=p_close,
        quote_token_refresh_attempted=h.quote_token_refresh_attempted,
        quote_token_refresh_succeeded=h.quote_token_refresh_succeeded,
        quote_token_refresh_failed=h.quote_token_refresh_failed,
        dxlink_reconnect_after_auth_error=h.dxlink_reconnect_after_auth_error,
        dxlink_reconnect_succeeded=h.dxlink_reconnect_succeeded,
        dxlink_reconnect_failed=h.dxlink_reconnect_failed,
    )


@router.get("/spy/candles/latest", response_model=DxLinkLatestCandlesResponse)
def dxlink_spy_candles_latest(
    db: Session = Depends(get_db),
) -> DxLinkLatestCandlesResponse:
    settings = get_settings()
    streamer = get_spy_candle_streamer(settings)
    rows = streamer.recent_decoded_candles(12)
    decoded = [DecodedCandleDebug.from_row(r) for r in rows]
    repo = BarsRepository(db)
    bars = repo.list_recent_spy_1m_dxlink(limit=12)
    p_time, p_close = _latest_persisted_dxlink_from_db(repo)
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
    h = streamer.health_snapshot()
    return DxLinkLatestCandlesResponse(
        decoded_candles=decoded,
        persisted_1m=persisted,
        subscribed_symbol=h.subscribed_symbol,
        event_type=h.event_type,
        parser_mode=h.parser_mode,
        latest_raw_period_time=h.latest_raw_period_time,
        latest_raw_event_time=h.latest_raw_event_time,
        latest_raw_close=h.latest_raw_close,
        latest_persisted_1m_bar_time=p_time,
        latest_persisted_1m_close=p_close,
    )
