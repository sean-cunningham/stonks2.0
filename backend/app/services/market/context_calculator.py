"""
Compute Strategy 1-lite market structure context from persisted SPY bars.

Formulas (documented):
- Session VWAP (RTH today, ET calendar date of latest bar):
  For each bar in chronological order, typical price tp = (high + low + close) / 3.
  cumulative_pv += tp * volume, cumulative_v += volume (skip bars with null/zero volume).
  VWAP = cumulative_pv / cumulative_v when cumulative_v > 0.

- ATR(14) on 5m completed bars (Wilder / RMA smoothing, standard):
  True Range TR_i = max(high_i - low_i, |high_i - close_{i-1}|, |low_i - close_{i-1}|).
  First bar uses TR = high - low.
  ATR_14 = mean(TR_1..TR_14) for the initial value at index 13 (0-based).
  Subsequent: ATR_i = (ATR_{i-1} * 13 + TR_i) / 14.

- Opening range: max high / min low over first N minutes of RTH (default N=30), ET.

- Swing high/low: most recent pivot on completed 5m bars:
  pivot high at i if high[i] > high[i-1] and high[i] > high[i+1]; take latest such i.
  pivot low symmetric. Requires at least 3 completed bars.

Relative volume: current bar volume / SMA(volume, 20) of prior 20 completed bars; unavailable if <20 priors.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models.bars import IntradayBar

ET = ZoneInfo("America/New_York")
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)


@dataclass
class ContextMetrics:
    """Computed numeric context."""

    latest_price: float | None
    session_vwap: float | None
    opening_range_high: float | None
    opening_range_low: float | None
    latest_5m_atr: float | None
    recent_swing_high: float | None
    recent_swing_low: float | None
    relative_volume_5m: float | None
    relative_volume_available: bool


def bars_source_from_rows(bars: list[IntradayBar]) -> str:
    """Infer provider label from persisted bar rows."""
    if not bars:
        return "none"
    raw = (bars[-1].source_status or "").split(";", 1)[0]
    return raw or "unknown"


def to_et(dt: datetime) -> datetime:
    """Convert aware UTC (or naive treated as UTC) to America/New_York."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ET)


def is_rth_bar(bar_time: datetime) -> bool:
    """True if bar open time lies within regular session in ET (same calendar day rule)."""
    local = to_et(bar_time)
    t = local.time()
    return RTH_OPEN <= t < RTH_CLOSE


def session_date_et(bar_time: datetime) -> date:
    """Equity regular-session 'day' in ET for grouping."""
    return to_et(bar_time).date()


def filter_rth_bars_on_session_day(bars: list[IntradayBar], session_day: date) -> list[IntradayBar]:
    """Keep RTH bars whose ET calendar date equals session_day."""
    out: list[IntradayBar] = []
    for bar in bars:
        if not is_rth_bar(bar.bar_time):
            continue
        if session_date_et(bar.bar_time) == session_day:
            out.append(bar)
    out.sort(key=lambda b: b.bar_time)
    return out


def compute_typical_price(bar: IntradayBar) -> float:
    """(H+L+C)/3."""
    return (bar.high + bar.low + bar.close) / 3.0


def compute_session_vwap(bars_rth: list[IntradayBar]) -> float | None:
    """Session VWAP from HLC3 * volume / cumulative volume."""
    cum_pv = 0.0
    cum_v = 0.0
    for bar in bars_rth:
        if bar.volume is None or bar.volume <= 0:
            continue
        tp = compute_typical_price(bar)
        cum_pv += tp * float(bar.volume)
        cum_v += float(bar.volume)
    if cum_v <= 0:
        return None
    return cum_pv / cum_v


def compute_opening_range(
    bars_5m_rth: list[IntradayBar],
    *,
    opening_range_minutes: int,
) -> tuple[float | None, float | None]:
    """OR high/low over first N minutes of RTH."""
    if not bars_5m_rth:
        return None, None
    session_day = session_date_et(bars_5m_rth[0].bar_time)
    open_dt = datetime.combine(session_day, RTH_OPEN, tzinfo=ET)
    cutoff = open_dt + timedelta(minutes=opening_range_minutes)
    highs: list[float] = []
    lows: list[float] = []
    for bar in bars_5m_rth:
        bt = to_et(bar.bar_time)
        if bt < open_dt or bt >= cutoff:
            continue
        highs.append(bar.high)
        lows.append(bar.low)
    if not highs or not lows:
        return None, None
    return max(highs), min(lows)


def completed_5m_bars(bars_5m_rth: list[IntradayBar], now: datetime) -> list[IntradayBar]:
    """Exclude the current incomplete 5m bucket."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    completed: list[IntradayBar] = []
    for bar in bars_5m_rth:
        start = bar.bar_time if bar.bar_time.tzinfo else bar.bar_time.replace(tzinfo=timezone.utc)
        end = start + timedelta(minutes=5)
        if end <= now:
            completed.append(bar)
    return completed


def compute_recent_swings(completed_5m: list[IntradayBar]) -> tuple[float | None, float | None]:
    """Most recent pivot high and pivot low."""
    if len(completed_5m) < 3:
        return None, None
    highs: list[float | None] = [None] * len(completed_5m)
    lows: list[float | None] = [None] * len(completed_5m)
    for i in range(1, len(completed_5m) - 1):
        h_prev = completed_5m[i - 1].high
        h = completed_5m[i].high
        h_next = completed_5m[i + 1].high
        if h > h_prev and h > h_next:
            highs[i] = h
        l_prev = completed_5m[i - 1].low
        l = completed_5m[i].low
        l_next = completed_5m[i + 1].low
        if l < l_prev and l < l_next:
            lows[i] = l
    swing_high = None
    swing_low = None
    for i in range(len(highs) - 1, -1, -1):
        if highs[i] is not None:
            swing_high = highs[i]
            break
    for i in range(len(lows) - 1, -1, -1):
        if lows[i] is not None:
            swing_low = lows[i]
            break
    return swing_high, swing_low


def compute_atr14_wilder(completed_5m: list[IntradayBar]) -> float | None:
    """ATR(14) Wilder on completed 5m bars."""
    if len(completed_5m) < 15:
        return None
    trs: list[float] = []
    for i, bar in enumerate(completed_5m):
        if i == 0:
            trs.append(bar.high - bar.low)
            continue
        prev_close = completed_5m[i - 1].close
        tr = max(
            bar.high - bar.low,
            abs(bar.high - prev_close),
            abs(bar.low - prev_close),
        )
        trs.append(tr)
    if len(trs) < 14:
        return None
    atr = sum(trs[:14]) / 14.0
    for tr in trs[14:]:
        atr = (atr * 13.0 + tr) / 14.0
    return atr


def compute_atr_early_available_bars(completed_5m: list[IntradayBar]) -> float | None:
    """
    Early-session ATR estimate from available completed 5m bars.

    Uses the same true-range definition as ATR(14), but computes a simple average
    over available completed bars when there are at least 6 and fewer than 15 bars.
    """
    n = len(completed_5m)
    if n < 6:
        return None
    if n >= 15:
        return compute_atr14_wilder(completed_5m)
    trs: list[float] = []
    for i, bar in enumerate(completed_5m):
        if i == 0:
            trs.append(bar.high - bar.low)
            continue
        prev_close = completed_5m[i - 1].close
        tr = max(
            bar.high - bar.low,
            abs(bar.high - prev_close),
            abs(bar.low - prev_close),
        )
        trs.append(tr)
    if not trs:
        return None
    return sum(trs) / float(len(trs))


def compute_relative_volume(completed_5m: list[IntradayBar]) -> tuple[float | None, bool]:
    """Last completed bar volume vs SMA(20) of prior volumes."""
    if len(completed_5m) < 21:
        return None, False
    last = completed_5m[-1]
    if last.volume is None or last.volume <= 0:
        return None, False
    prior = completed_5m[-21:-1]
    vols = [b.volume for b in prior if b.volume is not None and b.volume > 0]
    if len(vols) < 20:
        return None, False
    sma20 = sum(float(v) for v in vols[-20:]) / 20.0
    if sma20 <= 0:
        return None, False
    return float(last.volume) / sma20, True


def compute_context_metrics(
    *,
    bars_1m: list[IntradayBar],
    bars_5m: list[IntradayBar],
    now: datetime,
    opening_range_minutes: int,
) -> ContextMetrics:
    """Compute all metrics; may return None fields when not computable."""
    if not bars_1m or not bars_5m:
        return ContextMetrics(
            latest_price=None,
            session_vwap=None,
            opening_range_high=None,
            opening_range_low=None,
            latest_5m_atr=None,
            recent_swing_high=None,
            recent_swing_low=None,
            relative_volume_5m=None,
            relative_volume_available=False,
        )

    latest_anchor = max(bars_1m[-1].bar_time, bars_5m[-1].bar_time)
    session_day = session_date_et(latest_anchor)

    rth_1m = filter_rth_bars_on_session_day(bars_1m, session_day)
    rth_5m = filter_rth_bars_on_session_day(bars_5m, session_day)

    latest_price = bars_1m[-1].close if rth_1m else None
    if latest_price is None and rth_5m:
        latest_price = rth_5m[-1].close

    vwap = compute_session_vwap(rth_1m) if rth_1m else None
    orh, orl = compute_opening_range(rth_5m, opening_range_minutes=opening_range_minutes)

    completed_5m = completed_5m_bars(rth_5m, now)
    atr = compute_atr14_wilder(completed_5m)
    if atr is None:
        atr = compute_atr_early_available_bars(completed_5m)
    swing_h, swing_l = compute_recent_swings(completed_5m)
    rel, rel_ok = compute_relative_volume(completed_5m)

    return ContextMetrics(
        latest_price=latest_price,
        session_vwap=vwap,
        opening_range_high=orh,
        opening_range_low=orl,
        latest_5m_atr=atr,
        recent_swing_high=swing_h,
        recent_swing_low=swing_l,
        relative_volume_5m=rel,
        relative_volume_available=rel_ok,
    )
