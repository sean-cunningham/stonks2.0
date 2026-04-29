"""Read-only API for SPY Fast Move Sniper (0DTE)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.strategy_one import get_context_service, get_market_service
from app.core.config import get_settings
from app.core.database import get_db
from app.schemas.strategy import StrategyOneEvaluationResponse, StrategyOneMarketEvaluationTrace
from app.services.market.context_service import ContextService
from app.services.market.market_store import MarketStoreService
from app.services.strategy.strategy_two_spy_0dte_vol_sniper import (
    StrategyTwoEvalInput,
    evaluate_strategy_two_spy_0dte_vol_sniper,
)

router = APIRouter(prefix="/strategy/spy/strategy-2", tags=["strategy"])


@router.get("/evaluation", response_model=StrategyOneEvaluationResponse)
def get_strategy_two_evaluation(
    context: ContextService = Depends(get_context_service),
    market: MarketStoreService = Depends(get_market_service),
    db: Session = Depends(get_db),
) -> StrategyOneEvaluationResponse:
    _ = db
    _ = get_settings()
    status = context.get_status()
    summary = context.get_summary()
    bars_1m = context.get_bars_1m()
    resolution = market.resolve_spy_market_for_evaluation()
    mstatus = resolution.final_status
    chain = market.get_latest_chain()
    inp = StrategyTwoEvalInput.from_api(
        status=status,
        summary=summary,
        market=mstatus,
        chain=chain,
        bars_1m=bars_1m.bars,
    )
    trace = StrategyOneMarketEvaluationTrace(
        market_status_source=resolution.market_status_source,
        auto_refresh_attempted=resolution.auto_refresh_attempted,
        auto_refresh_trigger_reason=resolution.auto_refresh_trigger_reason,
        post_refresh_market_ready=resolution.post_refresh_market_ready,
        post_refresh_block_reason=resolution.post_refresh_block_reason,
    )
    return evaluate_strategy_two_spy_0dte_vol_sniper(inp).model_copy(update={"market_evaluation_trace": trace})
