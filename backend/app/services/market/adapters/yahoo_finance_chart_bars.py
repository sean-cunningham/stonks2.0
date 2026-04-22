"""
Yahoo Finance chart API (v8) — public, unauthenticated JSON.

Used only for SPY intraday OHLCV when Tastytrade REST bars are unavailable.
Documented upstream: Yahoo chart endpoint; not affiliated with Yahoo.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

import httpx

from app.models.bars import IntradayBar

logger = logging.getLogger(__name__)

YAHOO_CHART_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"


def fetch_spy_yahoo_bars(
    *,
    interval: Literal["1m", "5m"],
    range_param: str = "5d",
    user_agent: str,
) -> list[IntradayBar]:
    """
    Fetch real SPY bars from Yahoo chart API.

    Returns empty list if the response is unusable (no fake bars).
    """
    url = f"{YAHOO_CHART_BASE}/SPY?interval={interval}&range={range_param}"
    headers = {"User-Agent": user_agent}
    with httpx.Client(timeout=25.0, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        payload = response.json()

    chart = payload.get("chart", {})
    results = chart.get("result")
    if not results or not isinstance(results, list):
        logger.warning("Yahoo chart: missing result for SPY interval=%s", interval)
        return []

    result: dict[str, Any] = results[0]
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators", {}).get("quote", [{}])
    if not isinstance(timestamps, list) or not indicators:
        return []
    quote = indicators[0] if isinstance(indicators[0], dict) else {}

    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []

    bars: list[IntradayBar] = []
    for idx, ts in enumerate(timestamps):
        if ts is None:
            continue
        o = _idx(opens, idx)
        h = _idx(highs, idx)
        l = _idx(lows, idx)
        c = _idx(closes, idx)
        v = _idx(volumes, idx)
        if o is None or h is None or l is None or c is None:
            continue
        bar_time = datetime.fromtimestamp(int(ts), tz=timezone.utc)
        vol_f = float(v) if v is not None else None
        provider = "yahoo_finance_chart_v8"
        status = provider if vol_f is not None and vol_f > 0 else f"{provider};no_volume"
        bars.append(
            IntradayBar(
                symbol="SPY",
                timeframe=interval,
                bar_time=bar_time,
                open=float(o),
                high=float(h),
                low=float(l),
                close=float(c),
                volume=vol_f,
                source_status=status,
            )
        )
    bars.sort(key=lambda b: b.bar_time)
    logger.info("Yahoo chart: fetched %s bars interval=%s", len(bars), interval)
    return bars


def _idx(series: list[Any], idx: int) -> float | None:
    if idx >= len(series):
        return None
    val = series[idx]
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None
