"""Shared in-memory SPY quote history for short-window diagnostics."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import threading


@dataclass(frozen=True)
class SpyQuoteSample:
    timestamp_utc: datetime
    price: float
    source: str


class SpyQuoteBuffer:
    """Thread-safe rolling SPY quote sample buffer."""

    def __init__(self, *, max_age_seconds: int = 300) -> None:
        self._max_age = timedelta(seconds=max_age_seconds)
        self._samples: deque[SpyQuoteSample] = deque()
        self._lock = threading.Lock()

    @staticmethod
    def _as_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _prune_locked(self, now_utc: datetime) -> None:
        cutoff = now_utc - self._max_age
        while self._samples and self._samples[0].timestamp_utc < cutoff:
            self._samples.popleft()

    def append(self, *, timestamp: datetime, price: float, source: str) -> None:
        if price <= 0:
            return
        ts = self._as_utc(timestamp)
        sample = SpyQuoteSample(timestamp_utc=ts, price=float(price), source=str(source))
        with self._lock:
            self._samples.append(sample)
            self._prune_locked(ts)

    def get_latest(self) -> SpyQuoteSample | None:
        with self._lock:
            if not self._samples:
                return None
            return self._samples[-1]

    def get_delta(self, seconds: int) -> float | None:
        if seconds <= 0:
            return None
        with self._lock:
            if len(self._samples) < 2:
                return None
            latest = self._samples[-1]
            target = latest.timestamp_utc - timedelta(seconds=seconds)
            anchor: SpyQuoteSample | None = None
            for sample in reversed(self._samples):
                if sample.timestamp_utc <= target:
                    anchor = sample
                    break
            if anchor is None:
                return None
            return latest.price - anchor.price

    def get_micro_snapshot(self, *, atr_5m: float | None = None) -> dict[str, float | int | bool | str | None]:
        with self._lock:
            if not self._samples:
                return {
                    "latest_price": None,
                    "latest_timestamp": None,
                    "price_15s_ago": None,
                    "price_30s_ago": None,
                    "price_change_15s": None,
                    "price_change_30s": None,
                    "abs_price_change_15s": None,
                    "abs_price_change_30s": None,
                    "atr_fraction_30s": None,
                    "sample_count": 0,
                    "buffer_age_seconds": None,
                    "data_available_15s": False,
                    "data_available_30s": False,
                }
            latest = self._samples[-1]
            self._prune_locked(latest.timestamp_utc)

            def _pick_price_ago(sec: int) -> float | None:
                target = latest.timestamp_utc - timedelta(seconds=sec)
                for sample in reversed(self._samples):
                    if sample.timestamp_utc <= target:
                        return sample.price
                return None

            p15 = _pick_price_ago(15)
            p30 = _pick_price_ago(30)
            d15 = (latest.price - p15) if p15 is not None else None
            d30 = (latest.price - p30) if p30 is not None else None
            atr_fraction_30s = None
            if atr_5m is not None and atr_5m > 0 and d30 is not None:
                atr_fraction_30s = abs(d30) / float(atr_5m)
            age_seconds = (latest.timestamp_utc - self._samples[0].timestamp_utc).total_seconds() if self._samples else None

            return {
                "latest_price": latest.price,
                "latest_timestamp": latest.timestamp_utc.isoformat(),
                "price_15s_ago": p15,
                "price_30s_ago": p30,
                "price_change_15s": d15,
                "price_change_30s": d30,
                "abs_price_change_15s": abs(d15) if d15 is not None else None,
                "abs_price_change_30s": abs(d30) if d30 is not None else None,
                "atr_fraction_30s": atr_fraction_30s,
                "sample_count": len(self._samples),
                "buffer_age_seconds": age_seconds,
                "data_available_15s": p15 is not None,
                "data_available_30s": p30 is not None,
            }


_spy_quote_buffer = SpyQuoteBuffer()


def get_spy_quote_buffer() -> SpyQuoteBuffer:
    return _spy_quote_buffer

