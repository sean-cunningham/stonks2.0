"""Read-only Strategy 2 exit decision support (deterministic, 0DTE-focused)."""

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


def evaluate_strategy_two_open_exit_readonly(inp: ExitEvaluationInput) -> StrategyOneExitEvaluationResponse:
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

    unreal = float(inp.valuation.unrealized_pnl_bid_basis or 0.0)
    entry_cost = float(inp.position.entry_price) * float(inp.position.quantity) * 100.0
    loss_frac = abs(unreal) / entry_cost if entry_cost > 0 and unreal < 0 else 0.0
    stop_frac = float((inp.position.exit_policy or {}).get("premium_fail_safe_stop_pct", 0.35))

    if now.astimezone(_ET).time().strftime("%H:%M") >= "15:58":
        reasons.append("hard_flat_0dte_time")
        action = "close_now"
    elif loss_frac >= stop_frac:
        reasons.append("premium_fail_safe_stop_triggered")
        action = "close_now"
    elif unreal >= 0 and inp.context_summary.latest_price is not None and inp.context_summary.session_vwap is not None:
        # Trim when impulse mean-reverts through VWAP.
        if inp.position.entry_decision == "candidate_call" and inp.context_summary.latest_price < inp.context_summary.session_vwap:
            reasons.append("vwap_cross_against_call")
            action = "close_now"
        elif inp.position.entry_decision == "candidate_put" and inp.context_summary.latest_price > inp.context_summary.session_vwap:
            reasons.append("vwap_cross_against_put")
            action = "close_now"
        else:
            reasons.append("no_exit_rules_triggered")
            action = "hold"
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
        exit_levels_snapshot={"loss_fraction": loss_frac, "fail_safe_stop_fraction": stop_frac},
        evaluation_timestamp=now,
    )
