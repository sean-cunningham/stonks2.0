"""Optional background context refresh (not enabled by default)."""

from __future__ import annotations

import logging

from app.core.config import Settings
from app.core.database import SessionLocal
from app.services.market import bar_ingestion

logger = logging.getLogger(__name__)


def run_startup_context_refresh(settings: Settings) -> None:
    """If CONTEXT_STARTUP_REFRESH is true, ingest bars once at startup."""
    if not settings.CONTEXT_STARTUP_REFRESH:
        return
    db = SessionLocal()
    try:
        n1, n5, src = bar_ingestion.ingest_spy_intraday_safe(db, settings)
        logger.info("Startup context bar refresh: 1m=%s 5m=%s source=%s", n1, n5, src)
    finally:
        db.close()
