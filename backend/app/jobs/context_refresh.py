"""Optional startup 5m reaggregation from persisted DXLink 1m bars."""

from __future__ import annotations

import logging

from app.core.config import Settings
from app.core.database import SessionLocal
from app.services.market.bar_aggregate import DXLINK_BAR_SOURCE, reaggregate_spy_5m_from_db

logger = logging.getLogger(__name__)


def run_startup_context_refresh(settings: Settings) -> None:
    """If CONTEXT_STARTUP_REFRESH is true, rebuild 5m bars from 1m once at startup."""
    if not settings.CONTEXT_STARTUP_REFRESH:
        return
    db = SessionLocal()
    try:
        n5 = reaggregate_spy_5m_from_db(db, max_1m=settings.CONTEXT_MAX_BARS_PERSISTED_PER_TF)
        logger.info("Startup context 5m reaggregation: written=%s source=%s", n5, DXLINK_BAR_SOURCE)
    finally:
        db.close()
