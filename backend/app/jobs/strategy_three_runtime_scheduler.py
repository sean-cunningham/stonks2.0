"""Recurring Strategy 3 paper scheduler with independent entry/exit cadences."""

from __future__ import annotations

import logging
import threading
import time

from app.core.config import Settings
from app.core.database import SessionLocal
from app.services.market.context_service import ContextService
from app.services.market.market_store import MarketStoreService
from app.services.paper.strategy_three_runtime_service import get_strategy_three_runtime_coordinator

logger = logging.getLogger(__name__)


class StrategyThreeRuntimeScheduler:
    """In-process scheduler with separate entry and exit intervals."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self._settings.STRATEGY3_PAPER_RUNTIME_ENABLED:
            logger.info("Strategy 3 paper runtime scheduler disabled by config.")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="strategy3-paper-runtime")
        self._thread.start()
        logger.info(
            "Strategy 3 paper runtime scheduler started (entry=%ss exit=%ss).",
            self._settings.STRATEGY3_PAPER_ENTRY_INTERVAL_SECONDS,
            self._settings.STRATEGY3_PAPER_EXIT_INTERVAL_SECONDS,
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        logger.info("Strategy 3 paper runtime scheduler stopped.")

    def _run_loop(self) -> None:
        coord = get_strategy_three_runtime_coordinator()
        next_entry = time.monotonic()
        next_exit = time.monotonic()
        tick_resolution_s = 0.25
        while not self._stop_event.wait(timeout=tick_resolution_s):
            now = time.monotonic()
            run_entry = now >= next_entry
            run_exit = now >= next_exit
            if not run_entry and not run_exit:
                continue
            db = SessionLocal()
            try:
                context = ContextService(db=db, settings=self._settings)
                market = MarketStoreService(db=db, settings=self._settings)
                if run_exit:
                    coord.run_exit_tick(db, context=context, market=market, settings=self._settings)
                    next_exit = now + max(float(self._settings.STRATEGY3_PAPER_EXIT_INTERVAL_SECONDS), 0.5)
                if run_entry:
                    coord.run_entry_tick(db, context=context, market=market, settings=self._settings)
                    next_entry = now + max(float(self._settings.STRATEGY3_PAPER_ENTRY_INTERVAL_SECONDS), 1.0)
            except Exception as exc:
                logger.warning("Strategy 3 scheduler tick failed: %s", exc)
            finally:
                db.close()
