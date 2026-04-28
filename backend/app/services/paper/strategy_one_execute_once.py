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


def _append_primary_failed_gate_note(notes: list[str], gate: str | None) -> None:
    if gate:
        notes.append(f"diag_primary_failed_gate:{gate}")


def _append_affordability_details_note(notes: list[str], details: dict | None) -> None:
    if not details:
        return
    keys = [
        "attempted_option_symbol",
        "attempted_side",
        "attempted_expiration_date",
        "attempted_strike",
        "attempted_ask",
        "attempted_total_premium_usd",
        "account_equity_used",
        "max_risk_pct_used",
        "fail_safe_stop_pct_used",
        "risk_budget_usd",
        "max_affordable_premium_usd",
        "premium_over_budget_usd",
        "affordability_block_reason",
    ]
    parts: list[str] = []
    for k in keys:
        if k in details:
            parts.append(f"{k}={details[k]}")
    if parts:
        notes.append("affordability_diag:" + ";".join(parts))


def _primary_failed_gate_from_evaluation(evaluation) -> str | None:
    diag = getattr(evaluation, "diagnostics", None)
    if diag is None:
        return None
    return getattr(diag, "primary_failed_gate", None)


def _apply_exit_state_from_evaluation(*, row: PaperTrade, exit_eval, repo: PaperTradeRepository) -> None:
    """Persist Strategy 1 dynamic exit-state fields computed by exit evaluator."""
    snap = getattr(exit_eval, "exit_levels_snapshot", None)
    if not isinstance(snap, dict):
        return
    changed = False
    active_stop = snap.get("active_stop_price")
    take_profit = snap.get("take_profit_price")
    max_u_pct = snap.get("max_unrealized_pnl_percent")
    stage = snap.get("profit_lock_stage")
    if isinstance(active_stop, (int, float)):
        v = float(active_stop)
        if row.active_stop_price is None or abs(float(row.active_stop_price) - v) > 1e-12:
            row.active_stop_price = v
            changed = True
    if isinstance(take_profit, (int, float)):
        v = float(take_profit)
        if row.take_profit_price is None or abs(float(row.take_profit_price) - v) > 1e-12:
            row.take_profit_price = v
            changed = True
    if isinstance(max_u_pct, (int, float)):
        v = float(max_u_pct)
        if row.max_unrealized_pnl_percent is None or abs(float(row.max_unrealized_pnl_percent) - v) > 1e-12:
            row.max_unrealized_pnl_percent = v
            changed = True
    if isinstance(stage, str):
        if row.profit_lock_stage != stage:
            row.profit_lock_stage = stage
            changed = True
    if changed:
        repo.update_trade(row)


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
        held = market.resolve_open_paper_option_contract(option_symbol=row.option_symbol, chain=chain)
        valuation = compute_open_position_valuation(
            row, chain, settings, now=clock, held_resolution=held
        )
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
        _apply_exit_state_from_evaluation(row=row, exit_eval=exit_eval, repo=repo)
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
                held_contract_resolution=held,
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
        _append_primary_failed_gate_note(notes, _primary_failed_gate_from_evaluation(evaluation))
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
        _append_primary_failed_gate_note(notes, _primary_failed_gate_from_evaluation(evaluation))
        if str(exc) == "paper_entry_premium_exceeds_risk_budget":
            _append_affordability_details_note(notes, getattr(exc, "details", None))
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
    held = market.resolve_open_paper_option_contract(option_symbol=row.option_symbol, chain=chain)
    valuation = compute_open_position_valuation(row, chain, settings, held_resolution=held)
    require_acceptable_exit_quote_for_execution(valuation)
    svc = PaperTradeService()
    return svc.close_position(
        db,
        paper_trade_id=paper_trade_id,
        chain=chain,
        market_status=mstatus,
        exit_reason=EMERGENCY_EXIT_REASON,
        settings=settings,
        held_contract_resolution=held,
    )
