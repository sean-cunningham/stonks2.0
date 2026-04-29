"""Paper trading API for SPY Trend Continuation — persistence only; no broker routing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.strategy_one import get_context_service, get_market_service
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.strategy_dashboard_baseline_repository import StrategyDashboardBaselineRepository
from app.schemas.market import ChainLatestResponse, MarketStatusResponse
from app.schemas.paper_trade import (
    PaperCloseRequest,
    PaperOpenPositionValuationResponse,
    PaperTradeEventResponse,
    PaperTradeResponse,
)
from app.schemas.strategy_one_exit_evaluation import StrategyOneExitEvaluationResponse
from app.schemas.strategy_one_position_monitor import (
    StrategyOneOpenPositionMonitorResponse,
    StrategyOneOpenPositionsMonitorResponse,
)
from app.schemas.strategy import StrategyOneEvaluationResponse
from app.schemas.strategy_dashboard import StrategyDashboardResponse, StrategyStatsBaselineView
from app.schemas.strategy_one_paper_execution import StrategyOneExecuteOnceResponse
from app.schemas.strategy_one_runtime import StrategyOneRuntimeStatusResponse
from app.services.market.context_service import ContextService
from app.services.market.market_store import MarketStoreService
from app.services.paper.paper_trade_service import PaperTradeError, PaperTradeService
from app.services.paper.paper_valuation import compute_open_position_valuation
from app.services.paper.strategy_one_exit_evaluator import ExitEvaluationInput, evaluate_strategy_one_open_exit_readonly
from app.services.paper.strategy_one_evaluation_bundle import build_strategy_one_evaluation_bundle
from app.services.paper.strategy_one_execute_once import run_emergency_close_open_paper_trade, run_strategy_one_paper_execute_once
from app.services.paper.strategy_one_dashboard_service import build_strategy_one_dashboard
from app.services.paper.strategy_one_runtime_service import get_strategy_one_runtime_coordinator
from app.services.paper.strategy_one_position_monitor import (
    build_open_positions_monitor,
    build_single_open_position_monitor,
)

router = APIRouter(prefix="/paper/strategy/spy/strategy-1", tags=["paper"])


def _require_paper_app_mode(settings: Settings) -> None:
    if settings.APP_MODE != "paper":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="strategy_1_paper_automation_requires_app_mode_paper",
        )


def _paper_trade_http_detail(exc: PaperTradeError) -> dict:
    return {"code": exc.code, **exc.details}


@router.post("/execute-once", response_model=StrategyOneExecuteOnceResponse)
def execute_strategy_one_paper_once(
    db: Session = Depends(get_db),
    context: ContextService = Depends(get_context_service),
    market: MarketStoreService = Depends(get_market_service),
) -> StrategyOneExecuteOnceResponse:
    """Run one automatic Strategy 1 paper cycle (auto-open or auto-close only; no live routing)."""
    settings = get_settings()
    _require_paper_app_mode(settings)
    return run_strategy_one_paper_execute_once(db, context=context, market=market, settings=settings)


@router.get("/dashboard", response_model=StrategyDashboardResponse)
def get_strategy_one_dashboard(
    db: Session = Depends(get_db),
    context: ContextService = Depends(get_context_service),
    market: MarketStoreService = Depends(get_market_service),
) -> StrategyDashboardResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    return build_strategy_one_dashboard(db, context=context, market=market, settings=settings)


@router.post("/dashboard/reset", response_model=StrategyStatsBaselineView)
def reset_strategy_one_dashboard_stats(db: Session = Depends(get_db)) -> StrategyStatsBaselineView:
    """Set/reset dashboard baseline so stats/charts restart from configured starting equity."""
    settings = get_settings()
    _require_paper_app_mode(settings)
    strategy_id = PaperTradeService.STRATEGY_ID
    repo = PaperTradeRepository(db)
    baseline_cash = float(settings.PAPER_STRATEGY1_ACCOUNT_EQUITY_USD)
    baseline_repo = StrategyDashboardBaselineRepository(db)
    now = repo.utc_now()
    row = baseline_repo.upsert_for_strategy(strategy_id=strategy_id, reset_at=now, baseline_cash=baseline_cash)
    return StrategyStatsBaselineView(reset_at=row.reset_at, baseline_cash=float(row.baseline_cash))


@router.get("/runtime/status", response_model=StrategyOneRuntimeStatusResponse)
def get_strategy_one_runtime_status(db: Session = Depends(get_db)) -> StrategyOneRuntimeStatusResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    return get_strategy_one_runtime_coordinator().get_status(db, settings=settings)


@router.post("/runtime/pause", response_model=StrategyOneRuntimeStatusResponse)
def pause_strategy_one_runtime(db: Session = Depends(get_db)) -> StrategyOneRuntimeStatusResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    return get_strategy_one_runtime_coordinator().set_paused(db, settings=settings, paused=True)


@router.post("/runtime/resume", response_model=StrategyOneRuntimeStatusResponse)
def resume_strategy_one_runtime(db: Session = Depends(get_db)) -> StrategyOneRuntimeStatusResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    return get_strategy_one_runtime_coordinator().set_paused(db, settings=settings, paused=False)


@router.post("/runtime/entry-enable", response_model=StrategyOneRuntimeStatusResponse)
def enable_strategy_one_runtime_entry(db: Session = Depends(get_db)) -> StrategyOneRuntimeStatusResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    return get_strategy_one_runtime_coordinator().set_runtime_flags(
        db,
        settings=settings,
        entry_enabled=True,
    )


@router.post("/runtime/entry-disable", response_model=StrategyOneRuntimeStatusResponse)
def disable_strategy_one_runtime_entry(db: Session = Depends(get_db)) -> StrategyOneRuntimeStatusResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    return get_strategy_one_runtime_coordinator().set_runtime_flags(
        db,
        settings=settings,
        entry_enabled=False,
    )


@router.post("/runtime/exit-enable", response_model=StrategyOneRuntimeStatusResponse)
def enable_strategy_one_runtime_exit(db: Session = Depends(get_db)) -> StrategyOneRuntimeStatusResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    return get_strategy_one_runtime_coordinator().set_runtime_flags(
        db,
        settings=settings,
        exit_enabled=True,
    )


@router.post("/runtime/exit-disable", response_model=StrategyOneRuntimeStatusResponse)
def disable_strategy_one_runtime_exit(db: Session = Depends(get_db)) -> StrategyOneRuntimeStatusResponse:
    settings = get_settings()
    _require_paper_app_mode(settings)
    return get_strategy_one_runtime_coordinator().set_runtime_flags(
        db,
        settings=settings,
        exit_enabled=False,
    )


@router.post("/positions/{paper_trade_id}/close-now", response_model=PaperTradeResponse)
def emergency_close_paper_position_now(
    paper_trade_id: int,
    db: Session = Depends(get_db),
    market: MarketStoreService = Depends(get_market_service),
) -> PaperTradeResponse:
    """Emergency manual override: close one open paper trade with conservative exit rules."""
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
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=_paper_trade_http_detail(exc)) from exc
    return PaperTradeResponse.model_validate(row)


@router.post("/positions/{paper_trade_id}/emergency-close-unquoted", response_model=PaperTradeResponse)
def emergency_close_unquoted_paper_position(
    paper_trade_id: int,
    db: Session = Depends(get_db),
    market: MarketStoreService = Depends(get_market_service),
) -> PaperTradeResponse:
    """Paper emergency close: uses live option bid when available; $0 only if no quotable leg (Strategy 1 only)."""
    settings = get_settings()
    _require_paper_app_mode(settings)
    svc = PaperTradeService()
    try:
        row = svc.emergency_close_unquoted_paper_position(
            db, paper_trade_id=paper_trade_id, market=market, settings=settings
        )
    except PaperTradeError as exc:
        code = str(exc)
        if code in ("paper_trade_not_found", "paper_trade_not_open", "paper_trade_strategy_mismatch"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail=code) from exc
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=_paper_trade_http_detail(exc)) from exc
    return PaperTradeResponse.model_validate(row)


@router.post("/positions", response_model=PaperTradeResponse, status_code=status.HTTP_201_CREATED)
def open_paper_position_from_evaluation(
    db: Session = Depends(get_db),
    context: ContextService = Depends(get_context_service),
    market: MarketStoreService = Depends(get_market_service),
) -> PaperTradeResponse:
    """Open one paper long position from the current Strategy 1 evaluation (server-side snapshot)."""
    settings = get_settings()
    evaluation, mstatus, chain = build_strategy_one_evaluation_bundle(context, market, settings)
    svc = PaperTradeService()
    try:
        row = svc.open_position(
            db,
            evaluation=evaluation,
            chain=chain,
            market_status=mstatus,
            settings=settings,
        )
    except PaperTradeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PaperTradeResponse.model_validate(row)


@router.post("/positions/{paper_trade_id}/close", response_model=PaperTradeResponse)
def close_paper_position(
    paper_trade_id: int,
    body: PaperCloseRequest,
    db: Session = Depends(get_db),
    market: MarketStoreService = Depends(get_market_service),
) -> PaperTradeResponse:
    """Close an open paper position using bid reference on a fresh chain snapshot."""
    settings = get_settings()
    resolution = market.resolve_spy_market_for_evaluation()
    chain = market.get_latest_chain()
    repo = PaperTradeRepository(db)
    row_chk = repo.get_trade(paper_trade_id)
    if row_chk is None or row_chk.strategy_id != PaperTradeService.STRATEGY_ID or row_chk.status != "open":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="open_paper_trade_not_found")
    held = market.resolve_open_paper_option_contract(option_symbol=row_chk.option_symbol, chain=chain)
    svc = PaperTradeService()
    try:
        row = svc.close_position(
            db,
            paper_trade_id=paper_trade_id,
            chain=chain,
            market_status=resolution.final_status,
            exit_reason=body.exit_reason,
            settings=settings,
            held_contract_resolution=held,
        )
    except PaperTradeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=_paper_trade_http_detail(exc)) from exc
    return PaperTradeResponse.model_validate(row)


@router.get("/positions/open", response_model=list[PaperTradeResponse])
def list_open_paper_positions(db: Session = Depends(get_db)) -> list[PaperTradeResponse]:
    repo = PaperTradeRepository(db)
    rows = repo.list_open(strategy_id=PaperTradeService.STRATEGY_ID)
    return [PaperTradeResponse.model_validate(r) for r in rows]


@router.get("/positions/open/valuation", response_model=list[PaperOpenPositionValuationResponse])
def list_open_paper_position_valuations(
    db: Session = Depends(get_db),
    market: MarketStoreService = Depends(get_market_service),
) -> list[PaperOpenPositionValuationResponse]:
    """Mark-to-market all open Strategy 1 paper rows against one latest chain snapshot."""
    settings = get_settings()
    market.resolve_spy_market_for_evaluation()
    chain = market.get_latest_chain()
    repo = PaperTradeRepository(db)
    rows = repo.list_open(strategy_id=PaperTradeService.STRATEGY_ID)
    out: list[PaperOpenPositionValuationResponse] = []
    for r in rows:
        held = market.resolve_open_paper_option_contract(option_symbol=r.option_symbol, chain=chain)
        out.append(compute_open_position_valuation(r, chain, settings, held_resolution=held))
    return out


@router.get("/positions/open/monitor", response_model=StrategyOneOpenPositionsMonitorResponse)
def list_open_positions_monitor(
    db: Session = Depends(get_db),
    context: ContextService = Depends(get_context_service),
    market: MarketStoreService = Depends(get_market_service),
) -> StrategyOneOpenPositionsMonitorResponse:
    """Unified read-only monitor for all open Strategy 1 paper positions (one chain snapshot)."""
    settings = get_settings()
    st = context.get_status()
    summary = context.get_summary()
    resolution = market.resolve_spy_market_for_evaluation()
    mstatus = resolution.final_status
    chain = market.get_latest_chain()
    repo = PaperTradeRepository(db)
    rows = repo.list_open(strategy_id=PaperTradeService.STRATEGY_ID)
    return build_open_positions_monitor(
        rows,
        chain=chain,
        settings=settings,
        context_status=st,
        context_summary=summary,
        market_status=mstatus,
        market=market,
    )


@router.get("/positions/{paper_trade_id}/monitor", response_model=StrategyOneOpenPositionMonitorResponse)
def get_open_position_monitor(
    paper_trade_id: int,
    db: Session = Depends(get_db),
    context: ContextService = Depends(get_context_service),
    market: MarketStoreService = Depends(get_market_service),
) -> StrategyOneOpenPositionMonitorResponse:
    """Unified read-only monitor for one open Strategy 1 paper position."""
    settings = get_settings()
    repo = PaperTradeRepository(db)
    row = repo.get_trade(paper_trade_id)
    if row is None or row.strategy_id != PaperTradeService.STRATEGY_ID or row.status != "open":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="open_paper_trade_not_found")
    st = context.get_status()
    summary = context.get_summary()
    resolution = market.resolve_spy_market_for_evaluation()
    mstatus = resolution.final_status
    chain = market.get_latest_chain()
    return build_single_open_position_monitor(
        row,
        chain=chain,
        settings=settings,
        context_status=st,
        context_summary=summary,
        market_status=mstatus,
        market=market,
    )


@router.get("/positions/{paper_trade_id}/exit-evaluation", response_model=StrategyOneExitEvaluationResponse)
def get_open_paper_position_exit_evaluation(
    paper_trade_id: int,
    db: Session = Depends(get_db),
    context: ContextService = Depends(get_context_service),
    market: MarketStoreService = Depends(get_market_service),
) -> StrategyOneExitEvaluationResponse:
    """Read-only exit recommendation for one open paper row (no auto-close)."""
    settings = get_settings()
    repo = PaperTradeRepository(db)
    row = repo.get_trade(paper_trade_id)
    if row is None or row.strategy_id != PaperTradeService.STRATEGY_ID or row.status != "open":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="open_paper_trade_not_found")
    st = context.get_status()
    summary = context.get_summary()
    resolution = market.resolve_spy_market_for_evaluation()
    mstatus = resolution.final_status
    chain = market.get_latest_chain()
    held = market.resolve_open_paper_option_contract(option_symbol=row.option_symbol, chain=chain)
    valuation = compute_open_position_valuation(row, chain, settings, held_resolution=held)
    inp = ExitEvaluationInput(
        position=row,
        valuation=valuation,
        context_status=st,
        context_summary=summary,
        market_status=mstatus,
    )
    return evaluate_strategy_one_open_exit_readonly(inp)


@router.get("/positions/{paper_trade_id}/valuation", response_model=PaperOpenPositionValuationResponse)
def get_open_paper_position_valuation(
    paper_trade_id: int,
    db: Session = Depends(get_db),
    market: MarketStoreService = Depends(get_market_service),
) -> PaperOpenPositionValuationResponse:
    """Mark-to-market one open paper row; 404 if missing, wrong strategy, or not open."""
    settings = get_settings()
    repo = PaperTradeRepository(db)
    row = repo.get_trade(paper_trade_id)
    if row is None or row.strategy_id != PaperTradeService.STRATEGY_ID or row.status != "open":
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="open_paper_trade_not_found")
    market.resolve_spy_market_for_evaluation()
    chain = market.get_latest_chain()
    held = market.resolve_open_paper_option_contract(option_symbol=row.option_symbol, chain=chain)
    return compute_open_position_valuation(row, chain, settings, held_resolution=held)


@router.get("/positions/closed", response_model=list[PaperTradeResponse])
def list_closed_paper_positions(db: Session = Depends(get_db), limit: int = 100) -> list[PaperTradeResponse]:
    repo = PaperTradeRepository(db)
    rows = repo.list_closed(strategy_id=PaperTradeService.STRATEGY_ID, limit=min(max(limit, 1), 500))
    return [PaperTradeResponse.model_validate(r) for r in rows]


@router.get("/journal", response_model=list[PaperTradeEventResponse])
def list_paper_trade_journal(db: Session = Depends(get_db), limit: int = 200) -> list[PaperTradeEventResponse]:
    repo = PaperTradeRepository(db)
    events = repo.list_journal(strategy_id=PaperTradeService.STRATEGY_ID, limit=min(max(limit, 1), 500))
    return [PaperTradeEventResponse.model_validate(e) for e in events]
