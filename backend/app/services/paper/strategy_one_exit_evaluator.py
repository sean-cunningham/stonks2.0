"""Read-only exit evaluation for Strategy 1 open paper positions (no auto-close)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from app.models.trade import PaperTrade
from app.schemas.context import ContextStatusResponse, ContextSummaryResponse
from app.schemas.market import MarketStatusResponse
from app.schemas.paper_trade import PaperOpenPositionValuationResponse
from app.schemas.strategy_one_entry_policies import Strategy1ExitPolicyV1, Strategy1SizingPolicyV1
from app.schemas.strategy_one_exit_evaluation import StrategyOneExitEvaluationResponse


def _parse_exit_policy(raw: object) -> Strategy1ExitPolicyV1 | None:
    if not isinstance(raw, dict):
        return None
    try:
        return Strategy1ExitPolicyV1.model_validate(raw)
    except Exception:
        return None


def _parse_sizing_policy(raw: object) -> Strategy1SizingPolicyV1 | None:
    if not isinstance(raw, dict):
        return None
    try:
        return Strategy1SizingPolicyV1.model_validate(raw)
    except Exception:
        return None


def _premium_r_dollar(*, entry_total_premium_usd: float, fail_safe_fraction: float) -> float:
    """Premium-risk R in dollars: debit at entry × premium fail-safe fraction (not full thesis risk)."""
    return max(float(entry_total_premium_usd) * float(fail_safe_fraction), 1e-9)


def _parse_hh_mm_et(s: str) -> time:
    parts = s.strip().split(":")
    h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    return time(hour=h, minute=m)


def _informational_trailing_reference_price_v1(
    *,
    entry_decision: str,
    summary: ContextSummaryResponse,
) -> float | None:
    """v1 structural hint for underlying_structure_based trail — not an enforced stop engine."""
    orh, orl = summary.opening_range_high, summary.opening_range_low
    rsh, rsl = summary.recent_swing_high, summary.recent_swing_low
    if entry_decision == "candidate_call":
        levels = [x for x in (orl, rsl) if x is not None]
        return max(levels) if levels else None
    if entry_decision == "candidate_put":
        levels = [x for x in (orh, rsh) if x is not None]
        return min(levels) if levels else None
    return None


def _thesis_broken(
    *,
    entry_decision: str,
    thesis: dict[str, object],
    latest_price: float | None,
) -> bool:
    """Narrow structural break vs entry thesis anchor level."""
    if latest_price is None:
        return False
    level = thesis.get("level")
    if level is None:
        return False
    try:
        lv = float(level)
    except (TypeError, ValueError):
        return False
    if entry_decision == "candidate_call":
        return float(latest_price) < lv
    if entry_decision == "candidate_put":
        return float(latest_price) > lv
    return False


def _non_actionable_hold(
    *,
    blockers: list[str],
    policy_snap: dict[str, object],
    pos_snap: dict[str, object],
    mkt_snap: dict[str, object],
    levels_snap: dict[str, object],
    evaluation_timestamp: datetime,
) -> StrategyOneExitEvaluationResponse:
    """hold + blockers + explicit banner reason (not a trade-management 'hold')."""
    reasons = ["evaluation_blocked_non_actionable_state"]
    return StrategyOneExitEvaluationResponse(
        action="hold",
        reasons=reasons,
        blockers=blockers,
        current_policy_snapshot=policy_snap,
        current_position_snapshot=pos_snap,
        current_market_snapshot=mkt_snap,
        exit_levels_snapshot=levels_snap,
        evaluation_timestamp=evaluation_timestamp,
    )


@dataclass(frozen=True)
class ExitEvaluationInput:
    position: PaperTrade
    valuation: PaperOpenPositionValuationResponse
    context_status: ContextStatusResponse
    context_summary: ContextSummaryResponse
    market_status: MarketStatusResponse
    clock_utc: datetime | None = None


def evaluate_strategy_one_open_exit_readonly(inp: ExitEvaluationInput) -> StrategyOneExitEvaluationResponse:
    """Return a single recommended action; does not mutate DB or call the broker.

    Hard-flat and all session-clock comparisons use ``America/New_York`` via
    ``clock_utc.astimezone(ZoneInfo(...))`` — never the process local timezone.
    R-multiples are **premium-risk R** (fail-safe premium dollars), not full thesis risk.
    """
    clock = inp.clock_utc or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)

    row = inp.position
    v = inp.valuation
    st = inp.context_status
    summary = inp.context_summary
    mkt = inp.market_status

    exit_raw = row.exit_policy if isinstance(row.exit_policy, dict) else None
    size_raw = row.sizing_policy if isinstance(row.sizing_policy, dict) else None
    exit_pol = _parse_exit_policy(exit_raw)
    size_pol = _parse_sizing_policy(size_raw)

    policy_snap: dict[str, object] = {}
    if exit_raw is not None:
        policy_snap["exit_policy"] = exit_raw
    if size_raw is not None:
        policy_snap["sizing_policy"] = size_raw

    pos_snap: dict[str, object] = {
        "paper_trade_id": row.id,
        "strategy_id": row.strategy_id,
        "symbol": row.symbol,
        "option_symbol": row.option_symbol,
        "side": row.side,
        "quantity": row.quantity,
        "status": row.status,
        "entry_time": row.entry_time.isoformat() if row.entry_time else None,
        "entry_price": row.entry_price,
        "entry_decision": row.entry_decision,
    }

    mkt_snap: dict[str, object] = {
        "market_ready": mkt.market_ready,
        "market_block_reason": mkt.block_reason,
        "quote_is_fresh": mkt.quote_is_fresh,
        "chain_is_fresh": mkt.chain_is_fresh,
        "us_equity_rth_open": st.us_equity_rth_open,
        "context_ready_for_live_trading": summary.context_ready_for_live_trading,
        "latest_price": summary.latest_price,
        "session_vwap": summary.session_vwap,
        "opening_range_high": summary.opening_range_high,
        "opening_range_low": summary.opening_range_low,
        "recent_swing_high": summary.recent_swing_high,
        "recent_swing_low": summary.recent_swing_low,
        "latest_5m_atr": summary.latest_5m_atr,
    }

    levels_snap: dict[str, object] = {
        "unrealized_pnl_bid_basis": v.unrealized_pnl_bid_basis,
        "valuation_quote_is_fresh": v.quote_is_fresh,
        "valuation_exit_actionable": v.exit_actionable,
        "valuation_error": v.valuation_error,
        "informational_structural_trailing_reference_note_v1": (
            "v1 informational structural level only; not an enforced trailing-stop engine."
        ),
    }

    if row.status != "open":
        return _non_actionable_hold(
            blockers=["not_open_position"],
            policy_snap=policy_snap,
            pos_snap=pos_snap,
            mkt_snap=mkt_snap,
            levels_snap=levels_snap,
            evaluation_timestamp=clock,
        )

    policy_blockers: list[str] = []
    if exit_pol is None:
        policy_blockers.append("missing_exit_policy")
    if size_pol is None:
        policy_blockers.append("missing_sizing_policy")
    if policy_blockers:
        return _non_actionable_hold(
            blockers=policy_blockers,
            policy_snap=policy_snap,
            pos_snap=pos_snap,
            mkt_snap=mkt_snap,
            levels_snap=levels_snap,
            evaluation_timestamp=clock,
        )

    assert exit_pol is not None and size_pol is not None

    premium_r = _premium_r_dollar(
        entry_total_premium_usd=size_pol.entry_total_premium_usd,
        fail_safe_fraction=exit_pol.premium_fail_safe_stop_pct,
    )
    levels_snap["premium_r_dollar"] = premium_r
    levels_snap["profit_trigger_premium_r_dollars"] = exit_pol.profit_trigger_r * premium_r
    levels_snap["trail_activation_premium_r_dollars"] = exit_pol.trail_activation_r * premium_r
    levels_snap["premium_fail_safe_loss_threshold_dollars"] = -premium_r
    trail_px = _informational_trailing_reference_price_v1(entry_decision=row.entry_decision, summary=summary)
    levels_snap["informational_structural_trailing_reference_price_v1"] = trail_px

    quote_blockers: list[str] = []
    if v.valuation_error is not None:
        quote_blockers.append("valuation_error_present")
    if not v.quote_is_fresh:
        quote_blockers.append("stale_valuation")
    if not v.exit_actionable:
        quote_blockers.append("exit_not_actionable_missing_fresh_option_quote")
    if quote_blockers:
        return _non_actionable_hold(
            blockers=quote_blockers,
            policy_snap=policy_snap,
            pos_snap=pos_snap,
            mkt_snap=mkt_snap,
            levels_snap=levels_snap,
            evaluation_timestamp=clock,
        )

    u = v.unrealized_pnl_bid_basis
    if u is None:
        return _non_actionable_hold(
            blockers=["missing_unrealized_pnl_bid_basis"],
            policy_snap=policy_snap,
            pos_snap=pos_snap,
            mkt_snap=mkt_snap,
            levels_snap=levels_snap,
            evaluation_timestamp=clock,
        )

    blockers: list[str] = []
    reasons: list[str] = []

    # 1) Hard fail-safe: unrealized loss at or beyond -1 premium-risk R (fail-safe dollars).
    if u <= -premium_r + 1e-6:
        reasons.append("premium_fail_safe_stop_breached")
        return StrategyOneExitEvaluationResponse(
            action="close_now",
            reasons=reasons,
            blockers=blockers,
            current_policy_snapshot=policy_snap,
            current_position_snapshot=pos_snap,
            current_market_snapshot=mkt_snap,
            exit_levels_snapshot=levels_snap,
            evaluation_timestamp=clock,
        )

    # 2) Thesis break vs stored anchor.
    thesis = exit_pol.thesis_stop_reference or {}
    if _thesis_broken(entry_decision=row.entry_decision, thesis=thesis, latest_price=summary.latest_price):
        reasons.append("thesis_structure_break_vs_entry_anchor")
        return StrategyOneExitEvaluationResponse(
            action="close_now",
            reasons=reasons,
            blockers=blockers,
            current_policy_snapshot=policy_snap,
            current_position_snapshot=pos_snap,
            current_market_snapshot=mkt_snap,
            exit_levels_snapshot=levels_snap,
            evaluation_timestamp=clock,
        )

    # Intraday clock: always policy zone (default America/New_York), never local TZ.
    zone = ZoneInfo(exit_pol.intraday_hard_flat_zone)
    now_local = clock.astimezone(zone)
    flat_t = _parse_hh_mm_et(exit_pol.intraday_hard_flat_time_et)

    # 3) Intraday hard flat (RTH only; avoids weekend false positives). Compare local ET wall time only.
    if (
        exit_pol.trade_horizon_class == "intraday_continuation"
        and st.us_equity_rth_open
        and now_local.time() >= flat_t
    ):
        reasons.append("intraday_hard_flat_time_et_reached")
        return StrategyOneExitEvaluationResponse(
            action="close_now",
            reasons=reasons,
            blockers=blockers,
            current_policy_snapshot=policy_snap,
            current_position_snapshot=pos_snap,
            current_market_snapshot=mkt_snap,
            exit_levels_snapshot=levels_snap,
            evaluation_timestamp=clock,
        )

    # 4) No meaningful progress (intraday): past max timeout and under +0.1 premium-risk R on bid basis.
    if row.entry_time:
        et = row.entry_time if row.entry_time.tzinfo else row.entry_time.replace(tzinfo=timezone.utc)
        elapsed_min = (clock - et).total_seconds() / 60.0
    else:
        elapsed_min = 0.0
    progress_floor = 0.1 * premium_r
    if (
        exit_pol.trade_horizon_class == "intraday_continuation"
        and elapsed_min > float(exit_pol.intraday_no_progress_timeout_minutes_max)
        and u < progress_floor
    ):
        reasons.append("intraday_no_progress_past_timeout_window")
        return StrategyOneExitEvaluationResponse(
            action="close_now",
            reasons=reasons,
            blockers=blockers,
            current_policy_snapshot=policy_snap,
            current_position_snapshot=pos_snap,
            current_market_snapshot=mkt_snap,
            exit_levels_snapshot=levels_snap,
            evaluation_timestamp=clock,
        )

    # 5) Trail activation (premium-risk R multiple).
    if u >= exit_pol.trail_activation_r * premium_r - 1e-6:
        reasons.append("trail_activation_premium_r_reached")
        return StrategyOneExitEvaluationResponse(
            action="trail_active",
            reasons=reasons,
            blockers=blockers,
            current_policy_snapshot=policy_snap,
            current_position_snapshot=pos_snap,
            current_market_snapshot=mkt_snap,
            exit_levels_snapshot=levels_snap,
            evaluation_timestamp=clock,
        )

    # 6) Profit trigger (premium-risk R multiple).
    if u >= exit_pol.profit_trigger_r * premium_r - 1e-6:
        reasons.append("profit_trigger_premium_r_reached")
        return StrategyOneExitEvaluationResponse(
            action="tighten_stop",
            reasons=reasons,
            blockers=blockers,
            current_policy_snapshot=policy_snap,
            current_position_snapshot=pos_snap,
            current_market_snapshot=mkt_snap,
            exit_levels_snapshot=levels_snap,
            evaluation_timestamp=clock,
        )

    # 7) Optional promote-to-swing hint (never auto; intraday only, profitable, fresh quote, not near flat).
    promote_floor = 0.5 * premium_r
    minutes_to_flat: float | None = None
    if st.us_equity_rth_open:
        flat_dt = datetime.combine(now_local.date(), flat_t, tzinfo=now_local.tzinfo)
        minutes_to_flat = (flat_dt - now_local).total_seconds() / 60.0

    if (
        exit_pol.trade_horizon_class == "intraday_continuation"
        and v.quote_is_fresh
        and u > 0
        and u >= promote_floor
        and (minutes_to_flat is None or minutes_to_flat > 10.0)
    ):
        reasons.append("intraday_profitable_structure_intact_promotion_hint_only")
        return StrategyOneExitEvaluationResponse(
            action="promote_to_swing_candidate",
            reasons=reasons,
            blockers=blockers,
            current_policy_snapshot=policy_snap,
            current_position_snapshot=pos_snap,
            current_market_snapshot=mkt_snap,
            exit_levels_snapshot=levels_snap,
            evaluation_timestamp=clock,
        )

    reasons.append("no_exit_rules_triggered")
    return StrategyOneExitEvaluationResponse(
        action="hold",
        reasons=reasons,
        blockers=blockers,
        current_policy_snapshot=policy_snap,
        current_position_snapshot=pos_snap,
        current_market_snapshot=mkt_snap,
        exit_levels_snapshot=levels_snap,
        evaluation_timestamp=clock,
    )
