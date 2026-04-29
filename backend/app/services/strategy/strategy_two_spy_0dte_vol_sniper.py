"""Read-only Strategy 2 SPY 0DTE volatility sniper evaluator (deterministic)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from statistics import mean
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

STRATEGY2_ID = "strategy_2_spy_0dte_vol_sniper"
_ET = ZoneInfo("America/New_York")
_ENTRY_WINDOWS_ET = (
    (time(9, 45), time(11, 30)),
    (time(13, 45), time(15, 45)),
)
_PROXIMITY_PCT = 0.0008
_PROXIMITY_ATR_MULT = 0.20
_MIN_ABS_1M_RETURN_PCT = 0.0008
_MIN_1M_RANGE_ATR_MULT = 0.45
_MIN_1M_VOLUME_MULT = 1.75
_MIN_OPTION_MID = 0.20
_MAX_OPTION_MID = 3.00
_MAX_SPREAD_DOLLARS = 0.05
_MAX_SPREAD_PERCENT = 10.0


@dataclass(frozen=True)
class StrategyTwoEvalInput:
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
    ) -> "StrategyTwoEvalInput":
        return cls(status=status, summary=summary, market=market, chain=chain, bars_1m=list(bars_1m))


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


def _is_within_entry_window(now_utc: datetime) -> bool:
    # Temporary override for active paper debugging: bypass time-window gating.
    # Keep all other strategy filters unchanged (context/market/speed/volume/contract).
    _ = now_utc
    return True


def _current_1m_signal_metrics(inp: StrategyTwoEvalInput) -> tuple[float | None, float | None, float | None]:
    bars = inp.bars_1m
    if len(bars) < 21:
        return None, None, None
    latest = bars[-1]
    if latest.open is None or latest.close is None or latest.high is None or latest.low is None:
        return None, None, None
    if latest.open <= 0:
        return None, None, None
    abs_return_pct = abs((float(latest.close) - float(latest.open)) / float(latest.open))
    avg_volume_20 = mean(float(b.volume or 0.0) for b in bars[-21:-1])
    volume_mult = (float(latest.volume or 0.0) / avg_volume_20) if avg_volume_20 > 0 else None
    one_min_range = float(latest.high) - float(latest.low)
    atr = float(inp.summary.latest_5m_atr or 0.0)
    range_atr_ratio = (one_min_range / atr) if atr > 0 else None
    return abs_return_pct, range_atr_ratio, volume_mult


def _trigger_levels(inp: StrategyTwoEvalInput) -> dict[str, float]:
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
    # Previous day levels if available from 1m bars.
    if inp.bars_1m:
        now_et_day = datetime.now(timezone.utc).astimezone(_ET).date()
        prev_day_high = None
        prev_day_low = None
        for b in inp.bars_1m:
            b_day = b.bar_time.astimezone(_ET).date()
            if b_day >= now_et_day:
                continue
            prev_day_high = float(b.high) if prev_day_high is None else max(prev_day_high, float(b.high))
            prev_day_low = float(b.low) if prev_day_low is None else min(prev_day_low, float(b.low))
        if prev_day_high is not None:
            out["previous_day_high"] = prev_day_high
        if prev_day_low is not None:
            out["previous_day_low"] = prev_day_low
    return out


def _choose_setup(
    *,
    latest_price: float,
    one_min_return_signed: float,
    trigger_name: str,
) -> str:
    bullish = one_min_return_signed >= _MIN_ABS_1M_RETURN_PCT
    bearish = one_min_return_signed <= -_MIN_ABS_1M_RETURN_PCT
    upper_triggers = {"opening_range_high", "recent_swing_high", "previous_day_high"}
    lower_triggers = {"opening_range_low", "recent_swing_low", "previous_day_low"}
    if trigger_name in upper_triggers:
        if bullish:
            return "call_breakout"
        if bearish:
            return "put_rejection"
    if trigger_name in lower_triggers:
        if bearish:
            return "put_breakdown"
        if bullish:
            return "call_rejection"
    if trigger_name == "session_vwap":
        if bullish and latest_price >= 0:
            return "call_breakout"
        if bearish:
            return "put_breakdown"
    return "none"


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


def evaluate_strategy_two_spy_0dte_vol_sniper(inp: StrategyTwoEvalInput) -> StrategyOneEvaluationResponse:
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
            "outside_strategy_2_entry_window",
            "Entries are only allowed 09:45-11:30 ET and 13:45-15:45 ET.",
        )

    latest = inp.summary.latest_price
    vwap = inp.summary.session_vwap
    atr = inp.summary.latest_5m_atr
    gate_pass["required_metrics_present"] = (
        latest is not None
        and vwap is not None
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
            "Required metrics (price, levels, ATR) are missing for sniper evaluation.",
        )

    assert latest is not None and vwap is not None and atr is not None
    trigger_levels = _trigger_levels(inp)
    gate_pass["trigger_levels_available"] = len(trigger_levels) > 0
    if not gate_pass["trigger_levels_available"]:
        primary_failed_gate = "trigger_levels_available"
        return fail(
            "trigger_levels_available",
            "missing_trigger_levels",
            "No trigger levels are available for Strategy 2.",
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
            "Price is not inside the Strategy 2 trigger proximity band.",
        )

    one_min_metrics = _current_1m_signal_metrics(inp)
    if one_min_metrics[0] is None or one_min_metrics[1] is None or one_min_metrics[2] is None:
        primary_failed_gate = "one_min_signal_metrics_available"
        return fail(
            "one_min_signal_metrics_available",
            "missing_one_min_signal_metrics",
            "Recent 1-minute bars are insufficient for speed/range/volume checks.",
        )

    current_abs_1m_return, current_1m_range_atr_ratio, current_1m_volume_mult = one_min_metrics
    latest_bar = inp.bars_1m[-1]
    one_min_signed_return = (float(latest_bar.close) - float(latest_bar.open)) / float(latest_bar.open)
    near_miss["current_1m_return_abs_pct"] = current_abs_1m_return
    near_miss["current_1m_range_atr_ratio"] = current_1m_range_atr_ratio
    near_miss["current_1m_volume_multiple"] = current_1m_volume_mult

    gate_pass["speed_return_confirmed"] = current_abs_1m_return >= _MIN_ABS_1M_RETURN_PCT
    if not gate_pass["speed_return_confirmed"]:
        primary_failed_gate = "speed_return_confirmed"
        return fail(
            "speed_return_confirmed",
            "one_min_return_below_threshold",
            "Absolute 1-minute return did not meet Strategy 2 speed threshold.",
        )

    gate_pass["speed_range_confirmed"] = current_1m_range_atr_ratio >= _MIN_1M_RANGE_ATR_MULT
    if not gate_pass["speed_range_confirmed"]:
        primary_failed_gate = "speed_range_confirmed"
        return fail(
            "speed_range_confirmed",
            "one_min_range_below_threshold",
            "Current 1-minute range did not meet Strategy 2 ATR-based speed threshold.",
        )

    gate_pass["volume_confirmed"] = current_1m_volume_mult >= _MIN_1M_VOLUME_MULT
    if not gate_pass["volume_confirmed"]:
        primary_failed_gate = "volume_confirmed"
        return fail(
            "volume_confirmed",
            "one_min_volume_below_threshold",
            "Current 1-minute volume did not meet Strategy 2 confirmation threshold.",
        )

    assert nearest_trigger_name is not None
    setup_type = _choose_setup(
        latest_price=float(latest),
        one_min_return_signed=one_min_signed_return,
        trigger_name=nearest_trigger_name,
    )
    near_miss["setup_type"] = setup_type
    gate_pass["setup_type_detected"] = setup_type != "none"
    if setup_type == "none":
        primary_failed_gate = "setup_type_detected"
        return fail(
            "setup_type_detected",
            "setup_type_none",
            "No Strategy 2 setup type matched the current trigger interaction.",
        )
    side = "call" if setup_type.startswith("call_") else "put"
    reasons.extend(
        [
            f"setup_type:{setup_type}",
            f"trigger_level:{nearest_trigger_name}",
            f"proximity_band:{proximity_band:.4f}",
            f"one_min_return_abs_pct:{current_abs_1m_return:.6f}",
            f"one_min_range_atr_ratio:{current_1m_range_atr_ratio:.6f}",
            f"one_min_volume_multiple:{current_1m_volume_mult:.6f}",
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
