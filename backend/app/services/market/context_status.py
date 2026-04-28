"""Context readiness from persisted DXLink bars, stream health, and session-aware freshness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal

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


def _expected_latest_completed_1m_start(now_utc: datetime) -> datetime:
    """
    Latest *completed* 1m bar open time (bar_time) implied by wall clock.

    Bars use the candle open / period start as bar_time. The bar for [T, T+1m) completes
    at T+1m, so at `now` the latest completed bar_time is floor(now to minute) minus 1 minute.
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    now_utc = now_utc.astimezone(timezone.utc)
    minute_floor = now_utc.replace(second=0, microsecond=0)
    return minute_floor - timedelta(minutes=1)


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
    expected_latest_completed_1m_start: datetime | None = None
    stale_1m_reference_time: datetime | None = None
    stale_1m_seconds: float | None = None
    stale_1m_boolean: bool = False
    expected_latest_completed_5m_start: datetime | None = None
    stale_5m_reference_time: datetime | None = None
    stale_5m_seconds: float | None = None
    stale_5m_boolean: bool = False
    completed_5m_bar_count: int = 0
    context_session_mode: Literal["none", "early", "mature"] = "none"
    early_session_ready: bool = False
    mature_session_ready: bool = False
    atr_mode: Literal["none", "early_available_bars", "atr14"] = "none"


def _metrics_reason_and_flags(
    *,
    b1: list[IntradayBar],
    b5: list[IntradayBar],
    latest_1m: datetime | None,
    latest_5m: datetime | None,
    settings: Settings,
    current: datetime,
) -> tuple[str, bool, bool, bool, bool, bool, int, str, bool, bool, str]:
    """
    Returns:
      (analysis_block_reason, bars_1m_ok, bars_5m_ok, vwap_ok, or_ok, atr_ok,
       completed_5m_count, context_session_mode, early_session_ready,
       mature_session_ready, atr_mode).

    analysis_block_reason is 'none' when analysis metrics are computable on the anchor session.
    """
    if not b1:
        return "bars_not_initialized", False, bool(b5), False, False, False, 0, "none", False, False, "none"
    if not b5:
        return "insufficient_5m_bars", True, False, False, False, False, 0, "none", False, False, "none"

    anchor = latest_1m or latest_5m
    if anchor is None:
        return "bars_not_initialized", False, False, False, False, False, 0, "none", False, False, "none"

    session_day = context_calculator.session_date_et(anchor)
    rth_1m = context_calculator.filter_rth_bars_on_session_day(b1, session_day)
    rth_5m = context_calculator.filter_rth_bars_on_session_day(b5, session_day)

    if not rth_1m or not rth_5m:
        return "insufficient_1m_bars", True, True, False, False, False, 0, "none", False, False, "none"

    if len(rth_1m) < 5:
        return "insufficient_1m_bars", True, True, False, False, False, 0, "none", False, False, "none"

    vwap_ok = context_calculator.compute_session_vwap(rth_1m) is not None
    orh, orl = context_calculator.compute_opening_range(
        rth_5m,
        opening_range_minutes=settings.OPENING_RANGE_MINUTES,
    )
    or_ok = orh is not None and orl is not None

    completed_5m = context_calculator.completed_5m_bars(rth_5m, current)
    completed_5m_count = len(completed_5m)
    early_atr_ok = context_calculator.compute_atr_early_available_bars(completed_5m) is not None
    atr_ok = context_calculator.compute_atr14_wilder(completed_5m) is not None
    swing_ok = context_calculator.compute_recent_swings(completed_5m)[0] is not None
    early_ready = bool(vwap_ok and or_ok and swing_ok and early_atr_ok and completed_5m_count >= 6)
    mature_ready = bool(vwap_ok and or_ok and atr_ok and swing_ok and completed_5m_count >= 15)
    if completed_5m_count >= 15:
        session_mode = "mature"
        atr_mode = "atr14"
    elif completed_5m_count >= 6:
        session_mode = "early"
        atr_mode = "early_available_bars" if early_atr_ok else "none"
    else:
        session_mode = "none"
        atr_mode = "none"

    if not vwap_ok:
        reason = "insufficient_1m_bars"
    elif not or_ok:
        reason = "insufficient_5m_bars"
    elif completed_5m_count < 6:
        reason = "insufficient_5m_bars"
    elif completed_5m_count < 15:
        reason = "none" if early_ready else "insufficient_5m_bars"
    elif not atr_ok:
        reason = "insufficient_5m_bars"
    elif not swing_ok:
        reason = "insufficient_5m_bars"
    else:
        reason = "none"

    return (
        reason,
        True,
        True,
        vwap_ok,
        or_ok,
        atr_ok,
        completed_5m_count,
        session_mode,
        early_ready,
        mature_ready,
        atr_mode,
    )


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
        expected_1m: datetime | None = None,
        stale_1m_ref: datetime | None = None,
        stale_1m_secs: float | None = None,
        stale_1m_flag: bool = False,
        expected_5m: datetime | None = None,
        stale_ref: datetime | None = None,
        stale_seconds: float | None = None,
        stale_flag: bool = False,
        completed_5m_count: int = 0,
        session_mode: Literal["none", "early", "mature"] = "none",
        early_ready: bool = False,
        mature_ready: bool = False,
        atr_mode: Literal["none", "early_available_bars", "atr14"] = "none",
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
            expected_latest_completed_1m_start=expected_1m,
            stale_1m_reference_time=stale_1m_ref,
            stale_1m_seconds=stale_1m_secs,
            stale_1m_boolean=stale_1m_flag,
            expected_latest_completed_5m_start=expected_5m,
            stale_5m_reference_time=stale_ref,
            stale_5m_seconds=stale_seconds,
            stale_5m_boolean=stale_flag,
            completed_5m_bar_count=completed_5m_count,
            context_session_mode=session_mode,
            early_session_ready=early_ready,
            mature_session_ready=mature_ready,
            atr_mode=atr_mode,
        )

    b1 = _dxlink_bars_only(bars_1m)
    b5 = _dxlink_bars_only(bars_5m)

    latest_1m = _as_utc_aware(b1[-1].bar_time) if b1 else None
    latest_5m = _as_utc_aware(b5[-1].bar_time) if b5 else None
    latest_session = context_calculator.session_date_et(latest_1m) if latest_1m else None
    completed_5m_count_snapshot = 0
    session_mode_snapshot: Literal["none", "early", "mature"] = "none"
    early_ready_snapshot = False
    mature_ready_snapshot = False
    atr_mode_snapshot: Literal["none", "early_available_bars", "atr14"] = "none"
    if latest_session is not None:
        rth_1m_snapshot = context_calculator.filter_rth_bars_on_session_day(b1, latest_session)
        rth_5m_snapshot = context_calculator.filter_rth_bars_on_session_day(b5, latest_session)
        completed_5m_snapshot = context_calculator.completed_5m_bars(rth_5m_snapshot, current)
        completed_5m_count_snapshot = len(completed_5m_snapshot)
        vwap_snapshot_ok = bool(rth_1m_snapshot) and context_calculator.compute_session_vwap(rth_1m_snapshot) is not None
        orh_snapshot, orl_snapshot = context_calculator.compute_opening_range(
            rth_5m_snapshot,
            opening_range_minutes=settings.OPENING_RANGE_MINUTES,
        )
        or_snapshot_ok = orh_snapshot is not None and orl_snapshot is not None
        atr_early_snapshot_ok = context_calculator.compute_atr_early_available_bars(completed_5m_snapshot) is not None
        atr14_snapshot_ok = context_calculator.compute_atr14_wilder(completed_5m_snapshot) is not None
        swing_snapshot_ok = context_calculator.compute_recent_swings(completed_5m_snapshot)[0] is not None
        early_ready_snapshot = bool(
            completed_5m_count_snapshot >= 6
            and vwap_snapshot_ok
            and or_snapshot_ok
            and atr_early_snapshot_ok
            and swing_snapshot_ok
        )
        mature_ready_snapshot = bool(
            completed_5m_count_snapshot >= 15
            and vwap_snapshot_ok
            and or_snapshot_ok
            and atr14_snapshot_ok
            and swing_snapshot_ok
        )
        if completed_5m_count_snapshot >= 15:
            session_mode_snapshot = "mature"
            atr_mode_snapshot = "atr14"
        elif completed_5m_count_snapshot >= 6:
            session_mode_snapshot = "early"
            atr_mode_snapshot = "early_available_bars" if atr_early_snapshot_ok else "none"

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
            expected_1m=None,
            stale_1m_ref=None,
            stale_1m_secs=None,
            stale_1m_flag=False,
            completed_5m_count=completed_5m_count_snapshot,
            session_mode=session_mode_snapshot,
            early_ready=early_ready_snapshot,
            mature_ready=mature_ready_snapshot,
            atr_mode=atr_mode_snapshot,
        )

    age_1m = (current - latest_1m).total_seconds() if latest_1m else None
    age_5m = (current - latest_5m).total_seconds() if latest_5m else None
    stale_1m = age_1m is None or age_1m > settings.CONTEXT_BAR_MAX_STALENESS_SECONDS_1M
    stale_5m = age_5m is None or age_5m > settings.CONTEXT_BAR_MAX_STALENESS_SECONDS_5M
    expected_1m_start: datetime | None = None
    stale_1m_ref: datetime | None = current
    stale_1m_seconds: float | None = age_1m
    expected_5m_start: datetime | None = None
    stale_5m_ref: datetime | None = current
    stale_5m_seconds: float | None = age_5m
    if rth_open and latest_1m is not None:
        expected_1m_start = _expected_latest_completed_1m_start(current)
        # RTH: 1m bars are labeled by period start; natural lag vs wall clock reaches ~120s at end
        # of the in-progress minute. Compare latest persisted open time to the expected completed bar.
        stale_1m = latest_1m < expected_1m_start
        stale_1m_ref = expected_1m_start
        stale_1m_seconds = max((expected_1m_start - latest_1m).total_seconds(), 0.0)
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
            expected_1m=expected_1m_start,
            stale_1m_ref=stale_1m_ref,
            stale_1m_secs=stale_1m_seconds,
            stale_1m_flag=stale_1m,
            expected_5m=expected_5m_start,
            stale_ref=stale_5m_ref,
            stale_seconds=stale_5m_seconds,
            stale_flag=stale_5m,
            completed_5m_count=completed_5m_count_snapshot,
            session_mode=session_mode_snapshot,
            early_ready=early_ready_snapshot,
            mature_ready=mature_ready_snapshot,
            atr_mode=atr_mode_snapshot,
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
            expected_1m=expected_1m_start,
            stale_1m_ref=stale_1m_ref,
            stale_1m_secs=stale_1m_seconds,
            stale_1m_flag=stale_1m,
            expected_5m=expected_5m_start,
            stale_ref=stale_5m_ref,
            stale_seconds=stale_5m_seconds,
            stale_flag=stale_5m,
            completed_5m_count=completed_5m_count_snapshot,
            session_mode=session_mode_snapshot,
            early_ready=early_ready_snapshot,
            mature_ready=mature_ready_snapshot,
            atr_mode=atr_mode_snapshot,
        )

    (
        ar_reason,
        b1a,
        b5a,
        vwap_ok,
        or_ok,
        atr_ok,
        completed_5m_count,
        session_mode,
        early_ready,
        mature_ready,
        atr_mode,
    ) = _metrics_reason_and_flags(
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
            expected_1m=expected_1m_start,
            stale_1m_ref=stale_1m_ref,
            stale_1m_secs=stale_1m_seconds,
            stale_1m_flag=stale_1m,
            expected_5m=expected_5m_start,
            stale_ref=stale_5m_ref,
            stale_seconds=stale_5m_seconds,
            stale_flag=stale_5m,
            completed_5m_count=completed_5m_count,
            session_mode=session_mode,
            early_ready=early_ready,
            mature_ready=mature_ready,
            atr_mode=atr_mode,
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
            expected_1m=expected_1m_start,
            stale_1m_ref=stale_1m_ref,
            stale_1m_secs=stale_1m_seconds,
            stale_1m_flag=stale_1m,
            expected_5m=expected_5m_start,
            stale_ref=stale_5m_ref,
            stale_seconds=stale_5m_seconds,
            stale_flag=stale_5m,
            completed_5m_count=completed_5m_count,
            session_mode=session_mode,
            early_ready=early_ready,
            mature_ready=mature_ready,
            atr_mode=atr_mode,
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
        expected_1m=expected_1m_start,
        stale_1m_ref=stale_1m_ref,
        stale_1m_secs=stale_1m_seconds,
        stale_1m_flag=stale_1m,
        expected_5m=expected_5m_start,
        stale_ref=stale_5m_ref,
        stale_seconds=stale_5m_seconds,
        stale_flag=stale_5m,
        completed_5m_count=completed_5m_count,
        session_mode=session_mode,
        early_ready=early_ready,
        mature_ready=mature_ready,
        atr_mode=atr_mode,
    )
