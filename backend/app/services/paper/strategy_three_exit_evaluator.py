"""Read-only Strategy 3 exit decision support (deterministic, 0DTE micro-scalper)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.models.trade import PaperTrade
from app.schemas.context import ContextStatusResponse, ContextSummaryResponse
from app.schemas.market import MarketStatusResponse
from app.schemas.paper_trade import PaperOpenPositionValuationResponse
from app.schemas.strategy_one_exit_evaluation import StrategyOneExitEvaluationResponse

_ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class ExitEvaluationInput:
    position: PaperTrade
    valuation: PaperOpenPositionValuationResponse
    context_status: ContextStatusResponse
    context_summary: ContextSummaryResponse
    market_status: MarketStatusResponse
    clock_utc: datetime | None = None


def evaluate_strategy_three_open_exit_readonly(inp: ExitEvaluationInput) -> StrategyOneExitEvaluationResponse:
    now = inp.clock_utc or datetime.now(timezone.utc)
    reasons: list[str] = []
    blockers: list[str] = []

    if not inp.market_status.market_ready:
        blockers.append(f"market_not_ready:{inp.market_status.block_reason}")
    if inp.valuation.valuation_error:
        blockers.append(inp.valuation.valuation_error)
    if not inp.valuation.quote_is_fresh:
        blockers.append("stale_option_quote")
    if not inp.valuation.exit_actionable:
        blockers.append("exit_quote_not_actionable")
    if blockers:
        return StrategyOneExitEvaluationResponse(
            action="hold",
            reasons=["exit_not_actionable_due_to_data_quality"],
            blockers=blockers,
            current_policy_snapshot=inp.position.exit_policy or {},
            current_position_snapshot={"paper_trade_id": inp.position.id, "option_symbol": inp.position.option_symbol},
            current_market_snapshot={"market_ready": inp.market_status.market_ready, "block_reason": inp.market_status.block_reason},
            exit_levels_snapshot={},
            evaluation_timestamp=now,
        )

    current_bid = inp.valuation.current_bid
    if current_bid is None:
        blockers.append("missing_current_bid")
        return StrategyOneExitEvaluationResponse(
            action="hold",
            reasons=["exit_not_actionable_due_to_data_quality"],
            blockers=blockers,
            current_policy_snapshot=inp.position.exit_policy or {},
            current_position_snapshot={"paper_trade_id": inp.position.id, "option_symbol": inp.position.option_symbol},
            current_market_snapshot={"market_ready": inp.market_status.market_ready, "block_reason": inp.market_status.block_reason},
            exit_levels_snapshot={},
            evaluation_timestamp=now,
        )

    policy = inp.position.exit_policy or {}
    stop_frac = float(policy.get("premium_fail_safe_stop_pct", 0.15))
    profit_target_pct = float(policy.get("profit_target_pct", 0.25))
    speed_failure_seconds = int(policy.get("speed_failure_seconds", 75))
    speed_failure_min_profit_pct = float(policy.get("speed_failure_min_profit_pct", 0.05))
    max_hold_seconds = int(policy.get("max_hold_seconds", 240))
    hard_flat_time = str(policy.get("hard_flat_time_et", "15:45"))

    entry_price = float(inp.position.entry_price)
    pnl_pct = (float(current_bid) - entry_price) / entry_price if entry_price > 0 else 0.0
    held_seconds = 0.0
    if inp.position.entry_time is not None:
        entry_time = inp.position.entry_time if inp.position.entry_time.tzinfo else inp.position.entry_time.replace(tzinfo=timezone.utc)
        held_seconds = max((now - entry_time).total_seconds(), 0.0)

    if now.astimezone(_ET).time().strftime("%H:%M") >= hard_flat_time:
        reasons.append("hard_flat_0dte_time")
        action = "close_now"
    elif pnl_pct >= profit_target_pct - 1e-6:
        reasons.append("profit_target_reached")
        action = "close_now"
    elif pnl_pct <= -stop_frac:
        reasons.append("hard_stop_reached")
        action = "close_now"
    elif held_seconds >= max_hold_seconds:
        reasons.append("max_hold_time_reached")
        action = "close_now"
    elif held_seconds >= speed_failure_seconds and pnl_pct < speed_failure_min_profit_pct:
        reasons.append("speed_failure_not_positive_enough")
        action = "close_now"
    else:
        reasons.append("no_exit_rules_triggered")
        action = "hold"

    return StrategyOneExitEvaluationResponse(
        action=action,
        reasons=reasons,
        blockers=[],
        current_policy_snapshot=inp.position.exit_policy or {},
        current_position_snapshot={
            "paper_trade_id": inp.position.id,
            "option_symbol": inp.position.option_symbol,
            "entry_price": inp.position.entry_price,
            "quantity": inp.position.quantity,
        },
        current_market_snapshot={
            "latest_price": inp.context_summary.latest_price,
            "session_vwap": inp.context_summary.session_vwap,
            "market_ready": inp.market_status.market_ready,
        },
        exit_levels_snapshot={
            "pnl_pct": pnl_pct,
            "hard_stop_pct": stop_frac,
            "profit_target_pct": profit_target_pct,
            "held_seconds": held_seconds,
            "speed_failure_seconds": speed_failure_seconds,
            "speed_failure_min_profit_pct": speed_failure_min_profit_pct,
            "max_hold_seconds": max_hold_seconds,
        },
        evaluation_timestamp=now,
    )
