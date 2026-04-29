"""Build Strategy 3 evaluation + market status + chain."""

from __future__ import annotations

from app.core.config import Settings
from app.schemas.market import ChainLatestResponse, MarketStatusResponse
from app.schemas.strategy import StrategyOneEvaluationResponse, StrategyOneMarketEvaluationTrace
from app.services.market.context_service import ContextService
from app.services.market.market_store import MarketStoreService
from app.services.strategy.strategy_three_spy_micro_impulse import (
    StrategyThreeEvalInput,
    evaluate_strategy_three_spy_micro_impulse,
)


def build_strategy_three_evaluation_bundle(
    context: ContextService,
    market: MarketStoreService,
    settings: Settings,
) -> tuple[StrategyOneEvaluationResponse, MarketStatusResponse, ChainLatestResponse]:
    st = context.get_status()
    summary = context.get_summary()
    bars_1m = context.get_bars_1m()
    resolution = market.resolve_spy_market_for_evaluation()
    mstatus = resolution.final_status
    chain = market.get_latest_chain()
    inp = StrategyThreeEvalInput.from_api(
        status=st,
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
    evaluation = evaluate_strategy_three_spy_micro_impulse(inp).model_copy(update={"market_evaluation_trace": trace})
    _ = settings
    return evaluation, mstatus, chain
