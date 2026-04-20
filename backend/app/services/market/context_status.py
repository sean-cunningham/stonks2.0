"""Context readiness from persisted bars and freshness rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import Settings
from app.models.bars import IntradayBar
from app.services.market import context_calculator


def _as_utc_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
    now: datetime | None = None,
) -> ContextReadiness:
    """Fail closed with explicit reasons when context is insufficient."""
    current = now or datetime.now(timezone.utc)
    latest_1m = _as_utc_aware(bars_1m[-1].bar_time) if bars_1m else None
    latest_5m = _as_utc_aware(bars_5m[-1].bar_time) if bars_5m else None

    bars_1m_ok = bool(bars_1m)
    bars_5m_ok = bool(bars_5m)
    if not bars_1m_ok or not bars_5m_ok:
        return ContextReadiness(
            context_ready=False,
            block_reason="no_bars_ingested",
            latest_1m_bar_time=latest_1m,
            latest_5m_bar_time=latest_5m,
            bars_1m_available=bars_1m_ok,
            bars_5m_available=bars_5m_ok,
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
    rth_1m = context_calculator.filter_rth_bars_on_session_day(bars_1m, session_day)
    rth_5m = context_calculator.filter_rth_bars_on_session_day(bars_5m, session_day)

    if not rth_1m or not rth_5m:
        return ContextReadiness(
            context_ready=False,
            block_reason="no_rth_session_bars",
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
            block_reason="insufficient_1m_rth_bars",
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
        reason = "vwap_not_computable"
    elif not or_ok:
        reason = "opening_range_not_ready"
    elif len(completed_5m) < 15:
        reason = "insufficient_5m_bars_for_atr"
    elif not atr_ok:
        reason = "atr_not_computable"
    elif not swing_ok:
        reason = "swing_structure_not_ready"
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
