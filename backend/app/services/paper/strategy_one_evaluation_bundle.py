"""Build Strategy 1 evaluation + market status + chain (shared by paper API and automation)."""

from __future__ import annotations

from app.core.config import Settings
from app.schemas.market import ChainLatestResponse, MarketStatusResponse
from app.schemas.strategy import StrategyOneEvaluationResponse, StrategyOneMarketEvaluationTrace
from app.services.market.context_service import ContextService
from app.services.market.market_store import MarketStoreService
from app.services.strategy.strategy_one_spy import StrategyOneEvalInput, evaluate_strategy_one_spy


def build_strategy_one_evaluation_bundle(
    context: ContextService,
    market: MarketStoreService,
    settings: Settings,
) -> tuple[StrategyOneEvaluationResponse, MarketStatusResponse, ChainLatestResponse]:
    """One resolve + one chain read + evaluation (same inputs as manual paper open)."""
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
