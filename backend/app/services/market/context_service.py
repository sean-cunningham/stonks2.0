"""Orchestration for SPY intraday context API (bars + metrics + readiness)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.repositories.bars_repository import BarsRepository
from app.schemas.bars import BarListResponse, BarRow
from app.schemas.context import (
    ContextRefreshResponse,
    ContextStatusDebugResponse,
    ContextStatusResponse,
    ContextSummaryResponse,
)
from app.services.broker.dxlink_spy_candle_streamer import get_spy_candle_streamer
from app.services.market import bar_ingestion, context_calculator, context_status
from app.services.market.bar_aggregate import DXLINK_BAR_SOURCE

logger = logging.getLogger(__name__)


def _dxlink_bars(bars: list) -> list:
    return [b for b in bars if (b.source_status or "").startswith(DXLINK_BAR_SOURCE)]


class ContextService:
    """Read/write SPY context state backed by IntradayBar rows."""

    def __init__(self, db: Session, settings: Settings) -> None:
        self._db = db
        self._settings = settings
        self._bars = BarsRepository(db)

    def _dxlink_health(self):
        return get_spy_candle_streamer(self._settings).health_snapshot()

    def _load_bars(self, limit: int = 120) -> tuple[list, list]:
        one = self._bars.list_recent_bars(symbol="SPY", timeframe="1m", limit=limit)
        five = self._bars.list_recent_bars(symbol="SPY", timeframe="5m", limit=limit)
        return one, five

    def _bars_source_label(self, bars_1m: list, bars_5m: list) -> str:
        if _dxlink_bars(bars_1m) or _dxlink_bars(bars_5m):
            return DXLINK_BAR_SOURCE
        if self._dxlink_health().subscribed:
            return DXLINK_BAR_SOURCE
        return "none"

    def get_status(self) -> ContextStatusResponse:
        bars_1m, bars_5m = self._load_bars()
        readiness = context_status.evaluate_context_readiness(
            bars_1m=bars_1m,
            bars_5m=bars_5m,
            settings=self._settings,
            dxlink=self._dxlink_health(),
        )
        source = self._bars_source_label(bars_1m, bars_5m)
        analysis_ok = readiness.context_ready_for_analysis
        return ContextStatusResponse(
            symbol="SPY",
            us_equity_rth_open=readiness.us_equity_rth_open,
            context_ready_for_live_trading=readiness.context_ready_for_live_trading,
            context_ready_for_analysis=readiness.context_ready_for_analysis,
            context_ready=readiness.context_ready,
            block_reason=readiness.block_reason,
            block_reason_analysis=readiness.block_reason_analysis,
            latest_session_date_et=readiness.latest_session_date_et,
            latest_1m_bar_time=readiness.latest_1m_bar_time,
            latest_5m_bar_time=readiness.latest_5m_bar_time,
            bars_1m_available=readiness.bars_1m_available,
            bars_5m_available=readiness.bars_5m_available,
            vwap_available=readiness.vwap_available,
            opening_range_available=readiness.opening_range_available,
            atr_available=readiness.atr_available,
            expected_latest_completed_5m_start=readiness.expected_latest_completed_5m_start,
            stale_5m_reference_time=readiness.stale_5m_reference_time,
            stale_5m_seconds=readiness.stale_5m_seconds,
            stale_5m_boolean=readiness.stale_5m_boolean,
            source_status="ok" if analysis_ok else "degraded",
            bars_source=source,
        )

    def get_status_debug(self) -> ContextStatusDebugResponse:
        """Same readiness evaluation as /context/spy/status; exposes 5m staleness inputs explicitly."""
        bars_1m, bars_5m = self._load_bars()
        readiness = context_status.evaluate_context_readiness(
            bars_1m=bars_1m,
            bars_5m=bars_5m,
            settings=self._settings,
            dxlink=self._dxlink_health(),
        )
        return ContextStatusDebugResponse(
            symbol="SPY",
            latest_1m_bar_time=readiness.latest_1m_bar_time,
            latest_5m_bar_time=readiness.latest_5m_bar_time,
            expected_latest_completed_5m_start=readiness.expected_latest_completed_5m_start,
            stale_5m_reference_time=readiness.stale_5m_reference_time,
            stale_5m_seconds=readiness.stale_5m_seconds,
            stale_5m_boolean=readiness.stale_5m_boolean,
            block_reason=readiness.block_reason,
            block_reason_analysis=readiness.block_reason_analysis,
        )

    def get_bars_1m(self) -> BarListResponse:
        bars = self._bars.list_recent_bars(symbol="SPY", timeframe="1m", limit=120)
        return self._to_bar_list(bars, "1m")

    def get_bars_5m(self) -> BarListResponse:
        bars = self._bars.list_recent_bars(symbol="SPY", timeframe="5m", limit=120)
        return self._to_bar_list(bars, "5m")

    def _to_bar_list(self, bars: list, timeframe: str) -> BarListResponse:
        one, five = self._load_bars()
        source = self._bars_source_label(one, five)
        return BarListResponse(
            symbol="SPY",
            timeframe=timeframe,
            bars=[
                BarRow(
                    symbol=b.symbol,
                    timeframe=b.timeframe,
                    bar_time=b.bar_time,
                    open=b.open,
                    high=b.high,
                    low=b.low,
                    close=b.close,
                    volume=b.volume,
                    source_status=b.source_status,
                )
                for b in bars
            ],
            bars_source=source,
            fetched_at=datetime.now(timezone.utc),
        )

    def get_summary(self) -> ContextSummaryResponse:
        bars_1m, bars_5m = self._load_bars()
        b1 = _dxlink_bars(bars_1m)
        b5 = _dxlink_bars(bars_5m)
        readiness = context_status.evaluate_context_readiness(
            bars_1m=bars_1m,
            bars_5m=bars_5m,
            settings=self._settings,
            dxlink=self._dxlink_health(),
        )
        metrics = context_calculator.compute_context_metrics(
            bars_1m=b1 or bars_1m,
            bars_5m=b5 or bars_5m,
            now=datetime.now(timezone.utc),
            opening_range_minutes=self._settings.OPENING_RANGE_MINUTES,
        )
        source = self._bars_source_label(bars_1m, bars_5m)
        analysis_ok = readiness.context_ready_for_analysis
        return ContextSummaryResponse(
            symbol="SPY",
            us_equity_rth_open=readiness.us_equity_rth_open,
            context_ready_for_live_trading=readiness.context_ready_for_live_trading,
            context_ready_for_analysis=readiness.context_ready_for_analysis,
            latest_price=metrics.latest_price,
            session_vwap=metrics.session_vwap if analysis_ok else None,
            opening_range_high=metrics.opening_range_high if analysis_ok else None,
            opening_range_low=metrics.opening_range_low if analysis_ok else None,
            latest_5m_atr=metrics.latest_5m_atr if analysis_ok else None,
            recent_swing_high=metrics.recent_swing_high if analysis_ok else None,
            recent_swing_low=metrics.recent_swing_low if analysis_ok else None,
            relative_volume_5m=(
                metrics.relative_volume_5m if analysis_ok and metrics.relative_volume_available else None
            ),
            relative_volume_available=bool(analysis_ok and metrics.relative_volume_available),
            latest_1m_bar_time=readiness.latest_1m_bar_time,
            latest_5m_bar_time=readiness.latest_5m_bar_time,
            latest_session_date_et=readiness.latest_session_date_et,
            context_ready=readiness.context_ready,
            block_reason=readiness.block_reason,
            block_reason_analysis=readiness.block_reason_analysis,
            source_status="ok" if analysis_ok else "degraded",
            bars_source=source,
        )

    def refresh(self) -> ContextRefreshResponse:
        """Recompute 5m from persisted 1m and return readiness."""
        try:
            n1, n5, src = bar_ingestion.ingest_spy_intraday(self._db, self._settings)
            refreshed = n5 > 0
        except bar_ingestion.BarIngestionError as exc:
            logger.warning("Context refresh failed: %s", exc)
            n1, n5, src = 0, 0, f"failed:{exc}"
            refreshed = False

        status = self.get_status()
        summary = self.get_summary()
        if refreshed:
            summary = summary.model_copy(update={"bars_source": src, "source_status": status.source_status})
            status = status.model_copy(update={"bars_source": src})
        return ContextRefreshResponse(
            refreshed=refreshed,
            bars_1m_written=n1,
            bars_5m_written=n5,
            status=status,
            summary=summary,
        )
