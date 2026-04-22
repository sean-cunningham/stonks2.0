"""Deterministic 5m OHLCV aggregation from completed 1m SPY bars (DXLink path)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models.bars import IntradayBar

ET = ZoneInfo("America/New_York")

DXLINK_BAR_SOURCE = "tastytrade_dxlink_candle"


def is_five_minute_bucket_start(bar_time: datetime) -> bool:
    """True if this 1m bar opens exactly at a 5-minute boundary in America/New_York."""
    if bar_time.tzinfo is None:
        bar_time = bar_time.replace(tzinfo=timezone.utc)
    et = bar_time.astimezone(ET)
    return et.second == 0 and et.microsecond == 0 and et.minute % 5 == 0


def five_minute_bucket_start_utc(one_minute_bar_time: datetime) -> datetime:
    """Floor bar open time to the start of its 5-minute ET bucket, returned as UTC-aware."""
    if one_minute_bar_time.tzinfo is None:
        one_minute_bar_time = one_minute_bar_time.replace(tzinfo=timezone.utc)
    et = one_minute_bar_time.astimezone(ET)
    floored = et.replace(minute=(et.minute // 5) * 5, second=0, microsecond=0)
    return floored.astimezone(timezone.utc)


def five_consecutive_1m_bars_for_bucket(
    bucket_start_utc: datetime,
    bars: list[IntradayBar],
) -> list[IntradayBar] | None:
    """
    Return the five 1m bars covering [bucket_start, bucket_start+5m) if all exist
    and are consecutive 1-minute steps; else None.
    """
    if len(bars) != 5:
        return None
    ordered = sorted(bars, key=lambda b: b.bar_time)
    start = bucket_start_utc.astimezone(timezone.utc)
    for i, bar in enumerate(ordered):
        expected = start + timedelta(minutes=i)
        bt = bar.bar_time if bar.bar_time.tzinfo else bar.bar_time.replace(tzinfo=timezone.utc)
        bt = bt.astimezone(timezone.utc)
        if bt.replace(microsecond=0) != expected.replace(microsecond=0):
            return None
    return ordered


def aggregate_1m_to_5m_bar(one_m_bars: list[IntradayBar]) -> IntradayBar | None:
    """Build one completed 5m bar from exactly five consecutive 1m bars."""
    if len(one_m_bars) != 5:
        return None
    ordered = sorted(one_m_bars, key=lambda b: b.bar_time)
    o = ordered[0].open
    h = max(b.high for b in ordered)
    l = min(b.low for b in ordered)
    c = ordered[-1].close
    vol_parts: list[float] = []
    for b in ordered:
        if b.volume is not None:
            vol_parts.append(float(b.volume))
    volume = sum(vol_parts) if vol_parts else None
    bucket = five_minute_bucket_start_utc(ordered[0].bar_time)
    return IntradayBar(
        symbol="SPY",
        timeframe="5m",
        bar_time=bucket,
        open=o,
        high=h,
        low=l,
        close=c,
        volume=volume,
        source_status=DXLINK_BAR_SOURCE,
    )


def reaggregate_spy_5m_from_db(db: Session, *, max_1m: int) -> int:
    """
    Scan recent SPY 1m bars and upsert completed 5m bars where five consecutive
    1m bars exist starting on a 5-minute ET boundary.
    """
    from app.repositories.bars_repository import BarsRepository

    repo = BarsRepository(db)
    raw = repo.list_recent_bars(symbol="SPY", timeframe="1m", limit=max_1m)
    one = [b for b in raw if (b.source_status or "").startswith(DXLINK_BAR_SOURCE)]
    if len(one) < 5:
        return 0
    written = 0
    seen_buckets: set[datetime] = set()
    for i in range(0, len(one) - 4):
        window = one[i : i + 5]
        b0 = window[0].bar_time
        if not is_five_minute_bucket_start(b0):
            continue
        bucket = five_minute_bucket_start_utc(b0)
        if bucket in seen_buckets:
            continue
        subset = five_consecutive_1m_bars_for_bucket(bucket, window)
        if subset is None:
            continue
        five_bar = aggregate_1m_to_5m_bar(subset)
        if five_bar is None:
            continue
        repo.upsert_bars([five_bar])
        seen_buckets.add(bucket)
        written += 1
    return written
