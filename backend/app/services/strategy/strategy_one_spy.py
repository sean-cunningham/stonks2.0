"""
Read-only Strategy 1 evaluator for SPY (decision logic only).

Rules are intentionally explicit; no execution, positions, or journal writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.schemas.context import ContextStatusResponse, ContextSummaryResponse
from app.schemas.market import ChainLatestResponse, MarketStatusResponse, NearAtmContract
from app.schemas.strategy import StrategyOneContextSnapshot, StrategyOneEvaluationResponse

# First-pass deterministic contract filters (tune via config later if needed).
_MAX_SPREAD_PERCENT = 35.0
_MIN_OPTION_MID = 0.05
_MAX_OPTION_MID = 75.0

# No-trade: price too close to VWAP vs ATR (no directional edge).
_VWAP_ATR_CHOP_K = 0.2


@dataclass
class StrategyOneEvalInput:
    """Normalized snapshot for one evaluation pass."""

    us_equity_rth_open: bool
    context_ready_for_live_trading: bool
    context_block_reason: str
    latest_price: float | None
    session_vwap: float | None
    opening_range_high: float | None
    opening_range_low: float | None
    latest_5m_atr: float | None
    recent_swing_high: float | None
    recent_swing_low: float | None
    market_ready: bool
    market_block_reason: str
    chain_available: bool
    chain_option_quotes_available: bool
    chain_selected_expiration: str | None
    underlying_reference_price: float | None
    near_atm_contracts: list[NearAtmContract]

    @classmethod
    def from_api(
        cls,
        *,
        status: ContextStatusResponse,
        summary: ContextSummaryResponse,
        market: MarketStatusResponse,
        chain: ChainLatestResponse,
    ) -> StrategyOneEvalInput:
        return cls(
            us_equity_rth_open=status.us_equity_rth_open,
            context_ready_for_live_trading=status.context_ready_for_live_trading,
            context_block_reason=status.block_reason,
            latest_price=summary.latest_price,
            session_vwap=summary.session_vwap,
            opening_range_high=summary.opening_range_high,
            opening_range_low=summary.opening_range_low,
            latest_5m_atr=summary.latest_5m_atr,
            recent_swing_high=summary.recent_swing_high,
            recent_swing_low=summary.recent_swing_low,
            market_ready=market.market_ready,
            market_block_reason=market.block_reason,
            chain_available=chain.available,
            chain_option_quotes_available=chain.option_quotes_available,
            chain_selected_expiration=chain.selected_expiration,
            underlying_reference_price=chain.underlying_reference_price,
            near_atm_contracts=list(chain.near_atm_contracts),
        )


def _snapshot(inp: StrategyOneEvalInput) -> StrategyOneContextSnapshot:
    return StrategyOneContextSnapshot(
        us_equity_rth_open=inp.us_equity_rth_open,
        context_ready_for_live_trading=inp.context_ready_for_live_trading,
        context_block_reason=inp.context_block_reason,
        latest_price=inp.latest_price,
        session_vwap=inp.session_vwap,
        opening_range_high=inp.opening_range_high,
        opening_range_low=inp.opening_range_low,
        latest_5m_atr=inp.latest_5m_atr,
        recent_swing_high=inp.recent_swing_high,
        recent_swing_low=inp.recent_swing_low,
        market_ready=inp.market_ready,
        market_block_reason=inp.market_block_reason,
        chain_available=inp.chain_available,
        chain_option_quotes_available=inp.chain_option_quotes_available,
        chain_selected_expiration=inp.chain_selected_expiration,
        underlying_reference_price=inp.underlying_reference_price,
    )


def _spread_percent(c: NearAtmContract) -> float | None:
    if c.spread_percent is not None:
        return float(c.spread_percent)
    if c.bid is None or c.ask is None:
        return None
    mid = c.mid if c.mid is not None else (c.bid + c.ask) / 2.0
    if mid <= 0:
        return None
    return (c.ask - c.bid) / mid * 100.0


def _expiry_matches(c: NearAtmContract, selected: str | None) -> bool:
    if not selected:
        return True
    if not c.expiration_date:
        return True
    return c.expiration_date == selected


def _contract_passes_quality(c: NearAtmContract, *, selected_expiration: str | None) -> bool:
    if not _expiry_matches(c, selected_expiration):
        return False
    if c.bid is None or c.ask is None or c.bid <= 0 or c.ask <= 0:
        return False
    mid = c.mid if c.mid is not None else (c.bid + c.ask) / 2.0
    if mid < _MIN_OPTION_MID or mid > _MAX_OPTION_MID:
        return False
    sp = _spread_percent(c)
    if sp is None or sp > _MAX_SPREAD_PERCENT:
        return False
    return True


def _or_mid(orh: float, orl: float) -> float:
    return 0.5 * (orh + orl)


def _inside_opening_range(px: float, orl: float, orh: float) -> bool:
    return orl < px < orh


def _mixed_vwap_opening_range(px: float, vwap: float, orh: float, orl: float) -> bool:
    """VWAP vs opening-range geometry disagree (inside OR only): bullish VWAP in lower half, or bearish VWAP in upper half."""
    if not _inside_opening_range(px, orl, orh):
        return False
    mid = _or_mid(orh, orl)
    if px > vwap and px <= mid:
        return True
    if px < vwap and px >= mid:
        return True
    return False


def _chop_zone(px: float, vwap: float, atr: float) -> bool:
    return abs(px - vwap) < (_VWAP_ATR_CHOP_K * atr)


def _bullish_structure(px: float, orh: float, orl: float, sh: float) -> bool:
    """
    Bullish structural confirmation (no weak swing-low-only rule).

    - Breakout: above OR high and above recent swing high.
    - Reclaim inside OR: strictly inside range, upper half or at midpoint, and at/above recent swing high.
    """
    if orl >= orh:
        return False
    mid = _or_mid(orh, orl)
    if px > orh and px > sh:
        return True
    if orl < px < orh and px >= mid and px >= sh:
        return True
    return False


def _bearish_structure(px: float, orh: float, orl: float, sl: float) -> bool:
    """
    Bearish structural confirmation (no weak swing-high-only rule).

    - Breakdown: below OR low and below recent swing low.
    - Distribution inside OR: strictly inside range, lower half or at midpoint, and at/below recent swing low.
    """
    if orl >= orh:
        return False
    mid = _or_mid(orh, orl)
    if px < orl and px < sl:
        return True
    if orl < px < orh and px <= mid and px <= sl:
        return True
    return False


def _bullish_structural_tag(px: float, orh: float, orl: float, sh: float) -> str | None:
    if px > orh and px > sh:
        return "bullish_structure_breakout_above_or_high_and_swing_high"
    if orl < px < orh and px >= _or_mid(orh, orl) and px >= sh:
        return "bullish_structure_reclaim_inside_or_upper_half_with_swing_high"
    return None


def _bearish_structural_tag(px: float, orh: float, orl: float, sl: float) -> str | None:
    if px < orl and px < sl:
        return "bearish_structure_breakdown_below_or_low_and_swing_low"
    if orl < px < orh and px <= _or_mid(orh, orl) and px <= sl:
        return "bearish_structure_distribution_inside_or_lower_half_with_swing_low"
    return None


def _pick_contract_nearest_strike(
    contracts: list[NearAtmContract],
    *,
    want_call: bool,
    reference: float,
    selected_expiration: str | None,
) -> NearAtmContract | None:
    """Nearest strike to reference among quality-passing contracts; delta is never used."""
    filtered = [
        c
        for c in contracts
        if (c.is_call if want_call else c.is_put) and _contract_passes_quality(c, selected_expiration=selected_expiration)
    ]
    if not filtered:
        return None
    return min(filtered, key=lambda c: abs(float(c.strike) - reference))


def evaluate_strategy_one_spy(
    inp: StrategyOneEvalInput,
    *,
    now: datetime | None = None,
) -> StrategyOneEvaluationResponse:
    """Return a read-only Strategy 1 decision for SPY; fail closed on missing or poor inputs."""
    ts = now or datetime.now(timezone.utc)
    snap = _snapshot(inp)
    blockers: list[str] = []
    reasons: list[str] = []

    if not inp.context_ready_for_live_trading:
        blockers.append(f"context_not_live_ready:{inp.context_block_reason}")
        return StrategyOneEvaluationResponse(
            decision="no_trade",
            blockers=blockers,
            reasons=reasons,
            context_snapshot_used=snap,
            contract_candidate=None,
            evaluation_timestamp=ts,
        )

    if not inp.market_ready:
        blockers.append(f"market_not_ready:{inp.market_block_reason}")
        return StrategyOneEvaluationResponse(
            decision="no_trade",
            blockers=blockers,
            reasons=reasons,
            context_snapshot_used=snap,
            contract_candidate=None,
            evaluation_timestamp=ts,
        )

    if not inp.chain_available or not inp.chain_option_quotes_available:
        blockers.append("chain_not_acceptable")
        return StrategyOneEvaluationResponse(
            decision="no_trade",
            blockers=blockers,
            reasons=reasons,
            context_snapshot_used=snap,
            contract_candidate=None,
            evaluation_timestamp=ts,
        )

    missing: list[str] = []
    if inp.latest_price is None:
        missing.append("latest_price")
    if inp.session_vwap is None:
        missing.append("session_vwap")
    if inp.opening_range_high is None:
        missing.append("opening_range_high")
    if inp.opening_range_low is None:
        missing.append("opening_range_low")
    if inp.latest_5m_atr is None:
        missing.append("latest_5m_atr")
    if inp.recent_swing_high is None:
        missing.append("recent_swing_high")
    if inp.recent_swing_low is None:
        missing.append("recent_swing_low")
    if missing:
        blockers.append("missing_metrics:" + ",".join(missing))
        return StrategyOneEvaluationResponse(
            decision="no_trade",
            blockers=blockers,
            reasons=reasons,
            context_snapshot_used=snap,
            contract_candidate=None,
            evaluation_timestamp=ts,
        )

    ref = inp.underlying_reference_price if inp.underlying_reference_price is not None else inp.latest_price
    if ref is None:
        blockers.append("missing_underlying_reference")
        return StrategyOneEvaluationResponse(
            decision="no_trade",
            blockers=blockers,
            reasons=reasons,
            context_snapshot_used=snap,
            contract_candidate=None,
            evaluation_timestamp=ts,
        )

    px = float(inp.latest_price)
    vwap = float(inp.session_vwap)
    orh = float(inp.opening_range_high)
    orl = float(inp.opening_range_low)
    atr = float(inp.latest_5m_atr)
    sh = float(inp.recent_swing_high)
    sl = float(inp.recent_swing_low)

    if atr <= 0:
        blockers.append("atr_non_positive")
        return StrategyOneEvaluationResponse(
            decision="no_trade",
            blockers=blockers,
            reasons=reasons,
            context_snapshot_used=snap,
            contract_candidate=None,
            evaluation_timestamp=ts,
        )

    if _chop_zone(px, vwap, atr):
        band = _VWAP_ATR_CHOP_K * atr
        blockers.append("no_trade_zone:vwap_atr_band")
        reasons.append(f"abs_price_minus_vwap={abs(px - vwap):.6f}_below_{_VWAP_ATR_CHOP_K}*atr_band={band:.6f}")
        return StrategyOneEvaluationResponse(
            decision="no_trade",
            blockers=blockers,
            reasons=reasons,
            context_snapshot_used=snap,
            contract_candidate=None,
            evaluation_timestamp=ts,
        )

    if _mixed_vwap_opening_range(px, vwap, orh, orl):
        blockers.append("mixed:vwap_vs_opening_range_geometry")
        reasons.append("inside_opening_range_but_vwap_disagrees_with_upper_or_lower_half")
        return StrategyOneEvaluationResponse(
            decision="no_trade",
            blockers=blockers,
            reasons=reasons,
            context_snapshot_used=snap,
            contract_candidate=None,
            evaluation_timestamp=ts,
        )

    bull = px > vwap and _bullish_structure(px, orh, orl, sh)
    bear = px < vwap and _bearish_structure(px, orh, orl, sl)

    if bull and bear:
        blockers.append("conflicting_bull_and_bear_structural_paths")
        return StrategyOneEvaluationResponse(
            decision="no_trade",
            blockers=blockers,
            reasons=reasons,
            context_snapshot_used=snap,
            contract_candidate=None,
            evaluation_timestamp=ts,
        )

    if bull:
        c = _pick_contract_nearest_strike(
            inp.near_atm_contracts,
            want_call=True,
            reference=float(ref),
            selected_expiration=inp.chain_selected_expiration,
        )
        if c is None:
            blockers.append("no_acceptable_option_contract")
            return StrategyOneEvaluationResponse(
                decision="no_trade",
                blockers=blockers,
                reasons=reasons,
                context_snapshot_used=snap,
                contract_candidate=None,
                evaluation_timestamp=ts,
            )
        tag = _bullish_structural_tag(px, orh, orl, sh)
        reasons.extend(
            [
                "context_live_ready",
                "market_and_chain_ready",
                "price_above_vwap",
                tag or "bullish_structure",
                "atr_positive",
                "call_contract_passed_quality_filters",
                "contract_selected_nearest_strike_to_underlying_reference_no_delta_preference",
            ]
        )
        return StrategyOneEvaluationResponse(
            decision="candidate_call",
            blockers=[],
            reasons=reasons,
            context_snapshot_used=snap,
            contract_candidate=c.model_copy(),
            evaluation_timestamp=ts,
        )

    if bear:
        c = _pick_contract_nearest_strike(
            inp.near_atm_contracts,
            want_call=False,
            reference=float(ref),
            selected_expiration=inp.chain_selected_expiration,
        )
        if c is None:
            blockers.append("no_acceptable_option_contract")
            return StrategyOneEvaluationResponse(
                decision="no_trade",
                blockers=blockers,
                reasons=reasons,
                context_snapshot_used=snap,
                contract_candidate=None,
                evaluation_timestamp=ts,
            )
        tag = _bearish_structural_tag(px, orh, orl, sl)
        reasons.extend(
            [
                "context_live_ready",
                "market_and_chain_ready",
                "price_below_vwap",
                tag or "bearish_structure",
                "atr_positive",
                "put_contract_passed_quality_filters",
                "contract_selected_nearest_strike_to_underlying_reference_no_delta_preference",
            ]
        )
        return StrategyOneEvaluationResponse(
            decision="candidate_put",
            blockers=[],
            reasons=reasons,
            context_snapshot_used=snap,
            contract_candidate=c.model_copy(),
            evaluation_timestamp=ts,
        )

    reasons.append("evaluated_structural_paths:no_bull_or_bear_candidate_after_gates")
    return StrategyOneEvaluationResponse(
        decision="no_trade",
        blockers=[],
        reasons=reasons,
        context_snapshot_used=snap,
        contract_candidate=None,
        evaluation_timestamp=ts,
    )
