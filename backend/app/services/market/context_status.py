"""Context readiness from persisted DXLink bars, stream health, and freshness rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import Settings
from app.models.bars import IntradayBar
from app.services.broker.dxlink_spy_candle_streamer import DxLinkHealthSnapshot
from app.services.market import context_calculator
from app.services.market.bar_aggregate import DXLINK_BAR_SOURCE


def _as_utc_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _dxlink_bars_only(bars: list[IntradayBar]) -> list[IntradayBar]:
    return [b for b in bars if (b.source_status or "").startswith(DXLINK_BAR_SOURCE)]


@dataclass
class ContextReadiness:
    """Boolean readiness flags and human-readable block reason."""

    context_ready: bool
    block_reason: str
    latest_1m_bar_time: datetime | None
    latest_5m_bar_time: datetime | None
    bars_1m_available: bool
    bars_5m_available: bool
    vwap_available: bool
    opening_range_available: bool
    atr_available: bool


def evaluate_context_readiness(
    *,
    bars_1m: list[IntradayBar],
    bars_5m: list[IntradayBar],
    settings: Settings,
    dxlink: DxLinkHealthSnapshot,
    now: datetime | None = None,
) -> ContextReadiness:
    """Fail closed with explicit reasons when DXLink or context data is insufficient."""
    current = now or datetime.now(timezone.utc)

    if not (dxlink.connected and dxlink.subscribed):
        return ContextReadiness(
            context_ready=False,
            block_reason="dxlink_not_connected",
            latest_1m_bar_time=None,
            latest_5m_bar_time=None,
            bars_1m_available=False,
            bars_5m_available=False,
            vwap_available=False,
            opening_range_available=False,
            atr_available=False,
        )

    b1 = _dxlink_bars_only(bars_1m)
    b5 = _dxlink_bars_only(bars_5m)

    latest_1m = _as_utc_aware(b1[-1].bar_time) if b1 else None
    latest_5m = _as_utc_aware(b5[-1].bar_time) if b5 else None

    if not b1:
        return ContextReadiness(
            context_ready=False,
            block_reason="bars_not_initialized",
            latest_1m_bar_time=latest_1m,
            latest_5m_bar_time=latest_5m,
            bars_1m_available=False,
            bars_5m_available=bool(b5),
            vwap_available=False,
            opening_range_available=False,
            atr_available=False,
        )

    if not b5:
        return ContextReadiness(
            context_ready=False,
            block_reason="insufficient_5m_bars",
            latest_1m_bar_time=latest_1m,
            latest_5m_bar_time=latest_5m,
            bars_1m_available=True,
            bars_5m_available=False,
            vwap_available=False,
            opening_range_available=False,
            atr_available=False,
        )

    age_1m = (current - latest_1m).total_seconds() if latest_1m else None
    age_5m = (current - latest_5m).total_seconds() if latest_5m else None
    if age_1m is None or age_1m > settings.CONTEXT_BAR_MAX_STALENESS_SECONDS_1M:
        return ContextReadiness(
            context_ready=False,
            block_reason="stale_1m_bars",
            latest_1m_bar_time=latest_1m,
            latest_5m_bar_time=latest_5m,
            bars_1m_available=True,
            bars_5m_available=True,
            vwap_available=False,
            opening_range_available=False,
            atr_available=False,
        )
    if age_5m is None or age_5m > settings.CONTEXT_BAR_MAX_STALENESS_SECONDS_5M:
        return ContextReadiness(
            context_ready=False,
            block_reason="stale_5m_bars",
            latest_1m_bar_time=latest_1m,
            latest_5m_bar_time=latest_5m,
            bars_1m_available=True,
            bars_5m_available=True,
            vwap_available=False,
            opening_range_available=False,
            atr_available=False,
        )

    anchor = latest_1m or latest_5m
    session_day = context_calculator.session_date_et(anchor)
    rth_1m = context_calculator.filter_rth_bars_on_session_day(b1, session_day)
    rth_5m = context_calculator.filter_rth_bars_on_session_day(b5, session_day)

    if not rth_1m or not rth_5m:
        return ContextReadiness(
            context_ready=False,
            block_reason="insufficient_1m_bars",
            latest_1m_bar_time=latest_1m,
            latest_5m_bar_time=latest_5m,
            bars_1m_available=True,
            bars_5m_available=True,
            vwap_available=False,
            opening_range_available=False,
            atr_available=False,
        )

    if len(rth_1m) < 5:
        return ContextReadiness(
            context_ready=False,
            block_reason="insufficient_1m_bars",
            latest_1m_bar_time=latest_1m,
            latest_5m_bar_time=latest_5m,
            bars_1m_available=True,
            bars_5m_available=True,
            vwap_available=False,
            opening_range_available=False,
            atr_available=False,
        )

    vwap_ok = context_calculator.compute_session_vwap(rth_1m) is not None
    orh, orl = context_calculator.compute_opening_range(
        rth_5m,
        opening_range_minutes=settings.OPENING_RANGE_MINUTES,
    )
    or_ok = orh is not None and orl is not None

    completed_5m = context_calculator.completed_5m_bars(rth_5m, current)
    atr_ok = context_calculator.compute_atr14_wilder(completed_5m) is not None
    swing_ok = context_calculator.compute_recent_swings(completed_5m)[0] is not None

    if not vwap_ok:
        reason = "insufficient_1m_bars"
    elif not or_ok:
        reason = "insufficient_5m_bars"
    elif len(completed_5m) < 15:
        reason = "insufficient_5m_bars"
    elif not atr_ok:
        reason = "insufficient_5m_bars"
    elif not swing_ok:
        reason = "insufficient_5m_bars"
    else:
        reason = "none"

    ready = reason == "none"
    return ContextReadiness(
        context_ready=ready,
        block_reason=reason,
        latest_1m_bar_time=latest_1m,
        latest_5m_bar_time=latest_5m,
        bars_1m_available=True,
        bars_5m_available=True,
        vwap_available=vwap_ok,
        opening_range_available=or_ok,
        atr_available=atr_ok,
    )
