"""Paper trading API for SPY Micro Impulse Scalper (0DTE)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.strategy_one import get_context_service, get_market_service
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.strategy_dashboard_baseline_repository import StrategyDashboardBaselineRepository
from app.schemas.paper_trade import PaperTradeEventResponse, PaperTradeResponse
from app.schemas.strategy_dashboard import StrategyDashboardResponse, StrategyStatsBaselineView
from app.schemas.strategy_three_paper_execution import StrategyThreeExecuteOnceResponse
from app.schemas.strategy_three_runtime import StrategyThreeRuntimeStatusResponse
from app.services.market.context_service import ContextService
from app.services.market.market_store import MarketStoreService
from app.services.paper.paper_trade_service import PaperTradeError
from app.services.paper.strategy_three_dashboard_service import build_strategy_three_dashboard
from app.services.paper.strategy_three_execute_once import (
    run_emergency_close_open_paper_trade,
    run_strategy_three_paper_execute_once,
)
from app.services.paper.strategy_three_paper_trade_service import StrategyThreePaperTradeService
from app.services.paper.strategy_three_runtime_service import get_strategy_three_runtime_coordinator

router = APIRouter(prefix="/paper/strategy/spy/strategy-3", tags=["paper"])


def _require_paper_app_mode(settings: Settings) -> None:
    if settings.APP_MODE != "paper":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="strategy_3_paper_automation_requires_app_mode_paper",
        )


@router.post("/execute-once", response_model=StrategyThreeExecuteOnceResponse)
def execute_strategy_three_paper_once(
    db: Session = Depends(get_db),
    context: ContextService = Depends(get_context_service),
    market: MarketStoreService = Depends(get_market_service),
) -> StrategyThreeExecuteOnceResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    return run_strategy_three_paper_execute_once(db, context=context, market=market, settings=settings)


@router.get("/dashboard", response_model=StrategyDashboardResponse)
def get_strategy_three_dashboard(
    db: Session = Depends(get_db),
    context: ContextService = Depends(get_context_service),
    market: MarketStoreService = Depends(get_market_service),
) -> StrategyDashboardResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    return build_strategy_three_dashboard(db, context=context, market=market, settings=settings)


@router.post("/dashboard/reset", response_model=StrategyStatsBaselineView)
def reset_strategy_three_dashboard_stats(db: Session = Depends(get_db)) -> StrategyStatsBaselineView:
    """Set/reset dashboard baseline so stats/charts restart from configured starting equity."""
    settings = get_settings()
    _require_paper_app_mode(settings)
    strategy_id = StrategyThreePaperTradeService.STRATEGY_ID
    repo = PaperTradeRepository(db)
    baseline_cash = float(settings.PAPER_STRATEGY3_ACCOUNT_EQUITY_USD)
    baseline_repo = StrategyDashboardBaselineRepository(db)
    now = repo.utc_now()
    row = baseline_repo.upsert_for_strategy(strategy_id=strategy_id, reset_at=now, baseline_cash=baseline_cash)
    return StrategyStatsBaselineView(reset_at=row.reset_at, baseline_cash=float(row.baseline_cash))


@router.get("/runtime/status", response_model=StrategyThreeRuntimeStatusResponse)
def get_strategy_three_runtime_status(db: Session = Depends(get_db)) -> StrategyThreeRuntimeStatusResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    return get_strategy_three_runtime_coordinator().get_status(db, settings=settings)


@router.post("/runtime/pause", response_model=StrategyThreeRuntimeStatusResponse)
def pause_strategy_three_runtime(db: Session = Depends(get_db)) -> StrategyThreeRuntimeStatusResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    return get_strategy_three_runtime_coordinator().set_paused(db, settings=settings, paused=True)


@router.post("/runtime/resume", response_model=StrategyThreeRuntimeStatusResponse)
def resume_strategy_three_runtime(db: Session = Depends(get_db)) -> StrategyThreeRuntimeStatusResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    return get_strategy_three_runtime_coordinator().set_paused(db, settings=settings, paused=False)


@router.post("/runtime/entry-enable", response_model=StrategyThreeRuntimeStatusResponse)
def enable_strategy_three_runtime_entry(db: Session = Depends(get_db)) -> StrategyThreeRuntimeStatusResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    return get_strategy_three_runtime_coordinator().set_runtime_flags(db, settings=settings, entry_enabled=True)


@router.post("/runtime/entry-disable", response_model=StrategyThreeRuntimeStatusResponse)
def disable_strategy_three_runtime_entry(db: Session = Depends(get_db)) -> StrategyThreeRuntimeStatusResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    return get_strategy_three_runtime_coordinator().set_runtime_flags(db, settings=settings, entry_enabled=False)


@router.post("/runtime/exit-enable", response_model=StrategyThreeRuntimeStatusResponse)
def enable_strategy_three_runtime_exit(db: Session = Depends(get_db)) -> StrategyThreeRuntimeStatusResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    return get_strategy_three_runtime_coordinator().set_runtime_flags(db, settings=settings, exit_enabled=True)


@router.post("/runtime/exit-disable", response_model=StrategyThreeRuntimeStatusResponse)
def disable_strategy_three_runtime_exit(db: Session = Depends(get_db)) -> StrategyThreeRuntimeStatusResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    return get_strategy_three_runtime_coordinator().set_runtime_flags(db, settings=settings, exit_enabled=False)


@router.post("/positions/{paper_trade_id}/close-now", response_model=PaperTradeResponse)
def emergency_close_paper_position_now(
    paper_trade_id: int,
    db: Session = Depends(get_db),
    market: MarketStoreService = Depends(get_market_service),
) -> PaperTradeResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    try:
        row = run_emergency_close_open_paper_trade(
            db,
            paper_trade_id=paper_trade_id,
            market=market,
            settings=settings,
        )
    except PaperTradeError as exc:
        code = str(exc)
        if code == "paper_trade_not_open_for_emergency_close":
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=code) from exc
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=code) from exc
    return PaperTradeResponse.model_validate(row)


@router.get("/positions/open", response_model=list[PaperTradeResponse])
def list_open_paper_positions(db: Session = Depends(get_db)) -> list[PaperTradeResponse]:
    repo = PaperTradeRepository(db)
    rows = repo.list_open(strategy_id=StrategyThreePaperTradeService.STRATEGY_ID)
    return [PaperTradeResponse.model_validate(r) for r in rows]


@router.get("/positions/closed", response_model=list[PaperTradeResponse])
def list_closed_paper_positions(db: Session = Depends(get_db), limit: int = 100) -> list[PaperTradeResponse]:
    repo = PaperTradeRepository(db)
    rows = repo.list_closed(strategy_id=StrategyThreePaperTradeService.STRATEGY_ID, limit=min(max(limit, 1), 500))
    return [PaperTradeResponse.model_validate(r) for r in rows]


@router.get("/journal", response_model=list[PaperTradeEventResponse])
def list_paper_trade_journal(db: Session = Depends(get_db), limit: int = 200) -> list[PaperTradeEventResponse]:
    repo = PaperTradeRepository(db)
    events = repo.list_journal(strategy_id=StrategyThreePaperTradeService.STRATEGY_ID, limit=min(max(limit, 1), 500))
    return [PaperTradeEventResponse.model_validate(e) for e in events]
