from __future__ import annotations

import logging

from app.core.config import Settings
from app.core.database import SessionLocal
from app.services.market.market_store import MarketStoreService

logger = logging.getLogger(__name__)


def run_startup_market_refresh(settings: Settings) -> None:
    """Attempt one startup refresh so readiness is immediately visible."""
    db = SessionLocal()
    try:
        service = MarketStoreService(db=db, settings=settings)
        result = service.refresh_spy()
        logger.info(
            "Startup market refresh: refreshed=%s quote=%s chain=%s ready=%s reason=%s",
            result.refreshed,
            result.quote_refreshed,
            result.chain_refreshed,
            result.status.market_ready,
            result.status.block_reason,
        )
    except Exception as exc:
        logger.warning("Startup market refresh failed: %s", exc)
    finally:
        db.close()

