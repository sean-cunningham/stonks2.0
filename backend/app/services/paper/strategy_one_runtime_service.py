"""Strategy 1 paper runtime coordinator and single-process overlap protection."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.strategy_runtime import StrategyRuntimeCycleLog
from app.repositories.strategy_runtime_repository import StrategyRuntimeRepository
from app.schemas.strategy_one_runtime import StrategyOneRuntimeStatusResponse
from app.services.market.context_service import ContextService
from app.services.market.market_store import MarketStoreService
from app.services.paper.paper_trade_service import PaperTradeService
from app.services.paper.strategy_one_execute_once import run_strategy_one_paper_execute_once
from app.services.paper.strategy_one_execution_window import is_within_spy_rth_et

SKIPPED_PAUSED = "skipped_paused"
SKIPPED_OVERLAP = "skipped_overlapping_cycle"
SKIPPED_OUTSIDE_EXECUTION_WINDOW = "skipped_outside_execution_window"
RESULT_ERROR = "error"
LOCK_SCOPE_SINGLE_PROCESS = "single_process_only"

SLEEP_REASON_PAUSED = "paused"
SLEEP_REASON_OUTSIDE_RTH = "outside_rth"


class StrategyOneRuntimeCoordinator:
    """
    Coordinates scheduled execution and runtime controls for Strategy 1 paper mode.

    Overlap guard is a process-local lock only and does not protect multi-worker deployments.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def _build_status(
        self,
        state,
        *,
        settings: Settings,
        clock_utc: datetime | None = None,
    ) -> StrategyOneRuntimeStatusResponse:
        now = clock_utc or datetime.now(timezone.utc)
        market_window_open = is_within_spy_rth_et(clock_utc=now)
        if state.paused:
            runtime_sleep_reason = SLEEP_REASON_PAUSED
        elif not market_window_open:
            runtime_sleep_reason = SLEEP_REASON_OUTSIDE_RTH
        else:
            runtime_sleep_reason = None
        return StrategyOneRuntimeStatusResponse(
            strategy_id=PaperTradeService.STRATEGY_ID,
            mode=settings.APP_MODE,
            scheduler_enabled=settings.STRATEGY1_PAPER_RUNTIME_ENABLED,
            paused=state.paused,
            entry_enabled=state.entry_enabled,
            exit_enabled=state.exit_enabled,
            running=self._lock.locked(),
            lock_scope=LOCK_SCOPE_SINGLE_PROCESS,
            last_cycle_started_at=state.last_cycle_started_at,
            last_cycle_finished_at=state.last_cycle_finished_at,
            last_cycle_result=state.last_cycle_result,
            last_error=state.last_error,
            market_window_open=market_window_open,
            runtime_sleep_reason=runtime_sleep_reason,
        )

    def get_status(self, db: Session, *, settings: Settings) -> StrategyOneRuntimeStatusResponse:
        repo = StrategyRuntimeRepository(db)
        state = repo.get_or_create_state(strategy_id=PaperTradeService.STRATEGY_ID)
        return self._build_status(state, settings=settings)

    def set_paused(self, db: Session, *, settings: Settings, paused: bool) -> StrategyOneRuntimeStatusResponse:
        repo = StrategyRuntimeRepository(db)
        state = repo.get_or_create_state(strategy_id=PaperTradeService.STRATEGY_ID)
        state.paused = paused
        repo.save_state(state)
        return self._build_status(state, settings=settings)

    def set_runtime_flags(
        self,
        db: Session,
        *,
        settings: Settings,
        entry_enabled: bool | None = None,
        exit_enabled: bool | None = None,
    ) -> StrategyOneRuntimeStatusResponse:
        repo = StrategyRuntimeRepository(db)
        state = repo.get_or_create_state(strategy_id=PaperTradeService.STRATEGY_ID)
        if entry_enabled is not None:
            state.entry_enabled = entry_enabled
        if exit_enabled is not None:
            state.exit_enabled = exit_enabled
        repo.save_state(state)
        return self._build_status(state, settings=settings)

    def run_tick(
        self,
        db: Session,
        *,
        context: ContextService,
        market: MarketStoreService,
        settings: Settings,
        clock_utc: datetime | None = None,
    ) -> StrategyOneRuntimeStatusResponse:
        repo = StrategyRuntimeRepository(db)
        state = repo.get_or_create_state(strategy_id=PaperTradeService.STRATEGY_ID)
        now = clock_utc or datetime.now(timezone.utc)

        if state.paused:
            state.last_cycle_started_at = now
            state.last_cycle_finished_at = now
            state.last_cycle_result = SKIPPED_PAUSED
            state.last_error = None
            repo.save_state(state)
            repo.append_cycle_log(
                StrategyRuntimeCycleLog(
                    strategy_id=PaperTradeService.STRATEGY_ID,
                    started_at=now,
                    finished_at=now,
                    result=SKIPPED_PAUSED,
                )
            )
            return self._build_status(state, settings=settings, clock_utc=now)

        if not is_within_spy_rth_et(clock_utc=now):
            state.last_cycle_started_at = now
            state.last_cycle_finished_at = now
            state.last_cycle_result = SKIPPED_OUTSIDE_EXECUTION_WINDOW
            state.last_error = None
            repo.save_state(state)
            return self._build_status(state, settings=settings, clock_utc=now)

        if not self._lock.acquire(blocking=False):
            finished = datetime.now(timezone.utc)
            repo.append_cycle_log(
                StrategyRuntimeCycleLog(
                    strategy_id=PaperTradeService.STRATEGY_ID,
                    started_at=now,
                    finished_at=finished,
                    result=SKIPPED_OVERLAP,
                )
            )
            return self._build_status(state, settings=settings, clock_utc=now)

        try:
            state.last_cycle_started_at = now
            state.last_cycle_result = "running"
            state.last_error = None
            repo.save_state(state)
            try:
                out = run_strategy_one_paper_execute_once(
                    db,
                    context=context,
                    market=market,
                    settings=settings,
                    entry_enabled=state.entry_enabled,
                    exit_enabled=state.exit_enabled,
                )
                finished = datetime.now(timezone.utc)
                state.last_cycle_finished_at = finished
                state.last_cycle_result = out.cycle_action
                state.last_error = None
                repo.save_state(state)
                notes_summary = "|".join(out.notes)[:512] if out.notes else None
                repo.append_cycle_log(
                    StrategyRuntimeCycleLog(
                        strategy_id=PaperTradeService.STRATEGY_ID,
                        started_at=now,
                        finished_at=finished,
                        result=out.cycle_action,
                        cycle_action=out.cycle_action,
                        had_open_position_at_start=out.had_open_position_at_start,
                        notes_summary=notes_summary,
                    )
                )
            except Exception as exc:
                finished = datetime.now(timezone.utc)
                code = str(exc)[:256]
                state.last_cycle_finished_at = finished
                state.last_cycle_result = RESULT_ERROR
                state.last_error = code
                repo.save_state(state)
                repo.append_cycle_log(
                    StrategyRuntimeCycleLog(
                        strategy_id=PaperTradeService.STRATEGY_ID,
                        started_at=now,
                        finished_at=finished,
                        result=RESULT_ERROR,
                        error_code=code,
                    )
                )
        finally:
            self._lock.release()

        return self._build_status(state, settings=settings, clock_utc=now)


_runtime_coordinator = StrategyOneRuntimeCoordinator()


def get_strategy_one_runtime_coordinator() -> StrategyOneRuntimeCoordinator:
    return _runtime_coordinator
