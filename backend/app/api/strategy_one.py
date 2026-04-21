"""Read-only Strategy 1 (SPY) API — evaluation only; no execution."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.schemas.strategy import StrategyOneEvaluationResponse
from app.services.market.context_service import ContextService
from app.services.market.market_store import MarketStoreService
from app.services.strategy.strategy_one_spy import StrategyOneEvalInput, evaluate_strategy_one_spy

router = APIRouter(prefix="/strategy/spy/strategy-1", tags=["strategy"])


def get_context_service(db: Session = Depends(get_db)) -> ContextService:
    return ContextService(db=db, settings=get_settings())


def get_market_service(db: Session = Depends(get_db)) -> MarketStoreService:
    return MarketStoreService(db=db, settings=get_settings())


@router.get("/evaluation", response_model=StrategyOneEvaluationResponse)
def get_strategy_one_evaluation(
    context: ContextService = Depends(get_context_service),
    market: MarketStoreService = Depends(get_market_service),
) -> StrategyOneEvaluationResponse:
    """Return the current read-only Strategy 1 decision for SPY."""
    status = context.get_status()
    summary = context.get_summary()
    mstatus = market.get_spy_status()
    chain = market.get_latest_chain()
    inp = StrategyOneEvalInput.from_api(status=status, summary=summary, market=mstatus, chain=chain)
    return evaluate_strategy_one_spy(inp)
