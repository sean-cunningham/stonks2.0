"""Build Strategy 2 evaluation + market status + chain."""

from __future__ import annotations

from app.core.config import Settings
from app.schemas.market import ChainLatestResponse, MarketStatusResponse
from app.schemas.strategy import StrategyOneEvaluationResponse, StrategyOneMarketEvaluationTrace
from app.services.market.context_service import ContextService
from app.services.market.market_store import MarketStoreService
from app.services.strategy.strategy_two_spy_0dte_vol_sniper import (
    StrategyTwoEvalInput,
    evaluate_strategy_two_spy_0dte_vol_sniper,
)


def build_strategy_two_evaluation_bundle(
    context: ContextService,
    market: MarketStoreService,
    settings: Settings,
) -> tuple[StrategyOneEvaluationResponse, MarketStatusResponse, ChainLatestResponse]:
    st = context.get_status()
    summary = context.get_summary()
    resolution = market.resolve_spy_market_for_evaluation()
    mstatus = resolution.final_status
    chain = market.get_latest_chain()
    inp = StrategyTwoEvalInput.from_api(status=st, summary=summary, market=mstatus, chain=chain)
    trace = StrategyOneMarketEvaluationTrace(
        market_status_source=resolution.market_status_source,
        auto_refresh_attempted=resolution.auto_refresh_attempted,
        auto_refresh_trigger_reason=resolution.auto_refresh_trigger_reason,
        post_refresh_market_ready=resolution.post_refresh_market_ready,
        post_refresh_block_reason=resolution.post_refresh_block_reason,
    )
    evaluation = evaluate_strategy_two_spy_0dte_vol_sniper(inp).model_copy(update={"market_evaluation_trace": trace})
    _ = settings
    return evaluation, mstatus, chain
