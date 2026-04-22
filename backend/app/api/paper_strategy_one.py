"""Paper trading API for Strategy 1 SPY — persistence only; no broker routing."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.strategy_one import get_context_service, get_market_service
from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.repositories.paper_trade_repository import PaperTradeRepository
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
from app.schemas.strategy import StrategyOneEvaluationResponse, StrategyOneMarketEvaluationTrace
from app.services.market.context_service import ContextService
from app.services.market.market_store import MarketStoreService
from app.services.paper.paper_trade_service import PaperTradeError, PaperTradeService
from app.services.paper.paper_valuation import compute_open_position_valuation
from app.services.paper.strategy_one_exit_evaluator import ExitEvaluationInput, evaluate_strategy_one_open_exit_readonly
from app.services.paper.strategy_one_position_monitor import (
    build_open_positions_monitor,
    build_single_open_position_monitor,
)
from app.services.strategy.strategy_one_spy import StrategyOneEvalInput, evaluate_strategy_one_spy

router = APIRouter(prefix="/paper/strategy/spy/strategy-1", tags=["paper"])


def _build_evaluation_bundle(
    context: ContextService,
    market: MarketStoreService,
    settings: Settings,
) -> tuple[StrategyOneEvaluationResponse, MarketStatusResponse, ChainLatestResponse]:
    """One resolve + one chain read + evaluation (matches GET /strategy/spy/strategy-1/evaluation)."""
    st = context.get_status()
    summary = context.get_summary()
    resolution = market.resolve_spy_market_for_evaluation()
    mstatus = resolution.final_status
    chain = market.get_latest_chain()
    inp = StrategyOneEvalInput.from_api(
        status=st,
        summary=summary,
        market=mstatus,
        chain=chain,
        quote_freshness_threshold_seconds=settings.MARKET_QUOTE_MAX_AGE_SECONDS,
    )
    trace = StrategyOneMarketEvaluationTrace(
        market_status_source=resolution.market_status_source,
        auto_refresh_attempted=resolution.auto_refresh_attempted,
        auto_refresh_trigger_reason=resolution.auto_refresh_trigger_reason,
        post_refresh_market_ready=resolution.post_refresh_market_ready,
        post_refresh_block_reason=resolution.post_refresh_block_reason,
    )
    evaluation = evaluate_strategy_one_spy(inp).model_copy(update={"market_evaluation_trace": trace})
    return evaluation, mstatus, chain


@router.post("/positions", response_model=PaperTradeResponse, status_code=status.HTTP_201_CREATED)
def open_paper_position_from_evaluation(
    db: Session = Depends(get_db),
    context: ContextService = Depends(get_context_service),
    market: MarketStoreService = Depends(get_market_service),
) -> PaperTradeResponse:
    """Open one paper long position from the current Strategy 1 evaluation (server-side snapshot)."""
    settings = get_settings()
    evaluation, mstatus, chain = _build_evaluation_bundle(context, market, settings)
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
    svc = PaperTradeService()
    try:
        row = svc.close_position(
            db,
            paper_trade_id=paper_trade_id,
            chain=chain,
            market_status=resolution.final_status,
            exit_reason=body.exit_reason,
            settings=settings,
        )
    except PaperTradeError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
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
    return [compute_open_position_valuation(r, chain, settings) for r in rows]


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
    valuation = compute_open_position_valuation(row, chain, settings)
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
    return compute_open_position_valuation(row, chain, settings)


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
