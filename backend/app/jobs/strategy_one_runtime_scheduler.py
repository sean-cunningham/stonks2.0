"""Recurring Strategy 1 paper scheduler aligned to completed 1-minute bar closes."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.core.database import SessionLocal
from app.services.market.context_service import ContextService
from app.services.market.market_store import MarketStoreService
from app.services.paper.strategy_one_runtime_service import get_strategy_one_runtime_coordinator

logger = logging.getLogger(__name__)


def seconds_until_next_minute_offset(*, now: datetime, offset_seconds: int) -> float:
    """Return sleep duration until next HH:MM:offset_seconds (UTC)."""
    clamped = max(1, min(offset_seconds, 59))
    target = now.replace(second=clamped, microsecond=0)
    if now >= target:
        target = target + timedelta(minutes=1)
    return max((target - now).total_seconds(), 0.05)


class StrategyOneRuntimeScheduler:
    """In-process scheduler. Lock safety is single-process only."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self._settings.STRATEGY1_PAPER_RUNTIME_ENABLED:
            logger.info("Strategy 1 paper runtime scheduler disabled by config.")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="strategy1-paper-runtime")
        self._thread.start()
        logger.info(
            "Strategy 1 paper runtime scheduler started (offset_second=%s).",
            self._settings.STRATEGY1_PAPER_EXECUTE_OFFSET_SECONDS,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("Strategy 1 paper runtime scheduler stopped.")

    def _run_loop(self) -> None:
        coord = get_strategy_one_runtime_coordinator()
        while not self._stop_event.is_set():
            now = datetime.now(timezone.utc)
            wait_s = seconds_until_next_minute_offset(
                now=now,
                offset_seconds=self._settings.STRATEGY1_PAPER_EXECUTE_OFFSET_SECONDS,
            )
            if self._stop_event.wait(timeout=wait_s):
                break
            db = SessionLocal()
            try:
                context = ContextService(db=db, settings=self._settings)
                market = MarketStoreService(db=db, settings=self._settings)
                coord.run_tick(db, context=context, market=market, settings=self._settings)
            except Exception as exc:
                logger.warning("Strategy 1 scheduler tick failed: %s", exc)
            finally:
                db.close()
