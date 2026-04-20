"""Fetch and persist SPY intraday bars from real sources (no synthetic data)."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.bars import IntradayBar
from app.repositories.bars_repository import BarsRepository
from app.services.broker.tastytrade_auth import BrokerAuthError, TastytradeAuthService
from app.services.market.adapters import tastytrade_intraday_bars, yahoo_finance_chart_bars

logger = logging.getLogger(__name__)


class BarIngestionError(Exception):
    """Raised when no real bar source produced data."""


def _fetch_yahoo(settings: Settings) -> tuple[list[IntradayBar], list[IntradayBar]]:
    bars_1m = yahoo_finance_chart_bars.fetch_spy_yahoo_bars(
        interval="1m",
        range_param=settings.SPY_YAHOO_CHART_RANGE,
        user_agent=settings.YAHOO_CHART_USER_AGENT,
    )
    bars_5m = yahoo_finance_chart_bars.fetch_spy_yahoo_bars(
        interval="5m",
        range_param=settings.SPY_YAHOO_CHART_RANGE,
        user_agent=settings.YAHOO_CHART_USER_AGENT,
    )
    return bars_1m, bars_5m


def _fetch_tastytrade(settings: Settings) -> tuple[list[IntradayBar], list[IntradayBar]]:
    auth = TastytradeAuthService(settings)
    if not auth.has_credentials() or not settings.TASTYTRADE_API_BASE_URL:
        return [], []
    token = auth.get_access_token()
    bars_1m = tastytrade_intraday_bars.fetch_spy_tastytrade_bars(
        api_base_url=settings.TASTYTRADE_API_BASE_URL,
        access_token=token.access_token,
        interval="1m",
    )
    bars_5m = tastytrade_intraday_bars.fetch_spy_tastytrade_bars(
        api_base_url=settings.TASTYTRADE_API_BASE_URL,
        access_token=token.access_token,
        interval="5m",
    )
    return bars_1m, bars_5m


def ingest_spy_intraday(
    db: Session,
    settings: Settings,
) -> tuple[int, int, str]:
    """
    Fetch 1m and 5m SPY bars and persist.

    Returns (count_1m, count_5m, bars_source_label).
    """
    mode = settings.SPY_INTRADAY_BARS_SOURCE
    bars_1m: list[IntradayBar] = []
    bars_5m: list[IntradayBar] = []
    used_source = "none"

    if mode == "yahoo":
        bars_1m, bars_5m = _fetch_yahoo(settings)
        used_source = "yahoo_finance_chart_v8"
    elif mode == "tastytrade":
        try:
            bars_1m, bars_5m = _fetch_tastytrade(settings)
        except BrokerAuthError as exc:
            raise BarIngestionError(str(exc)) from exc
        used_source = "tastytrade_rest"
    else:
        # auto: prefer Tastytrade REST if credentials yield bars; else Yahoo.
        try:
            bars_1m, bars_5m = _fetch_tastytrade(settings)
            if bars_1m and bars_5m:
                used_source = "tastytrade_rest"
        except BrokerAuthError as exc:
            logger.info("Tastytrade bars unavailable in auto mode: %s", exc)
        if not bars_1m or not bars_5m:
            bars_1m, bars_5m = _fetch_yahoo(settings)
            used_source = "yahoo_finance_chart_v8"

    if not bars_1m or not bars_5m:
        raise BarIngestionError("no_real_bars_available")

    cap = settings.CONTEXT_MAX_BARS_PERSISTED_PER_TF
    if cap > 0:
        bars_1m = bars_1m[-cap:]
        bars_5m = bars_5m[-cap:]

    repo = BarsRepository(db)
    n1 = repo.upsert_bars(bars_1m)
    n5 = repo.upsert_bars(bars_5m)
    logger.info("SPY bar ingestion complete source=%s 1m=%s 5m=%s", used_source, n1, n5)
    return n1, n5, used_source


def ingest_spy_intraday_safe(
    db: Session,
    settings: Settings,
) -> tuple[int, int, str]:
    """Same as ingest_spy_intraday but never raises; returns zeros on failure."""
    try:
        return ingest_spy_intraday(db, settings)
    except BarIngestionError as exc:
        logger.warning("SPY bar ingestion failed: %s", exc)
        return 0, 0, f"failed:{exc}"
