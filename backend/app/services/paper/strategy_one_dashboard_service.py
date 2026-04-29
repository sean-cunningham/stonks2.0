"""Strategy 1 dashboard assembler using common strategy dashboard schema."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.repositories.strategy_dashboard_baseline_repository import StrategyDashboardBaselineRepository
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
    StrategyStatsBaselineView,
)
from app.services.market.context_service import ContextService
from app.services.market.market_store import MarketStoreService
from app.services.paper.paper_trade_service import PaperTradeService
from app.services.paper.paper_valuation import compute_open_position_valuation
from app.services.paper.strategy_dashboard_service import (
    build_mvp_timeseries,
    closed_trade_purchase_and_sale_usd,
    compute_current_cash,
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


def _extract_diag_primary_failed_gate(notes_summary: str | None) -> str | None:
    if not notes_summary:
        return None
    token = "diag_primary_failed_gate:"
    if token not in notes_summary:
        return None
    return notes_summary.split(token, 1)[1].split("|", 1)[0].strip() or None


def _extract_affordability_details(notes_summary: str | None) -> dict[str, str] | None:
    if not notes_summary:
        return None
    token = "affordability_diag:"
    if token not in notes_summary:
        return None
    raw = notes_summary.split(token, 1)[1].split("|", 1)[0].strip()
    if not raw:
        return None
    out: dict[str, str] = {}
    for pair in raw.split(";"):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        out[k.strip()] = v.strip()
    return out or None


def _entry_underlying_from_evaluation_snap(row) -> float | None:
    if row is None:
        return None
    snap = getattr(row, "evaluation_snapshot_json", None)
    if not isinstance(snap, dict):
        return None
    lp = snap.get("latest_price")
    if isinstance(lp, (int, float)):
        return float(lp)
    return None


def _pct_and_levels(
    *,
    entry_price: float,
    mark_price: float | None,
    exit_policy: dict | None,
    persisted_stop_price: float | None = None,
    persisted_take_profit_price: float | None = None,
) -> tuple[float | None, float | None, float | None]:
    if entry_price <= 0:
        return None, None, None
    pnl_pct = ((float(mark_price) - entry_price) / entry_price) if mark_price is not None else None
    stop_pct_raw = None
    take_profit_pct_raw = None
    if isinstance(exit_policy, dict):
        stop_pct_raw = exit_policy.get("premium_fail_safe_stop_pct") or exit_policy.get("hard_stop_pct")
        take_profit_pct_raw = exit_policy.get("profit_target_pct") or exit_policy.get("take_profit_pct")
    stop_pct = float(stop_pct_raw) if isinstance(stop_pct_raw, (int, float)) else None
    take_profit_pct = float(take_profit_pct_raw) if isinstance(take_profit_pct_raw, (int, float)) else None
    stop_price = (
        float(persisted_stop_price)
        if persisted_stop_price is not None
        else (entry_price * (1.0 - stop_pct) if stop_pct is not None else None)
    )
    take_profit_price = (
        float(persisted_take_profit_price)
        if persisted_take_profit_price is not None
        else (entry_price * (1.0 + take_profit_pct) if take_profit_pct is not None else None)
    )
    return pnl_pct, stop_price, take_profit_price


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
    baseline_repo = StrategyDashboardBaselineRepository(db)
    baseline = baseline_repo.get_for_strategy(strategy_id=strategy_id)
    scope_start = baseline.reset_at if baseline is not None else None
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
        market=market,
    )

    open_cards: list[StrategyOpenPositionCard] = []
    unrealized_total = 0.0
    valuation_errors = 0
    for p in monitor.positions:
        if scope_start is not None and p.entry_time < scope_start:
            continue
        u = p.valuation.unrealized_pnl_bid_basis
        if u is not None:
            unrealized_total += float(u)
        if p.valuation.valuation_error:
            valuation_errors += 1
        mark_price = p.valuation.current_mid if p.valuation.current_mid is not None else p.valuation.current_bid
        match_row = next((r for r in open_rows if int(r.id) == p.paper_trade_id), None)
        pnl_pct, stop_price, take_profit_price = _pct_and_levels(
            entry_price=float(p.entry_price),
            mark_price=mark_price,
            exit_policy=p.valuation.exit_policy,
            persisted_stop_price=float(match_row.active_stop_price) if match_row and match_row.active_stop_price is not None else None,
            persisted_take_profit_price=(
                float(match_row.take_profit_price) if match_row and match_row.take_profit_price is not None else None
            ),
        )
        exit_blockers = list(p.exit_evaluation.blockers) if p.exit_evaluation.blockers else []
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
                unrealized_pnl_pct=pnl_pct,
                stop_price=stop_price,
                take_profit_price=take_profit_price,
                quote_is_fresh=p.valuation.quote_is_fresh,
                exit_actionable=p.valuation.exit_actionable,
                monitor_state=p.monitor_state,
                current_bid=p.valuation.current_bid,
                current_ask=p.valuation.current_ask,
                quote_timestamp=p.valuation.quote_timestamp_used,
                quote_resolution_source=p.valuation.quote_resolution_source,
                quote_blocker_code=p.valuation.quote_blocker_code,
                exit_blocked_reasons=exit_blockers,
                entry_underlying_price=_entry_underlying_from_evaluation_snap(match_row),
                max_unrealized_pnl_percent=(
                    float(match_row.max_unrealized_pnl_percent)
                    if match_row and match_row.max_unrealized_pnl_percent is not None
                    else None
                ),
                profit_lock_stage=match_row.profit_lock_stage if match_row else None,
            )
        )

    closed_cards = []
    for r in closed_recent:
        if scope_start is not None and (r.exit_time is None or r.exit_time < scope_start):
            continue
        purchase_usd, sale_usd = closed_trade_purchase_and_sale_usd(r)
        closed_cards.append(
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
                total_purchase_price_usd=purchase_usd,
                total_sale_price_usd=sale_usd,
            )
        )
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
    failed_gate_counts: dict[str, int] = {}
    blocker_counts: dict[str, int] = {}
    auto_open_failure_count = 0
    affordability_failure_count = 0
    latest_affordability_details: dict[str, str] | None = None
    for r in cycle_rows:
        result_counts[r.result] = result_counts.get(r.result, 0) + 1
        blocker = _extract_auto_open_failure(r.notes_summary)
        if blocker:
            auto_open_failure_count += 1
            blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
            if blocker == "paper_entry_premium_exceeds_risk_budget":
                affordability_failure_count += 1
                parsed = _extract_affordability_details(r.notes_summary)
                if parsed and latest_affordability_details is None:
                    latest_affordability_details = parsed
        failed_gate = _extract_diag_primary_failed_gate(r.notes_summary)
        if failed_gate:
            failed_gate_counts[failed_gate] = failed_gate_counts.get(failed_gate, 0) + 1
    primary_recent_blocker = (
        max(blocker_counts.items(), key=lambda kv: kv[1])[0] if blocker_counts else None
    )
    most_common_recent_failed_gate = (
        max(failed_gate_counts.items(), key=lambda kv: kv[1])[0] if failed_gate_counts else None
    )

    eval_now, _, _ = build_strategy_one_evaluation_bundle(context, market, settings)
    candidate_blocked = eval_now.decision in ("candidate_call", "candidate_put") and auto_open_failure_count > 0

    scoped_open_rows = open_rows if scope_start is None else [r for r in open_rows if r.entry_time >= scope_start]
    scoped_closed_chrono = (
        closed_chrono
        if scope_start is None
        else [r for r in closed_chrono if r.exit_time is not None and r.exit_time >= scope_start]
    )
    opened_trade_count = (
        len(open_rows) + len(closed_chrono)
        if scope_start is None
        else sum(1 for r in open_rows if r.entry_time >= scope_start)
        + sum(1 for r in closed_chrono if r.entry_time >= scope_start)
    )
    starting_cash = (
        float(baseline.baseline_cash)
        if baseline is not None
        else float(settings.PAPER_STRATEGY1_ACCOUNT_EQUITY_USD)
    )
    metrics = compute_headline_metrics(
        closed=scoped_closed_chrono,
        unrealized_pnl=unrealized_total,
        open_count=len(scoped_open_rows),
        opened_trade_count=opened_trade_count,
    )
    metrics.current_cash = compute_current_cash(
        starting_cash=starting_cash,
        open_rows=scoped_open_rows,
        closed_rows=scoped_closed_chrono,
    )
    timeseries = build_mvp_timeseries(
        closed_chronological=scoped_closed_chrono,
        current_unrealized_pnl=unrealized_total,
        starting_cash=starting_cash,
        current_cash=float(metrics.current_cash or 0.0),
        as_of=as_of,
    )
    metrics.max_drawdown = compute_max_drawdown_from_curve(timeseries.equity_or_value)
    if valuation_errors > 0:
        timeseries.limitations.append("some open-position valuations were non-actionable; unrealized_pnl may be conservative")
    if baseline is not None:
        timeseries.limitations.append("dashboard stats/charts are scoped from the latest manual reset baseline")

    state_counts: dict[str, int] = {}
    for p in monitor.positions:
        state_counts[p.monitor_state] = state_counts.get(p.monitor_state, 0) + 1

    return StrategyDashboardResponse(
        as_of_timestamp=as_of,
        strategy=StrategyIdentity(
            strategy_id=strategy_id,
            strategy_name="SPY Trend Continuation",
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
            recent_failed_gate_counts=failed_gate_counts,
            most_common_recent_failed_gate=most_common_recent_failed_gate,
            current_near_miss_explanation=eval_now.diagnostics.explanation if eval_now.diagnostics else None,
            recent_affordability_failure_count=affordability_failure_count,
            latest_affordability_diagnostics=latest_affordability_details,
        ),
        stats_baseline=(
            StrategyStatsBaselineView(
                reset_at=baseline.reset_at,
                baseline_cash=float(baseline.baseline_cash),
            )
            if baseline is not None
            else None
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
