"""Read-only Strategy 2 SPY 0DTE volatility sniper evaluator (deterministic)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.schemas.context import ContextStatusResponse, ContextSummaryResponse
from app.schemas.market import ChainLatestResponse, MarketStatusResponse, NearAtmContract
from app.schemas.strategy import (
    StrategyOneContextSnapshot,
    StrategyOneEvaluationDiagnostics,
    StrategyOneEvaluationResponse,
)

STRATEGY2_ID = "strategy_2_spy_0dte_vol_sniper"
_ET = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class StrategyTwoEvalInput:
    status: ContextStatusResponse
    summary: ContextSummaryResponse
    market: MarketStatusResponse
    chain: ChainLatestResponse

    @classmethod
    def from_api(
        cls,
        *,
        status: ContextStatusResponse,
        summary: ContextSummaryResponse,
        market: MarketStatusResponse,
        chain: ChainLatestResponse,
    ) -> "StrategyTwoEvalInput":
        return cls(status=status, summary=summary, market=market, chain=chain)


def _snapshot(inp: StrategyTwoEvalInput) -> StrategyOneContextSnapshot:
    return StrategyOneContextSnapshot(
        symbol="SPY",
        us_equity_rth_open=inp.status.us_equity_rth_open,
        context_ready_for_live_trading=inp.status.context_ready_for_live_trading,
        context_block_reason=inp.status.block_reason,
        latest_price=inp.summary.latest_price,
        session_vwap=inp.summary.session_vwap,
        opening_range_high=inp.summary.opening_range_high,
        opening_range_low=inp.summary.opening_range_low,
        latest_5m_atr=inp.summary.latest_5m_atr,
        recent_swing_high=inp.summary.recent_swing_high,
        recent_swing_low=inp.summary.recent_swing_low,
        market_ready=inp.market.market_ready,
        market_block_reason=inp.market.block_reason,
        chain_available=inp.chain.available,
        chain_option_quotes_available=inp.chain.option_quotes_available,
        chain_selected_expiration=inp.chain.selected_expiration,
        underlying_reference_price=inp.chain.underlying_reference_price,
        quote_timestamp_used=inp.market.latest_quote_time,
        quote_age_seconds=inp.market.quote_age_seconds,
        quote_freshness_threshold_seconds=None,
        quote_stale=not inp.market.quote_is_fresh,
    )


def _is_0dte(expiration_date: str | None, now_utc: datetime) -> bool:
    if not expiration_date:
        return False
    return expiration_date == now_utc.astimezone(_ET).date().isoformat()


def _pick_0dte_contract(
    *,
    contracts: list[NearAtmContract],
    side: str,
    reference_price: float,
    now_utc: datetime,
) -> tuple[NearAtmContract | None, int]:
    eligible: list[NearAtmContract] = []
    for c in contracts:
        if not _is_0dte(c.expiration_date, now_utc):
            continue
        if side == "call" and not c.is_call:
            continue
        if side == "put" and not c.is_put:
            continue
        if c.ask is None or c.ask <= 0:
            continue
        if c.bid is None or c.bid <= 0:
            continue
        eligible.append(c)
    if not eligible:
        return None, 0
    return min(eligible, key=lambda c: abs(float(c.strike) - reference_price)), len(eligible)


def evaluate_strategy_two_spy_0dte_vol_sniper(inp: StrategyTwoEvalInput) -> StrategyOneEvaluationResponse:
    now = datetime.now(timezone.utc)
    blockers: list[str] = []
    reasons: list[str] = []
    gate_pass: dict[str, bool] = {}
    near_miss: dict[str, float | bool | str | None] = {}
    contract_gate: dict[str, int | bool | None] = {}
    primary_failed_gate: str | None = None

    def fail(gate: str, blocker: str, explanation: str) -> StrategyOneEvaluationResponse:
        failed = [name for name, passed in gate_pass.items() if not passed]
        diagnostics = StrategyOneEvaluationDiagnostics(
            gate_pass=gate_pass,
            primary_failed_gate=primary_failed_gate or gate,
            failed_gates=failed,
            near_miss=near_miss,
            contract_gate=contract_gate,
            explanation=explanation,
        )
        return StrategyOneEvaluationResponse(
            decision="no_trade",
            blockers=blockers + [blocker],
            reasons=reasons,
            context_snapshot_used=_snapshot(inp),
            contract_candidate=None,
            evaluation_timestamp=now,
            swing_promotion_eligible=False,
            diagnostics=diagnostics,
        )

    gate_pass["context_live_ready"] = inp.status.context_ready_for_live_trading
    if not gate_pass["context_live_ready"]:
        primary_failed_gate = "context_live_ready"
        return fail(
            "context_live_ready",
            f"context_not_live_ready:{inp.status.block_reason}",
            "Context is not ready for live trading.",
        )

    gate_pass["market_ready"] = inp.market.market_ready
    if not gate_pass["market_ready"]:
        primary_failed_gate = "market_ready"
        return fail(
            "market_ready",
            f"market_not_ready:{inp.market.block_reason}",
            "Market status is not ready for execution.",
        )

    latest = inp.summary.latest_price
    vwap = inp.summary.session_vwap
    atr = inp.summary.latest_5m_atr
    gate_pass["required_metrics_present"] = latest is not None and vwap is not None and atr is not None and atr > 0
    if not gate_pass["required_metrics_present"]:
        primary_failed_gate = "required_metrics_present"
        return fail(
            "required_metrics_present",
            "missing_metrics:price_vwap_or_atr",
            "Required metrics (price, VWAP, ATR) are missing for sniper evaluation.",
        )

    assert latest is not None and vwap is not None and atr is not None
    speed_ratio = abs(float(latest) - float(vwap)) / float(atr)
    near_miss["speed_ratio"] = speed_ratio
    gate_pass["volatility_impulse"] = speed_ratio >= 0.35
    if not gate_pass["volatility_impulse"]:
        primary_failed_gate = "volatility_impulse"
        return fail(
            "volatility_impulse",
            "no_volatility_impulse",
            "Price speed versus ATR is below sniper threshold.",
        )
    reasons.append("volatility_impulse_detected")

    side = "call" if latest > vwap else "put"
    reasons.append("price_above_vwap" if side == "call" else "price_below_vwap")

    cand, eligible_count = _pick_0dte_contract(
        contracts=inp.chain.near_atm_contracts,
        side=side,
        reference_price=float(latest),
        now_utc=now,
    )
    contract_gate["eligible_0dte_contracts_for_side"] = eligible_count
    gate_pass["contract_selected"] = cand is not None
    if cand is None:
        primary_failed_gate = "contract_selected"
        return fail(
            "contract_selected",
            "no_acceptable_option_contract_0dte",
            "No acceptable 0DTE contract was available for the detected side.",
        )

    diagnostics = StrategyOneEvaluationDiagnostics(
        gate_pass=gate_pass,
        primary_failed_gate=None,
        failed_gates=[],
        near_miss=near_miss,
        contract_gate=contract_gate,
        explanation="0DTE sniper candidate detected with sufficient volatility impulse.",
    )
    return StrategyOneEvaluationResponse(
        decision="candidate_call" if side == "call" else "candidate_put",
        blockers=[],
        reasons=reasons,
        context_snapshot_used=_snapshot(inp),
        contract_candidate=cand,
        evaluation_timestamp=now,
        swing_promotion_eligible=False,
        diagnostics=diagnostics,
    )
