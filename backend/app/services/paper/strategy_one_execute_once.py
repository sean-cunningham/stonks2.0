"""One automatic Strategy 1 paper cycle (open or close only; fail-closed)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.models.trade import PaperTrade
from app.schemas.paper_trade import PaperOpenPositionValuationResponse, PaperTradeResponse
from app.schemas.strategy_one_paper_execution import StrategyOneExecuteOnceResponse
from app.services.market.context_service import ContextService
from app.services.market.market_store import MarketStoreService
from app.services.paper.paper_trade_service import PaperTradeError, PaperTradeService
from app.services.paper.paper_valuation import compute_open_position_valuation
from app.services.paper.strategy_one_evaluation_bundle import build_strategy_one_evaluation_bundle
from app.services.paper.strategy_one_exit_evaluator import ExitEvaluationInput, evaluate_strategy_one_open_exit_readonly


AUTO_EXIT_REASON = "strategy_1_auto_exit_close_now"
EMERGENCY_EXIT_REASON = "emergency_manual_override"


def require_acceptable_exit_quote_for_execution(valuation: PaperOpenPositionValuationResponse) -> None:
    """Fail-closed gate before any automated or emergency close that must honor fresh two-sided quotes."""
    if valuation.valuation_error:
        raise PaperTradeError("paper_exit_quote_not_acceptable_for_execution")
    if not valuation.quote_is_fresh:
        raise PaperTradeError("paper_exit_quote_not_acceptable_for_execution")
    if not valuation.exit_actionable:
        raise PaperTradeError("paper_exit_quote_not_acceptable_for_execution")


def run_strategy_one_paper_execute_once(
    db: Session,
    *,
    context: ContextService,
    market: MarketStoreService,
    settings: Settings,
    entry_enabled: bool = True,
    exit_enabled: bool = True,
) -> StrategyOneExecuteOnceResponse:
    """One cycle: close on exit-eval ``close_now`` if open and quote acceptable; else open on candidate if flat."""
    clock = datetime.now(timezone.utc)
    repo = PaperTradeRepository(db)
    opens = repo.list_open(strategy_id=PaperTradeService.STRATEGY_ID)
    had_open = len(opens) > 0
    notes: list[str] = []
    svc = PaperTradeService()

    if had_open:
        if not exit_enabled:
            notes.append("runtime_exit_disabled")
            return StrategyOneExecuteOnceResponse(
                cycle_action="no_action",
                had_open_position_at_start=True,
                notes=notes,
                evaluation_timestamp=clock,
            )
        if len(opens) > 1:
            notes.append("multiple_open_positions_unexpected_using_first_row_only")
        row = opens[0]
        st = context.get_status()
        summary = context.get_summary()
        resolution = market.resolve_spy_market_for_evaluation()
        mstatus = resolution.final_status
        chain = market.get_latest_chain()
        valuation = compute_open_position_valuation(row, chain, settings)
        exit_eval = evaluate_strategy_one_open_exit_readonly(
            ExitEvaluationInput(
                position=row,
                valuation=valuation,
                context_status=st,
                context_summary=summary,
                market_status=mstatus,
                clock_utc=clock,
            )
        )
        if exit_eval.action != "close_now":
            notes.append("exit_evaluator_did_not_request_close_now")
            return StrategyOneExecuteOnceResponse(
                cycle_action="no_action",
                had_open_position_at_start=True,
                notes=notes,
                evaluation_timestamp=clock,
                exit_evaluation=exit_eval,
            )
        try:
            require_acceptable_exit_quote_for_execution(valuation)
        except PaperTradeError as exc:
            notes.append(f"auto_close_skipped:{exc}")
            return StrategyOneExecuteOnceResponse(
                cycle_action="no_action",
                had_open_position_at_start=True,
                notes=notes,
                evaluation_timestamp=clock,
                exit_evaluation=exit_eval,
            )
        try:
            closed = svc.close_position(
                db,
                paper_trade_id=row.id,
                chain=chain,
                market_status=mstatus,
                exit_reason=AUTO_EXIT_REASON,
                settings=settings,
            )
        except PaperTradeError as exc:
            notes.append(f"auto_close_failed:{exc}")
            return StrategyOneExecuteOnceResponse(
                cycle_action="no_action",
                had_open_position_at_start=True,
                notes=notes,
                evaluation_timestamp=clock,
                exit_evaluation=exit_eval,
            )
        return StrategyOneExecuteOnceResponse(
            cycle_action="closed",
            had_open_position_at_start=True,
            notes=notes,
            evaluation_timestamp=clock,
            exit_evaluation=exit_eval,
            closed_paper_trade=PaperTradeResponse.model_validate(closed),
        )

    # Flat book: attempt entry from current evaluation bundle.
    if not entry_enabled:
        notes.append("runtime_entry_disabled")
        return StrategyOneExecuteOnceResponse(
            cycle_action="no_action",
            had_open_position_at_start=False,
            notes=notes,
            evaluation_timestamp=clock,
        )
    evaluation, mstatus, chain = build_strategy_one_evaluation_bundle(context, market, settings)
    if evaluation.decision == "no_trade":
        notes.append("entry_evaluator_no_trade_candidate")
        return StrategyOneExecuteOnceResponse(
            cycle_action="no_action",
            had_open_position_at_start=False,
            notes=notes,
            evaluation_timestamp=clock,
            entry_evaluation=evaluation,
        )
    try:
        opened = svc.open_position(
            db,
            evaluation=evaluation,
            chain=chain,
            market_status=mstatus,
            settings=settings,
        )
    except PaperTradeError as exc:
        notes.append(f"auto_open_failed:{exc}")
        return StrategyOneExecuteOnceResponse(
            cycle_action="no_action",
            had_open_position_at_start=False,
            notes=notes,
            evaluation_timestamp=clock,
            entry_evaluation=evaluation,
        )
    return StrategyOneExecuteOnceResponse(
        cycle_action="opened",
        had_open_position_at_start=False,
        notes=notes,
        evaluation_timestamp=clock,
        entry_evaluation=evaluation,
        opened_paper_trade=PaperTradeResponse.model_validate(opened),
    )


def run_emergency_close_open_paper_trade(
    db: Session,
    *,
    paper_trade_id: int,
    market: MarketStoreService,
    settings: Settings,
) -> PaperTrade:
    """Close one open row with emergency reason; requires fresh actionable option quote."""
    resolution = market.resolve_spy_market_for_evaluation()
    mstatus = resolution.final_status
    chain = market.get_latest_chain()
    repo = PaperTradeRepository(db)
    row = repo.get_trade(paper_trade_id)
    if row is None or row.strategy_id != PaperTradeService.STRATEGY_ID or row.status != "open":
        raise PaperTradeError("paper_trade_not_open_for_emergency_close")
    valuation = compute_open_position_valuation(row, chain, settings)
    require_acceptable_exit_quote_for_execution(valuation)
    svc = PaperTradeService()
    return svc.close_position(
        db,
        paper_trade_id=paper_trade_id,
        chain=chain,
        market_status=mstatus,
        exit_reason=EMERGENCY_EXIT_REASON,
        settings=settings,
    )
