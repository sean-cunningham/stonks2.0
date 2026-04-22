"""SPY intraday bars: 1m from DXLink streamer only; 5m derived locally (recompute here)."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.market.bar_aggregate import DXLINK_BAR_SOURCE, reaggregate_spy_5m_from_db

logger = logging.getLogger(__name__)


class BarIngestionError(Exception):
    """Raised when bar maintenance cannot run (e.g. database error)."""


def ingest_spy_intraday(
    db: Session,
    settings: Settings,
) -> tuple[int, int, str]:
    """
    Recompute 5m bars from persisted 1m DXLink bars (no external HTTP).

    Returns (bars_1m_written, bars_5m_written, bars_source_label).
    """
    try:
        n5 = reaggregate_spy_5m_from_db(db, max_1m=settings.CONTEXT_MAX_BARS_PERSISTED_PER_TF)
    except Exception as exc:  # noqa: BLE001
        logger.warning("SPY 5m reaggregation failed: %s", exc)
        raise BarIngestionError("reaggregate_failed") from exc
    logger.info("SPY bar reaggregation complete 5m_written=%s source=%s", n5, DXLINK_BAR_SOURCE)
    return 0, n5, DXLINK_BAR_SOURCE


def ingest_spy_intraday_safe(
    db: Session,
    settings: Settings,
) -> tuple[int, int, str]:
    """Same as ingest_spy_intraday but never raises; returns zeros on failure."""
    try:
        return ingest_spy_intraday(db, settings)
    except BarIngestionError as exc:
        logger.warning("SPY bar reaggregation failed: %s", exc)
        return 0, 0, f"failed:{exc}"
