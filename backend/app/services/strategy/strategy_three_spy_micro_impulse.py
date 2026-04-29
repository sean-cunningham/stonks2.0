"""Read-only SPY Micro Impulse Scalper (0DTE) evaluator (deterministic)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from app.schemas.bars import BarRow
from app.schemas.context import ContextStatusResponse, ContextSummaryResponse
from app.schemas.market import ChainLatestResponse, MarketStatusResponse, NearAtmContract
from app.schemas.strategy import (
    StrategyOneContextSnapshot,
    StrategyOneEvaluationDiagnostics,
    StrategyOneEvaluationResponse,
)
from app.services.market.spy_quote_buffer import get_spy_quote_buffer

STRATEGY3_ID = "strategy_3_spy_micro_impulse"
_ET = ZoneInfo("America/New_York")
_ENTRY_WINDOWS_ET = (
    (time(9, 30), time(16, 0)),
)
_PROXIMITY_PCT = 0.0008
_PROXIMITY_ATR_MULT = 0.20
_MIN_OPTION_MID = 0.20
_MAX_OPTION_MID = 3.00
_MAX_SPREAD_DOLLARS = 0.05
_MAX_SPREAD_PERCENT = 10.0
_MICRO_ABS_15S = 0.20
_MICRO_ABS_30S = 0.30
_MICRO_ATR_FRAC_30S = 0.35


@dataclass(frozen=True)
class StrategyThreeEvalInput:
    status: ContextStatusResponse
    summary: ContextSummaryResponse
    market: MarketStatusResponse
    chain: ChainLatestResponse
    bars_1m: list[BarRow]

    @classmethod
    def from_api(
        cls,
        *,
        status: ContextStatusResponse,
        summary: ContextSummaryResponse,
        market: MarketStatusResponse,
        chain: ChainLatestResponse,
        bars_1m: list[BarRow],
    ) -> "StrategyThreeEvalInput":
        return cls(status=status, summary=summary, market=market, chain=chain, bars_1m=list(bars_1m))


def _snapshot(inp: StrategyThreeEvalInput) -> StrategyOneContextSnapshot:
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


def _is_within_entry_window(now_utc: datetime) -> bool:
    now_et = now_utc.astimezone(_ET).time()
    return any(start <= now_et <= end for start, end in _ENTRY_WINDOWS_ET)


def _trigger_levels(inp: StrategyThreeEvalInput) -> dict[str, float]:
    out: dict[str, float] = {}
    fields = {
        "opening_range_high": inp.summary.opening_range_high,
        "opening_range_low": inp.summary.opening_range_low,
        "session_vwap": inp.summary.session_vwap,
        "recent_swing_high": inp.summary.recent_swing_high,
        "recent_swing_low": inp.summary.recent_swing_low,
    }
    for key, value in fields.items():
        if value is not None:
            out[key] = float(value)
    return out


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
        mid = float(c.mid) if c.mid is not None else (float(c.bid) + float(c.ask)) / 2.0
        if mid < _MIN_OPTION_MID or mid > _MAX_OPTION_MID:
            continue
        spread = float(c.ask) - float(c.bid)
        spread_percent = c.spread_percent
        if spread_percent is None and mid > 0:
            spread_percent = (spread / mid) * 100.0
        spread_ok = spread <= _MAX_SPREAD_DOLLARS or (spread_percent is not None and spread_percent <= _MAX_SPREAD_PERCENT)
        if not spread_ok:
            continue
        eligible.append(c)
    if not eligible:
        return None, 0
    return min(eligible, key=lambda c: abs(float(c.strike) - reference_price)), len(eligible)


def evaluate_strategy_three_spy_micro_impulse(inp: StrategyThreeEvalInput) -> StrategyOneEvaluationResponse:
    now = datetime.now(timezone.utc)
    blockers: list[str] = []
    reasons: list[str] = []
    gate_pass: dict[str, bool] = {}
    near_miss: dict[str, float | bool | str | None] = {}
    contract_gate: dict[str, int | bool | None] = {}
    primary_failed_gate: str | None = None
    micro = get_spy_quote_buffer().get_micro_snapshot(
        atr_5m=float(inp.summary.latest_5m_atr) if inp.summary.latest_5m_atr is not None else None
    )
    near_miss["micro_latest_price"] = micro.get("latest_price")
    near_miss["micro_sample_count"] = micro.get("sample_count")
    near_miss["micro_price_change_15s"] = micro.get("price_change_15s")
    near_miss["micro_price_change_30s"] = micro.get("price_change_30s")
    near_miss["micro_abs_price_change_15s"] = micro.get("abs_price_change_15s")
    near_miss["micro_abs_price_change_30s"] = micro.get("abs_price_change_30s")
    near_miss["micro_atr_fraction_30s"] = micro.get("atr_fraction_30s")
    near_miss["micro_data_available_15s"] = micro.get("data_available_15s")
    near_miss["micro_data_available_30s"] = micro.get("data_available_30s")

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

    gate_pass["entry_window_open"] = _is_within_entry_window(now)
    if not gate_pass["entry_window_open"]:
        primary_failed_gate = "entry_window_open"
        return fail(
            "entry_window_open",
            "outside_strategy_3_entry_window",
            "Entries are only allowed in regular RTH.",
        )

    latest = inp.summary.latest_price
    atr = inp.summary.latest_5m_atr
    gate_pass["required_metrics_present"] = (
        latest is not None
        and atr is not None
        and atr > 0
        and inp.summary.opening_range_high is not None
        and inp.summary.opening_range_low is not None
        and inp.summary.recent_swing_high is not None
        and inp.summary.recent_swing_low is not None
    )
    if not gate_pass["required_metrics_present"]:
        primary_failed_gate = "required_metrics_present"
        return fail(
            "required_metrics_present",
            "missing_metrics:price_levels_or_atr",
            "Required metrics (price, levels, ATR) are missing for micro-impulse evaluation.",
        )

    assert latest is not None and atr is not None
    trigger_levels = _trigger_levels(inp)
    gate_pass["trigger_levels_available"] = len(trigger_levels) > 0
    if not gate_pass["trigger_levels_available"]:
        primary_failed_gate = "trigger_levels_available"
        return fail(
            "trigger_levels_available",
            "missing_trigger_levels",
            "No trigger levels are available for Strategy 3.",
        )

    proximity_band = max(float(latest) * _PROXIMITY_PCT, _PROXIMITY_ATR_MULT * float(atr))
    near_miss["proximity_band"] = proximity_band
    nearest_trigger_name = None
    nearest_trigger_level = None
    nearest_trigger_dist = None
    for name, level in trigger_levels.items():
        dist = abs(float(latest) - float(level))
        if nearest_trigger_dist is None or dist < nearest_trigger_dist:
            nearest_trigger_name = name
            nearest_trigger_level = level
            nearest_trigger_dist = dist
    near_miss["nearest_trigger_name"] = nearest_trigger_name
    near_miss["nearest_trigger_level"] = nearest_trigger_level
    near_miss["nearest_trigger_distance"] = nearest_trigger_dist
    gate_pass["near_trigger_level"] = nearest_trigger_dist is not None and nearest_trigger_dist <= proximity_band
    if not gate_pass["near_trigger_level"]:
        primary_failed_gate = "near_trigger_level"
        return fail(
            "near_trigger_level",
            "not_near_any_trigger_level",
            "Price is not inside the Strategy 3 trigger proximity band.",
        )

    data_15 = bool(micro.get("data_available_15s"))
    data_30 = bool(micro.get("data_available_30s"))
    gate_pass["micro_data_available"] = data_15 or data_30
    if not gate_pass["micro_data_available"]:
        primary_failed_gate = "micro_data_available"
        return fail(
            "micro_data_available",
            "micro_data_unavailable",
            "Micro quote data is not yet available in the SPY buffer.",
        )

    delta_15 = micro.get("price_change_15s")
    delta_30 = micro.get("price_change_30s")
    abs_15 = abs(float(delta_15)) if isinstance(delta_15, (int, float)) else None
    abs_30 = abs(float(delta_30)) if isinstance(delta_30, (int, float)) else None
    atr_30 = micro.get("atr_fraction_30s")

    micro_reasons: list[str] = []
    if abs_15 is not None and abs_15 >= _MICRO_ABS_15S:
        micro_reasons.append("abs_15s>=0.20")
    if abs_30 is not None and abs_30 >= _MICRO_ABS_30S:
        micro_reasons.append("abs_30s>=0.30")
    if isinstance(atr_30, (int, float)) and float(atr_30) >= _MICRO_ATR_FRAC_30S:
        micro_reasons.append("abs_30s>=0.35x_atr5m")
    micro_impulse_passed = bool(micro_reasons)
    near_miss["micro_impulse_passed"] = micro_impulse_passed
    near_miss["micro_impulse_reason"] = ",".join(micro_reasons) if micro_reasons else "none"
    gate_pass["micro_impulse_passed"] = micro_impulse_passed
    if not micro_impulse_passed:
        primary_failed_gate = "micro_impulse_passed"
        return fail(
            "micro_impulse_passed",
            "micro_impulse_below_threshold",
            "Micro movement did not satisfy Strategy 3 impulse thresholds.",
        )

    assert nearest_trigger_name is not None and nearest_trigger_level is not None
    curr_price = float(latest)
    prev_15 = micro.get("price_15s_ago")
    prev_30 = micro.get("price_30s_ago")
    prev_candidates = [float(v) for v in (prev_15, prev_30) if isinstance(v, (int, float))]
    positive_micro = (isinstance(delta_15, (int, float)) and float(delta_15) > 0) or (
        isinstance(delta_30, (int, float)) and float(delta_30) > 0
    )
    negative_micro = (isinstance(delta_15, (int, float)) and float(delta_15) < 0) or (
        isinstance(delta_30, (int, float)) and float(delta_30) < 0
    )
    resistance_triggers = {"opening_range_high", "recent_swing_high", "previous_day_high", "session_vwap"}
    support_triggers = {"opening_range_low", "recent_swing_low", "previous_day_low", "session_vwap"}
    crossed_up = curr_price > float(nearest_trigger_level) and any(p <= float(nearest_trigger_level) for p in prev_candidates)
    crossed_down = curr_price < float(nearest_trigger_level) and any(p >= float(nearest_trigger_level) for p in prev_candidates)
    crossed_trigger = crossed_up or crossed_down
    near_miss["crossed_trigger"] = crossed_trigger
    near_miss["rejected_trigger"] = False

    setup_type = "none"
    if nearest_trigger_name in resistance_triggers and positive_micro and crossed_up:
        setup_type = "call_micro_breakout"
    elif nearest_trigger_name in support_triggers and negative_micro and crossed_down:
        setup_type = "put_micro_breakdown"
    near_miss["setup_type"] = setup_type
    gate_pass["setup_type_detected"] = setup_type != "none"
    if setup_type == "none":
        primary_failed_gate = "setup_type_detected"
        return fail(
            "setup_type_detected",
            "micro_no_trigger_cross",
            "Micro impulse passed but no deterministic breakout/breakdown trigger cross was detected.",
        )

    side = "call" if setup_type.startswith("call_") else "put"
    reasons.extend(
        [
            f"setup_type:{setup_type}",
            f"trigger_level:{nearest_trigger_name}",
            f"proximity_band:{proximity_band:.4f}",
            f"micro_15s:{float(delta_15):.4f}" if isinstance(delta_15, (int, float)) else "micro_15s:na",
            f"micro_30s:{float(delta_30):.4f}" if isinstance(delta_30, (int, float)) else "micro_30s:na",
            f"micro_atr_frac_30s:{float(atr_30):.4f}" if isinstance(atr_30, (int, float)) else "micro_atr_frac_30s:na",
        ]
    )

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

    contract_gate["selected_contract_present"] = True
    near_miss["selected_option_symbol"] = cand.option_symbol
    near_miss["selected_strike"] = float(cand.strike)
    near_miss["selected_bid"] = float(cand.bid) if cand.bid is not None else None
    near_miss["selected_ask"] = float(cand.ask) if cand.ask is not None else None
    near_miss["selected_spread_percent"] = float(cand.spread_percent) if cand.spread_percent is not None else None

    diagnostics = StrategyOneEvaluationDiagnostics(
        gate_pass=gate_pass,
        primary_failed_gate=None,
        failed_gates=[],
        near_miss=near_miss,
        contract_gate=contract_gate,
        explanation="0DTE micro-impulse candidate detected with deterministic trigger cross.",
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
