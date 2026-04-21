"""Context readiness from persisted DXLink bars, stream health, and session-aware freshness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.core.config import Settings
from app.models.bars import IntradayBar
from app.services.broker.dxlink_spy_candle_streamer import DxLinkHealthSnapshot
from app.services.market import context_calculator
from app.services.market.bar_aggregate import DXLINK_BAR_SOURCE
from app.services.market.session_clock import expected_context_session_date_et, is_us_equity_rth_open


def _as_utc_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _dxlink_bars_only(bars: list[IntradayBar]) -> list[IntradayBar]:
    return [b for b in bars if (b.source_status or "").startswith(DXLINK_BAR_SOURCE)]


def _expected_latest_completed_5m_start(latest_1m: datetime) -> datetime:
    """
    Map latest completed 1m timestamp to the expected latest *completed* 5m bucket start.

    Bars are labeled by bucket-start time. A 5m bucket [S..S+4] is complete only when the
    latest completed 1m is >= S+4.

    Examples:
    - latest_1m=15:25 => expected latest completed 5m start is 15:20
    - latest_1m=15:29 => expected latest completed 5m start is 15:25
    - latest_1m=15:30 => expected latest completed 5m start is 15:25
    """
    if latest_1m.tzinfo is None:
        latest_1m = latest_1m.replace(tzinfo=timezone.utc)
    # Shift back 4 minutes so floor-to-5 yields the latest completed bucket start.
    completed_anchor = latest_1m - timedelta(minutes=4)
    return completed_anchor.replace(minute=(completed_anchor.minute // 5) * 5, second=0, microsecond=0)


@dataclass
class ContextReadiness:
    """Session-aware readiness for live trading vs post-close analysis."""

    us_equity_rth_open: bool
    context_ready_for_live_trading: bool
    context_ready_for_analysis: bool
    context_ready: bool
    block_reason: str
    block_reason_analysis: str
    latest_session_date_et: date | None
    latest_1m_bar_time: datetime | None
    latest_5m_bar_time: datetime | None
    bars_1m_available: bool
    bars_5m_available: bool
    vwap_available: bool
    opening_range_available: bool
    atr_available: bool
    expected_latest_completed_5m_start: datetime | None = None
    stale_5m_reference_time: datetime | None = None
    stale_5m_seconds: float | None = None
    stale_5m_boolean: bool = False


def _metrics_reason_and_flags(
    *,
    b1: list[IntradayBar],
    b5: list[IntradayBar],
    latest_1m: datetime | None,
    latest_5m: datetime | None,
    settings: Settings,
    current: datetime,
) -> tuple[str, bool, bool, bool, bool, bool]:
    """
    Returns (analysis_block_reason, bars_1m_ok, bars_5m_ok, vwap_ok, or_ok, atr_ok).

    analysis_block_reason is 'none' when analysis metrics are computable on the anchor session.
    """
    if not b1:
        return "bars_not_initialized", False, bool(b5), False, False, False
    if not b5:
        return "insufficient_5m_bars", True, False, False, False, False

    anchor = latest_1m or latest_5m
    if anchor is None:
        return "bars_not_initialized", False, False, False, False, False

    session_day = context_calculator.session_date_et(anchor)
    rth_1m = context_calculator.filter_rth_bars_on_session_day(b1, session_day)
    rth_5m = context_calculator.filter_rth_bars_on_session_day(b5, session_day)

    if not rth_1m or not rth_5m:
        return "insufficient_1m_bars", True, True, False, False, False

    if len(rth_1m) < 5:
        return "insufficient_1m_bars", True, True, False, False, False

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

    return reason, True, True, vwap_ok, or_ok, atr_ok


def evaluate_context_readiness(
    *,
    bars_1m: list[IntradayBar],
    bars_5m: list[IntradayBar],
    settings: Settings,
    dxlink: DxLinkHealthSnapshot,
    now: datetime | None = None,
) -> ContextReadiness:
    """Separate live-trading readiness (strict + RTH) from post-close analysis readiness."""
    current = now or datetime.now(timezone.utc)
    rth_open = is_us_equity_rth_open(current)
    expected_session = expected_context_session_date_et(current)

    def _readiness(
        *,
        live: bool,
        analysis: bool,
        block: str,
        block_a: str,
        latest_1m: datetime | None,
        latest_5m: datetime | None,
        b1a: bool,
        b5a: bool,
        vwap: bool,
        ora: bool,
        atr: bool,
        session_day: date | None,
        expected_5m: datetime | None = None,
        stale_ref: datetime | None = None,
        stale_seconds: float | None = None,
        stale_flag: bool = False,
    ) -> ContextReadiness:
        return ContextReadiness(
            us_equity_rth_open=rth_open,
            context_ready_for_live_trading=live,
            context_ready_for_analysis=analysis,
            context_ready=live,
            block_reason=block,
            block_reason_analysis=block_a,
            latest_session_date_et=session_day,
            latest_1m_bar_time=latest_1m,
            latest_5m_bar_time=latest_5m,
            bars_1m_available=b1a,
            bars_5m_available=b5a,
            vwap_available=vwap,
            opening_range_available=ora,
            atr_available=atr,
            expected_latest_completed_5m_start=expected_5m,
            stale_5m_reference_time=stale_ref,
            stale_5m_seconds=stale_seconds,
            stale_5m_boolean=stale_flag,
        )

    b1 = _dxlink_bars_only(bars_1m)
    b5 = _dxlink_bars_only(bars_5m)

    latest_1m = _as_utc_aware(b1[-1].bar_time) if b1 else None
    latest_5m = _as_utc_aware(b5[-1].bar_time) if b5 else None
    latest_session = context_calculator.session_date_et(latest_1m) if latest_1m else None

    # If we have no persisted DXLink bars at all, report connectivity first when disconnected.
    if not b1 and not b5 and not (dxlink.connected and dxlink.subscribed):
        return _readiness(
            live=False,
            analysis=False,
            block="dxlink_not_connected",
            block_a="dxlink_not_connected",
            latest_1m=None,
            latest_5m=None,
            b1a=False,
            b5a=False,
            vwap=False,
            ora=False,
            atr=False,
            session_day=None,
        )

    age_1m = (current - latest_1m).total_seconds() if latest_1m else None
    age_5m = (current - latest_5m).total_seconds() if latest_5m else None
    stale_1m = age_1m is None or age_1m > settings.CONTEXT_BAR_MAX_STALENESS_SECONDS_1M
    stale_5m = age_5m is None or age_5m > settings.CONTEXT_BAR_MAX_STALENESS_SECONDS_5M
    expected_5m_start: datetime | None = None
    stale_5m_ref: datetime | None = current
    stale_5m_seconds: float | None = age_5m
    if rth_open and latest_1m is not None and latest_5m is not None:
        expected_5m_start = _expected_latest_completed_5m_start(latest_1m)
        # Freshness for 5m in RTH should follow completed-bucket semantics rather than wall-clock age.
        stale_5m = latest_5m < expected_5m_start
        stale_5m_ref = expected_5m_start
        stale_5m_seconds = max((expected_5m_start - latest_5m).total_seconds(), 0.0)

    if rth_open and stale_1m:
        return _readiness(
            live=False,
            analysis=False,
            block="stale_1m_bars",
            block_a="stale_1m_bars",
            latest_1m=latest_1m,
            latest_5m=latest_5m,
            b1a=bool(b1),
            b5a=bool(b5),
            vwap=False,
            ora=False,
            atr=False,
            session_day=latest_session,
            expected_5m=expected_5m_start,
            stale_ref=stale_5m_ref,
            stale_seconds=stale_5m_seconds,
            stale_flag=stale_5m,
        )
    if rth_open and stale_5m:
        return _readiness(
            live=False,
            analysis=False,
            block="stale_5m_bars",
            block_a="stale_5m_bars",
            latest_1m=latest_1m,
            latest_5m=latest_5m,
            b1a=bool(b1),
            b5a=bool(b5),
            vwap=False,
            ora=False,
            atr=False,
            session_day=latest_session,
            expected_5m=expected_5m_start,
            stale_ref=stale_5m_ref,
            stale_seconds=stale_5m_seconds,
            stale_flag=stale_5m,
        )

    ar_reason, b1a, b5a, vwap_ok, or_ok, atr_ok = _metrics_reason_and_flags(
        b1=b1,
        b5=b5,
        latest_1m=latest_1m,
        latest_5m=latest_5m,
        settings=settings,
        current=current,
    )

    analysis_ready = ar_reason == "none"
    block_analysis = ar_reason
    if analysis_ready and not rth_open and latest_session is not None and latest_session != expected_session:
        analysis_ready = False
        block_analysis = "prior_session_data"

    if analysis_ready and not rth_open:
        block_analysis = "latest_session_complete"

    live_ready = bool(
        rth_open
        and analysis_ready
        and block_analysis in ("none", "latest_session_complete")
        and dxlink.connected
        and dxlink.subscribed
    )

    if not analysis_ready:
        return _readiness(
            live=False,
            analysis=False,
            block=ar_reason,
            block_a=block_analysis,
            latest_1m=latest_1m,
            latest_5m=latest_5m,
            b1a=b1a,
            b5a=b5a,
            vwap=vwap_ok,
            ora=or_ok,
            atr=atr_ok,
            session_day=latest_session,
            expected_5m=expected_5m_start,
            stale_ref=stale_5m_ref,
            stale_seconds=stale_5m_seconds,
            stale_flag=stale_5m,
        )

    if not rth_open:
        return _readiness(
            live=False,
            analysis=True,
            block="market_closed",
            block_a=block_analysis,
            latest_1m=latest_1m,
            latest_5m=latest_5m,
            b1a=b1a,
            b5a=b5a,
            vwap=vwap_ok,
            ora=or_ok,
            atr=atr_ok,
            session_day=latest_session,
            expected_5m=expected_5m_start,
            stale_ref=stale_5m_ref,
            stale_seconds=stale_5m_seconds,
            stale_flag=stale_5m,
        )

    return _readiness(
        live=True,
        analysis=True,
        block="none",
        block_a="none",
        latest_1m=latest_1m,
        latest_5m=latest_5m,
        b1a=b1a,
        b5a=b5a,
        vwap=vwap_ok,
        ora=or_ok,
        atr=atr_ok,
        session_day=latest_session,
        expected_5m=expected_5m_start,
        stale_ref=stale_5m_ref,
        stale_seconds=stale_5m_seconds,
        stale_flag=stale_5m,
    )
