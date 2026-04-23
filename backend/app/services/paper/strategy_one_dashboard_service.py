"""Strategy 1 dashboard assembler using common strategy dashboard schema."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.strategy_runtime_repository import StrategyRuntimeRepository
from app.schemas.strategy_dashboard import (
    StrategyClosedTradeCard,
    StrategyControlsView,
    StrategyCycleHistoryRow,
    StrategyCycleSummary,
    StrategyDashboardResponse,
    StrategyCurrentSignal,
    StrategyIdentity,
    StrategyOpenPositionCard,
    StrategyRuntimeView,
)
from app.services.market.context_service import ContextService
from app.services.market.market_store import MarketStoreService
from app.services.paper.paper_trade_service import PaperTradeService
from app.services.paper.paper_valuation import compute_open_position_valuation
from app.services.paper.strategy_dashboard_service import (
    build_mvp_timeseries,
    compute_headline_metrics,
    compute_max_drawdown_from_curve,
)
from app.services.paper.strategy_one_position_monitor import build_open_positions_monitor
from app.services.paper.strategy_one_runtime_service import get_strategy_one_runtime_coordinator
from app.services.paper.strategy_one_evaluation_bundle import build_strategy_one_evaluation_bundle


def _extract_auto_open_failure(notes_summary: str | None) -> str | None:
    if not notes_summary:
        return None
    token = "auto_open_failed:"
    if token not in notes_summary:
        return None
    return notes_summary.split(token, 1)[1].split("|", 1)[0].strip() or None


def build_strategy_one_dashboard(
    db: Session,
    *,
    context: ContextService,
    market: MarketStoreService,
    settings: Settings,
) -> StrategyDashboardResponse:
    as_of = datetime.now(timezone.utc)
    paper_repo = PaperTradeRepository(db)
    runtime_repo = StrategyRuntimeRepository(db)
    strategy_id = PaperTradeService.STRATEGY_ID

    runtime = get_strategy_one_runtime_coordinator().get_status(db, settings=settings)
    open_rows = paper_repo.list_open(strategy_id=strategy_id)
    closed_recent = paper_repo.list_closed(strategy_id=strategy_id, limit=20)
    closed_chrono = paper_repo.list_closed_chronological(strategy_id=strategy_id, limit=1000)
    cycle_rows = runtime_repo.list_cycle_logs(strategy_id=strategy_id, limit=50)

    st = context.get_status()
    summary = context.get_summary()
    resolution = market.resolve_spy_market_for_evaluation()
    mstatus = resolution.final_status
    chain = market.get_latest_chain()

    monitor = build_open_positions_monitor(
        open_rows,
        chain=chain,
        settings=settings,
        context_status=st,
        context_summary=summary,
        market_status=mstatus,
        evaluation_timestamp=as_of,
    )

    open_cards: list[StrategyOpenPositionCard] = []
    unrealized_total = 0.0
    valuation_errors = 0
    for p in monitor.positions:
        u = p.valuation.unrealized_pnl_bid_basis
        if u is not None:
            unrealized_total += float(u)
        if p.valuation.valuation_error:
            valuation_errors += 1
        mark_price = p.valuation.current_mid if p.valuation.current_mid is not None else p.valuation.current_bid
        open_cards.append(
            StrategyOpenPositionCard(
                paper_trade_id=p.paper_trade_id,
                symbol=p.symbol,
                option_symbol=p.option_symbol,
                side=p.side,
                quantity=p.quantity,
                entry_time=p.entry_time,
                entry_price=p.entry_price,
                mark_price=mark_price,
                unrealized_pnl=u,
                quote_is_fresh=p.valuation.quote_is_fresh,
                exit_actionable=p.valuation.exit_actionable,
                monitor_state=p.monitor_state,
            )
        )

    closed_cards = [
        StrategyClosedTradeCard(
            paper_trade_id=int(r.id),
            symbol=r.symbol,
            option_symbol=r.option_symbol,
            side=r.side,
            quantity=int(r.quantity),
            entry_time=r.entry_time,
            exit_time=r.exit_time,
            realized_pnl=float(r.realized_pnl) if r.realized_pnl is not None else None,
            exit_reason=r.exit_reason,
        )
        for r in closed_recent
    ]
    cycle_cards = [
        StrategyCycleHistoryRow(
            started_at=r.started_at,
            finished_at=r.finished_at,
            result=r.result,
            cycle_action=r.cycle_action,
            notes_summary=r.notes_summary,
            error_code=r.error_code,
        )
        for r in cycle_rows
    ]
    result_counts: dict[str, int] = {}
    blocker_counts: dict[str, int] = {}
    auto_open_failure_count = 0
    for r in cycle_rows:
        result_counts[r.result] = result_counts.get(r.result, 0) + 1
        blocker = _extract_auto_open_failure(r.notes_summary)
        if blocker:
            auto_open_failure_count += 1
            blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
    primary_recent_blocker = (
        max(blocker_counts.items(), key=lambda kv: kv[1])[0] if blocker_counts else None
    )

    eval_now, _, _ = build_strategy_one_evaluation_bundle(context, market, settings)
    candidate_blocked = eval_now.decision in ("candidate_call", "candidate_put") and auto_open_failure_count > 0

    metrics = compute_headline_metrics(closed=closed_chrono, unrealized_pnl=unrealized_total, open_count=len(open_rows))
    open_cost_basis = sum(float(r.entry_price) * int(r.quantity) * 100.0 for r in open_rows)
    metrics.current_cash = float(settings.PAPER_STRATEGY1_ACCOUNT_EQUITY_USD) + float(metrics.realized_pnl) - open_cost_basis
    timeseries = build_mvp_timeseries(
        closed_chronological=closed_chrono,
        current_unrealized_pnl=unrealized_total,
        as_of=as_of,
    )
    metrics.max_drawdown = compute_max_drawdown_from_curve(timeseries.equity_or_value)
    if valuation_errors > 0:
        timeseries.limitations.append("some open-position valuations were non-actionable; unrealized_pnl may be conservative")

    state_counts: dict[str, int] = {}
    for p in monitor.positions:
        state_counts[p.monitor_state] = state_counts.get(p.monitor_state, 0) + 1

    return StrategyDashboardResponse(
        as_of_timestamp=as_of,
        strategy=StrategyIdentity(
            strategy_id=strategy_id,
            strategy_name="Strategy 1 - SPY",
            symbol_scope=["SPY"],
            paper_only=True,
        ),
        runtime=StrategyRuntimeView(
            mode=runtime.mode,
            scheduler_enabled=runtime.scheduler_enabled,
            paused=runtime.paused,
            entry_enabled=runtime.entry_enabled,
            exit_enabled=runtime.exit_enabled,
            running=runtime.running,
            lock_scope=runtime.lock_scope,
            last_cycle_started_at=runtime.last_cycle_started_at,
            last_cycle_finished_at=runtime.last_cycle_finished_at,
            last_cycle_result=runtime.last_cycle_result,
            last_error=runtime.last_error,
            market_window_open=runtime.market_window_open,
            runtime_sleep_reason=runtime.runtime_sleep_reason,
        ),
        controls=StrategyControlsView(),
        current_signal=StrategyCurrentSignal(
            current_decision=eval_now.decision,
            current_reasons=list(eval_now.reasons),
            current_blockers=list(eval_now.blockers),
            candidate_blocked=candidate_blocked,
            candidate_block_reason=primary_recent_blocker if candidate_blocked else None,
        ),
        cycle_summary=StrategyCycleSummary(
            recent_auto_open_failure_count=auto_open_failure_count,
            primary_recent_blocker=primary_recent_blocker,
            recent_result_counts=result_counts,
        ),
        headline_metrics=metrics,
        open_positions=open_cards,
        recent_closed_trades=closed_cards,
        recent_cycle_history=cycle_cards,
        timeseries=timeseries,
        strategy_details={
            "open_monitor_state_counts": state_counts,
            "market_ready": mstatus.market_ready,
            "market_block_reason": mstatus.block_reason,
            "root_cause_note": (
                "Strategy 1 intraday entry uses the same 2-5 calendar DTE band (US/Eastern) in the evaluator "
                "and at paper entry. The option chain snapshot includes a bounded forward multi-expiry pool "
                "(selected_expiration is unset so rows are not collapsed to one expiry). If "
                "paper_entry_intraday_dte_not_in_band still appears, the contract in the evaluation snapshot "
                "likely predates this alignment or no 2-5 DTE rows were quoted in the current pool."
            ),
        },
    )
