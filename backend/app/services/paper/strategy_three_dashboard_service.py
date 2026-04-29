"""Strategy 3 dashboard assembler using common strategy dashboard schema."""

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
    StrategyCurrentSignal,
    StrategyDashboardResponse,
    StrategyHeadlineMetrics,
    StrategyIdentity,
    StrategyOpenPositionCard,
    StrategyRuntimeView,
    StrategyStatsBaselineView,
)
from app.services.market.context_service import ContextService
from app.services.market.market_store import MarketStoreService
from app.services.paper.paper_valuation import compute_open_position_valuation
from app.services.paper.strategy_dashboard_service import (
    build_mvp_timeseries,
    closed_trade_purchase_and_sale_usd,
    compute_current_cash,
    compute_headline_metrics,
    compute_max_drawdown_from_curve,
)
from app.services.paper.strategy_three_evaluation_bundle import build_strategy_three_evaluation_bundle
from app.services.paper.strategy_three_runtime_service import get_strategy_three_runtime_coordinator
from app.services.paper.strategy_three_paper_trade_service import StrategyThreePaperTradeService


def _extract_auto_open_failure(notes_summary: str | None) -> str | None:
    if not notes_summary or "auto_open_failed:" not in notes_summary:
        return None
    return notes_summary.split("auto_open_failed:", 1)[1].split("|", 1)[0].strip() or None


def _extract_affordability_details(notes_summary: str | None) -> dict[str, str] | None:
    if not notes_summary or "affordability_diag:" not in notes_summary:
        return None
    raw = notes_summary.split("affordability_diag:", 1)[1].split("|", 1)[0].strip()
    out: dict[str, str] = {}
    for pair in raw.split(";"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            out[k.strip()] = v.strip()
    return out or None


def build_strategy_three_dashboard(
    db: Session,
    *,
    context: ContextService,
    market: MarketStoreService,
    settings: Settings,
) -> StrategyDashboardResponse:
    as_of = datetime.now(timezone.utc)
    strategy_id = StrategyThreePaperTradeService.STRATEGY_ID
    paper_repo = PaperTradeRepository(db)
    runtime_repo = StrategyRuntimeRepository(db)

    runtime = get_strategy_three_runtime_coordinator().get_status(db, settings=settings)
    baseline_repo = StrategyDashboardBaselineRepository(db)
    baseline = baseline_repo.get_for_strategy(strategy_id=strategy_id)
    scope_start = baseline.reset_at if baseline is not None else None
    open_rows = paper_repo.list_open(strategy_id=strategy_id)
    closed_recent = paper_repo.list_closed(strategy_id=strategy_id, limit=20)
    closed_chrono = paper_repo.list_closed_chronological(strategy_id=strategy_id, limit=1000)
    cycle_rows = runtime_repo.list_cycle_logs(strategy_id=strategy_id, limit=50)

    market.resolve_spy_market_for_evaluation()
    chain = market.get_latest_chain()
    open_cards: list[StrategyOpenPositionCard] = []
    unrealized_total = 0.0
    valuation_errors = 0
    for row in open_rows:
        if scope_start is not None and row.entry_time < scope_start:
            continue
        valuation = compute_open_position_valuation(row, chain, settings)
        unrealized = valuation.unrealized_pnl_bid_basis
        if unrealized is not None:
            unrealized_total += float(unrealized)
        if valuation.valuation_error:
            valuation_errors += 1
        mark_price = valuation.current_mid if valuation.current_mid is not None else valuation.current_bid
        open_cards.append(
            StrategyOpenPositionCard(
                paper_trade_id=row.id,
                symbol=row.symbol,
                option_symbol=row.option_symbol,
                side=row.side,
                quantity=row.quantity,
                entry_time=row.entry_time,
                entry_price=row.entry_price,
                mark_price=mark_price,
                unrealized_pnl=unrealized,
                quote_is_fresh=valuation.quote_is_fresh,
                exit_actionable=valuation.exit_actionable,
                monitor_state="healthy" if valuation.exit_actionable else "blocked",
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

    blocker_counts: dict[str, int] = {}
    result_counts: dict[str, int] = {}
    auto_open_failure_count = 0
    affordability_failure_count = 0
    latest_affordability_details: dict[str, str] | None = None
    for row in cycle_rows:
        result_counts[row.result] = result_counts.get(row.result, 0) + 1
        blocker = _extract_auto_open_failure(row.notes_summary)
        if blocker:
            auto_open_failure_count += 1
            blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
            if blocker == "paper_entry_exceeds_max_position_cost":
                affordability_failure_count += 1
                if latest_affordability_details is None:
                    latest_affordability_details = _extract_affordability_details(row.notes_summary)
    primary_recent_blocker = max(blocker_counts.items(), key=lambda kv: kv[1])[0] if blocker_counts else None

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
    evaluation_now, mstatus, _ = build_strategy_three_evaluation_bundle(context, market, settings)
    metrics: StrategyHeadlineMetrics = compute_headline_metrics(
        closed=scoped_closed_chrono,
        unrealized_pnl=unrealized_total,
        open_count=len(scoped_open_rows),
        opened_trade_count=opened_trade_count,
    )
    starting_cash = (
        float(baseline.baseline_cash)
        if baseline is not None
        else float(settings.PAPER_STRATEGY3_ACCOUNT_EQUITY_USD)
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
    if valuation_errors:
        timeseries.limitations.append("some open-position valuations were non-actionable; unrealized_pnl may be conservative")
    if baseline is not None:
        timeseries.limitations.append("dashboard stats/charts are scoped from the latest manual reset baseline")

    diag = evaluation_now.diagnostics
    near = diag.near_miss if diag is not None and diag.near_miss is not None else {}
    contract_diag = diag.contract_gate if diag is not None and diag.contract_gate is not None else {}

    return StrategyDashboardResponse(
        as_of_timestamp=as_of,
        strategy=StrategyIdentity(
            strategy_id=strategy_id,
            strategy_name="SPY Micro Impulse Scalper (0DTE)",
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
            current_decision=evaluation_now.decision,
            current_reasons=list(evaluation_now.reasons),
            current_blockers=list(evaluation_now.blockers),
            candidate_blocked=primary_recent_blocker is not None,
            candidate_block_reason=primary_recent_blocker,
        ),
        cycle_summary=StrategyCycleSummary(
            recent_auto_open_failure_count=sum(blocker_counts.values()),
            primary_recent_blocker=primary_recent_blocker,
            recent_result_counts=result_counts,
            recent_failed_gate_counts={},
            most_common_recent_failed_gate=None,
            current_near_miss_explanation=evaluation_now.diagnostics.explanation if evaluation_now.diagnostics else None,
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
            "market_ready": mstatus.market_ready,
            "market_block_reason": mstatus.block_reason,
            "strategy_profile": "deterministic_0dte_micro_impulse",
            "primary_failed_gate": diag.primary_failed_gate if diag is not None else None,
            "nearest_trigger_name": near.get("nearest_trigger_name"),
            "nearest_trigger_distance": near.get("nearest_trigger_distance"),
            "proximity_band": near.get("proximity_band"),
            "micro_price_change_15s": near.get("micro_price_change_15s"),
            "micro_price_change_30s": near.get("micro_price_change_30s"),
            "micro_atr_fraction_30s": near.get("micro_atr_fraction_30s"),
            "micro_impulse_passed": near.get("micro_impulse_passed"),
            "micro_impulse_reason": near.get("micro_impulse_reason"),
            "crossed_trigger": near.get("crossed_trigger"),
            "setup_type": near.get("setup_type"),
            "selected_contract_diagnostics": contract_diag,
        },
    )
