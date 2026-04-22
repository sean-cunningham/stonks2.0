"""
Attempt to load SPY intraday bars from Tastytrade REST (if available).

Many environments only expose snapshots/streaming; this module tries a small
set of documented-style paths and returns nothing on failure (no synthetic bars).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

from app.models.bars import IntradayBar

logger = logging.getLogger(__name__)


def fetch_spy_tastytrade_bars(
    *,
    api_base_url: str,
    access_token: str,
    interval: Literal["1m", "5m"],
) -> list[IntradayBar]:
    """Return bars if a known endpoint succeeds; otherwise empty list."""
    headers = {"Authorization": f"Bearer {access_token}"}
    base = api_base_url.rstrip("/")
    interval_param = "1" if interval == "1m" else "5"
    paths = [
        f"/market-data/charts/equity/SPY?interval={interval_param}m",
        f"/market-data/equity-charts/SPY?interval={interval_param}m",
        f"/instruments/equities/SPY/candles?interval={interval_param}m",
    ]
    errors: list[str] = []
    with httpx.Client(timeout=20.0, headers=headers) as client:
        for path in paths:
            url = f"{base}{path}"
            try:
                response = client.get(url)
                response.raise_for_status()
                body = response.json()
            except httpx.HTTPError as exc:
                errors.append(f"{path}:{exc}")
                continue
            parsed = _parse_tastytrade_candles(body, timeframe=interval)
            if parsed:
                logger.info("Tastytrade bars: success path=%s count=%s", path, len(parsed))
                return parsed
    if errors:
        logger.info("Tastytrade bars: no usable endpoint (%s)", "; ".join(errors[:3]))
    return []


def _parse_tastytrade_candles(payload: dict[str, Any], timeframe: Literal["1m", "5m"]) -> list[IntradayBar]:
    """Best-effort parse; returns empty if shape unknown."""
    data = payload.get("data", payload)
    items = None
    if isinstance(data, dict):
        items = data.get("items") or data.get("candles") or data.get("chart")
    if not isinstance(items, list):
        return []

    bars: list[IntradayBar] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        ts = row.get("time") or row.get("timestamp") or row.get("start-time")
        o = row.get("open") or row.get("open-price")
        h = row.get("high") or row.get("high-price")
        l = row.get("low") or row.get("low-price")
        c = row.get("close") or row.get("close-price")
        v = row.get("volume")
        if ts is None or o is None or h is None or l is None or c is None:
            continue
        bar_time = _parse_ts(ts)
        if bar_time is None:
            continue
        vol = float(v) if v is not None else None
        provider = "tastytrade_rest"
        status = provider if vol is not None and vol > 0 else f"{provider};no_volume"
        bars.append(
            IntradayBar(
                symbol="SPY",
                timeframe=timeframe,
                bar_time=bar_time,
                open=float(o),
                high=float(h),
                low=float(l),
                close=float(c),
                volume=vol,
                source_status=status,
            )
        )
    bars.sort(key=lambda b: b.bar_time)
    return bars


def _parse_ts(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value) / (1000 if value > 1e12 else 1), tz=timezone.utc)
    if isinstance(value, str):
        candidate = value.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None
