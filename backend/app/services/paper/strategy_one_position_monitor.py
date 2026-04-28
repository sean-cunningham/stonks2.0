"""Assemble Strategy 1 position monitor payloads (read-only; reuses valuation + exit eval)."""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.config import Settings
from app.models.trade import PaperTrade
from app.schemas.context import ContextStatusResponse, ContextSummaryResponse
from app.schemas.market import ChainLatestResponse, MarketStatusResponse
from app.schemas.strategy_one_exit_evaluation import StrategyOneExitEvaluationResponse
from app.schemas.strategy_one_position_monitor import (
    MonitorStateLiteral,
    StrategyOneOpenPositionMonitorResponse,
    StrategyOneOpenPositionsMonitorResponse,
    StrategyOnePositionMonitorRow,
)
from app.services.market.market_store import MarketStoreService
from app.services.paper.held_option_contract_resolution import HeldOptionContractResolution
from app.services.paper.paper_valuation import compute_open_position_valuation
from app.services.paper.strategy_one_exit_evaluator import ExitEvaluationInput, evaluate_strategy_one_open_exit_readonly


def derive_monitor_state(exit_eval: StrategyOneExitEvaluationResponse) -> MonitorStateLiteral:
    """Map exit evaluator output to a coarse dashboard monitor_state."""
    if exit_eval.action == "close_now":
        return "close_now"
    if exit_eval.action == "trail_active":
        return "trail_active"
    if exit_eval.action == "tighten_stop":
        return "protected"
    if exit_eval.action == "hold" and exit_eval.blockers:
        return "blocked"
    return "healthy"


def build_position_monitor_row(
    row: PaperTrade,
    *,
    chain: ChainLatestResponse,
    settings: Settings,
    context_status: ContextStatusResponse,
    context_summary: ContextSummaryResponse,
    market_status: MarketStatusResponse,
    evaluation_timestamp: datetime,
    held_resolution: HeldOptionContractResolution | None = None,
) -> StrategyOnePositionMonitorRow:
    valuation = compute_open_position_valuation(
        row, chain, settings, now=evaluation_timestamp, held_resolution=held_resolution
    )
    exit_eval = evaluate_strategy_one_open_exit_readonly(
        ExitEvaluationInput(
            position=row,
            valuation=valuation,
            context_status=context_status,
            context_summary=context_summary,
            market_status=market_status,
            clock_utc=evaluation_timestamp,
        )
    )
    return StrategyOnePositionMonitorRow(
        paper_trade_id=int(row.id),
        strategy_id=row.strategy_id,
        symbol=row.symbol,
        option_symbol=row.option_symbol,
        side=row.side,
        quantity=int(row.quantity),
        entry_time=row.entry_time,
        entry_price=float(row.entry_price),
        entry_decision=row.entry_decision,
        entry_reference_basis=row.entry_reference_basis,
        valuation=valuation,
        exit_policy=row.exit_policy if isinstance(row.exit_policy, dict) else None,
        sizing_policy=row.sizing_policy if isinstance(row.sizing_policy, dict) else None,
        exit_evaluation=exit_eval,
        monitor_state=derive_monitor_state(exit_eval),
    )


def build_open_positions_monitor(
    rows: list[PaperTrade],
    *,
    chain: ChainLatestResponse,
    settings: Settings,
    context_status: ContextStatusResponse,
    context_summary: ContextSummaryResponse,
    market_status: MarketStatusResponse,
    evaluation_timestamp: datetime | None = None,
    market: MarketStoreService | None = None,
) -> StrategyOneOpenPositionsMonitorResponse:
    clock = evaluation_timestamp or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    positions: list[StrategyOnePositionMonitorRow] = []
    for r in rows:
        held: HeldOptionContractResolution | None = None
        if market is not None:
            held = market.resolve_open_paper_option_contract(option_symbol=r.option_symbol, chain=chain)
        positions.append(
            build_position_monitor_row(
                r,
                chain=chain,
                settings=settings,
                context_status=context_status,
                context_summary=context_summary,
                market_status=market_status,
                evaluation_timestamp=clock,
                held_resolution=held,
            )
        )
    return StrategyOneOpenPositionsMonitorResponse(
        evaluation_timestamp=clock,
        context_status=context_status,
        context_summary=context_summary,
        market_status=market_status,
        positions=positions,
    )


def build_single_open_position_monitor(
    row: PaperTrade,
    *,
    chain: ChainLatestResponse,
    settings: Settings,
    context_status: ContextStatusResponse,
    context_summary: ContextSummaryResponse,
    market_status: MarketStatusResponse,
    evaluation_timestamp: datetime | None = None,
    market: MarketStoreService | None = None,
) -> StrategyOneOpenPositionMonitorResponse:
    clock = evaluation_timestamp or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    held: HeldOptionContractResolution | None = None
    if market is not None:
        held = market.resolve_open_paper_option_contract(option_symbol=row.option_symbol, chain=chain)
    pos = build_position_monitor_row(
        row,
        chain=chain,
        settings=settings,
        context_status=context_status,
        context_summary=context_summary,
        market_status=market_status,
        evaluation_timestamp=clock,
        held_resolution=held,
    )
    return StrategyOneOpenPositionMonitorResponse(
        evaluation_timestamp=clock,
        context_status=context_status,
        context_summary=context_summary,
        market_status=market_status,
        position=pos,
    )
