"""Strategy 3 paper runtime coordinator with independent entry/exit ticks."""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.strategy_runtime import StrategyRuntimeCycleLog
from app.repositories.strategy_runtime_repository import StrategyRuntimeRepository
from app.schemas.strategy_three_runtime import StrategyThreeRuntimeStatusResponse
from app.services.market.context_service import ContextService
from app.services.market.market_store import MarketStoreService
from app.services.paper.strategy_one_execution_window import is_within_spy_rth_et
from app.services.paper.strategy_three_execute_once import (
    run_strategy_three_paper_entry_once,
    run_strategy_three_paper_exit_once,
    run_strategy_three_paper_execute_once,
)
from app.services.paper.strategy_three_paper_trade_service import StrategyThreePaperTradeService

SKIPPED_PAUSED = "skipped_paused"
SKIPPED_OVERLAP = "skipped_overlapping_cycle"
SKIPPED_OUTSIDE_EXECUTION_WINDOW = "skipped_outside_execution_window"
RESULT_ERROR = "error"
LOCK_SCOPE_SINGLE_PROCESS = "single_process_only"
SLEEP_REASON_PAUSED = "paused"
SLEEP_REASON_OUTSIDE_RTH = "outside_rth"


def _normalize_runtime_error_code(exc: Exception) -> str:
    raw = str(exc).strip()
    low = raw.lower()
    if "timed out during opening handshake" in low:
        return "dxlink_handshake_timeout"
    if "option_chain" in low or "option quote" in low or "missing_option_quote" in low:
        return "option_quote_refresh_failed"
    if "market" in low and "refresh" in low:
        return "market_data_refresh_failed"
    return raw[:256] if raw else exc.__class__.__name__


class StrategyThreeRuntimeCoordinator:
    def __init__(self) -> None:
        self._entry_lock = threading.Lock()
        self._exit_lock = threading.Lock()
        self._strategy_id = StrategyThreePaperTradeService.STRATEGY_ID

    def _is_running(self) -> bool:
        return self._entry_lock.locked() or self._exit_lock.locked()

    def _build_status(
        self,
        state,
        *,
        settings: Settings,
        clock_utc: datetime | None = None,
    ) -> StrategyThreeRuntimeStatusResponse:
        now = clock_utc or datetime.now(timezone.utc)
        market_window_open = is_within_spy_rth_et(clock_utc=now)
        if state.paused:
            runtime_sleep_reason = SLEEP_REASON_PAUSED
        elif not market_window_open:
            runtime_sleep_reason = SLEEP_REASON_OUTSIDE_RTH
        else:
            runtime_sleep_reason = None
        return StrategyThreeRuntimeStatusResponse(
            strategy_id=self._strategy_id,
            mode=settings.APP_MODE,
            scheduler_enabled=settings.STRATEGY3_PAPER_RUNTIME_ENABLED,
            paused=state.paused,
            entry_enabled=state.entry_enabled,
            exit_enabled=state.exit_enabled,
            running=self._is_running(),
            lock_scope=LOCK_SCOPE_SINGLE_PROCESS,
            last_cycle_started_at=state.last_cycle_started_at,
            last_cycle_finished_at=state.last_cycle_finished_at,
            last_cycle_result=state.last_cycle_result,
            last_error=state.last_error,
            market_window_open=market_window_open,
            runtime_sleep_reason=runtime_sleep_reason,
        )

    def get_status(self, db: Session, *, settings: Settings) -> StrategyThreeRuntimeStatusResponse:
        repo = StrategyRuntimeRepository(db)
        state = repo.get_or_create_state(strategy_id=self._strategy_id)
        return self._build_status(state, settings=settings)

    def set_paused(self, db: Session, *, settings: Settings, paused: bool) -> StrategyThreeRuntimeStatusResponse:
        repo = StrategyRuntimeRepository(db)
        state = repo.get_or_create_state(strategy_id=self._strategy_id)
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
    ) -> StrategyThreeRuntimeStatusResponse:
        repo = StrategyRuntimeRepository(db)
        state = repo.get_or_create_state(strategy_id=self._strategy_id)
        if entry_enabled is not None:
            state.entry_enabled = entry_enabled
        if exit_enabled is not None:
            state.exit_enabled = exit_enabled
        repo.save_state(state)
        return self._build_status(state, settings=settings)

    def _run_phase_tick(
        self,
        db: Session,
        *,
        context: ContextService,
        market: MarketStoreService,
        settings: Settings,
        phase: str,
        lock: threading.Lock,
    ) -> StrategyThreeRuntimeStatusResponse:
        repo = StrategyRuntimeRepository(db)
        state = repo.get_or_create_state(strategy_id=self._strategy_id)
        now = datetime.now(timezone.utc)
        if state.paused:
            state.last_cycle_started_at = now
            state.last_cycle_finished_at = now
            state.last_cycle_result = SKIPPED_PAUSED
            state.last_error = None
            repo.save_state(state)
            repo.append_cycle_log(
                StrategyRuntimeCycleLog(
                    strategy_id=self._strategy_id,
                    started_at=now,
                    finished_at=now,
                    result=SKIPPED_PAUSED,
                    notes_summary=f"phase:{phase}",
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
        if not lock.acquire(blocking=False):
            finished = datetime.now(timezone.utc)
            repo.append_cycle_log(
                StrategyRuntimeCycleLog(
                    strategy_id=self._strategy_id,
                    started_at=now,
                    finished_at=finished,
                    result=SKIPPED_OVERLAP,
                    notes_summary=f"phase:{phase}",
                )
            )
            return self._build_status(state, settings=settings, clock_utc=now)

        try:
            state.last_cycle_started_at = now
            state.last_cycle_result = "running"
            state.last_error = None
            repo.save_state(state)
            try:
                if phase == "entry":
                    out = run_strategy_three_paper_entry_once(
                        db,
                        context=context,
                        market=market,
                        settings=settings,
                        entry_enabled=state.entry_enabled,
                    )
                else:
                    out = run_strategy_three_paper_exit_once(
                        db,
                        context=context,
                        market=market,
                        settings=settings,
                        exit_enabled=state.exit_enabled,
                    )
                finished = datetime.now(timezone.utc)
                state.last_cycle_finished_at = finished
                state.last_cycle_result = out.cycle_action
                state.last_error = None
                repo.save_state(state)
                notes_summary = "|".join([f"phase:{phase}"] + out.notes)[:512]
                repo.append_cycle_log(
                    StrategyRuntimeCycleLog(
                        strategy_id=self._strategy_id,
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
                code = _normalize_runtime_error_code(exc)
                state.last_cycle_finished_at = finished
                state.last_cycle_result = RESULT_ERROR
                state.last_error = code
                repo.save_state(state)
                repo.append_cycle_log(
                    StrategyRuntimeCycleLog(
                        strategy_id=self._strategy_id,
                        started_at=now,
                        finished_at=finished,
                        result=RESULT_ERROR,
                        error_code=code,
                        notes_summary=f"phase:{phase}|error:{code}",
                    )
                )
        finally:
            lock.release()
        return self._build_status(state, settings=settings, clock_utc=now)

    def run_entry_tick(
        self,
        db: Session,
        *,
        context: ContextService,
        market: MarketStoreService,
        settings: Settings,
    ) -> StrategyThreeRuntimeStatusResponse:
        return self._run_phase_tick(
            db,
            context=context,
            market=market,
            settings=settings,
            phase="entry",
            lock=self._entry_lock,
        )

    def run_exit_tick(
        self,
        db: Session,
        *,
        context: ContextService,
        market: MarketStoreService,
        settings: Settings,
    ) -> StrategyThreeRuntimeStatusResponse:
        return self._run_phase_tick(
            db,
            context=context,
            market=market,
            settings=settings,
            phase="exit",
            lock=self._exit_lock,
        )

    def run_tick(
        self,
        db: Session,
        *,
        context: ContextService,
        market: MarketStoreService,
        settings: Settings,
    ) -> StrategyThreeRuntimeStatusResponse:
        repo = StrategyRuntimeRepository(db)
        state = repo.get_or_create_state(strategy_id=self._strategy_id)
        now = datetime.now(timezone.utc)
        if state.paused or not is_within_spy_rth_et(clock_utc=now):
            return self._build_status(state, settings=settings, clock_utc=now)
        out = run_strategy_three_paper_execute_once(
            db,
            context=context,
            market=market,
            settings=settings,
            entry_enabled=state.entry_enabled,
            exit_enabled=state.exit_enabled,
        )
        finished = datetime.now(timezone.utc)
        state.last_cycle_started_at = now
        state.last_cycle_finished_at = finished
        state.last_cycle_result = out.cycle_action
        state.last_error = None
        repo.save_state(state)
        return self._build_status(state, settings=settings, clock_utc=finished)


_runtime_coordinator = StrategyThreeRuntimeCoordinator()


def get_strategy_three_runtime_coordinator() -> StrategyThreeRuntimeCoordinator:
    return _runtime_coordinator
