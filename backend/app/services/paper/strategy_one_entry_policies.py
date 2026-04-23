"""Assign Strategy 1 exit + sizing policies at paper entry (no auto-exit)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.schemas.market import NearAtmContract
from app.schemas.strategy import StrategyOneEvaluationResponse
from app.schemas.strategy_one_entry_policies import Strategy1ExitPolicyV1, Strategy1SizingPolicyV1
from app.services.paper.contract_constants import OPTION_CONTRACT_MULTIPLIER

_ET = ZoneInfo("America/New_York")

PREMIUM_FAIL_SAFE_FRACTION = 0.35
MAX_RISK_FRACTION = 0.05
MAX_CONTRACTS_SMALL_ACCOUNT = 1
INTRADAY_DTE_MIN = 2
INTRADAY_DTE_MAX = 5
SWING_DTE_MIN = 7
SWING_DTE_MAX = 21


class EntryPolicyRejected(Exception):
    """Fail-closed policy gate at entry; caller maps to PaperTradeError."""

    def __init__(self, code: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


def calendar_dte_to_expiration_us_eastern(*, expiration_date_str: str, as_of_utc: datetime) -> int:
    """Calendar days from US/Eastern 'today' to expiration date (date-only)."""
    exp = date.fromisoformat(expiration_date_str)
    now_et = as_of_utc.astimezone(_ET).date()
    return (exp - now_et).days


def _thesis_stop_reference(evaluation: StrategyOneEvaluationResponse) -> dict[str, Any]:
    snap = evaluation.context_snapshot_used
    if evaluation.decision == "candidate_call":
        level = snap.recent_swing_low
        ref_type = "recent_swing_low"
        if level is None:
            level = snap.opening_range_low
            ref_type = "opening_range_low"
        if level is None:
            level = snap.underlying_reference_price
            ref_type = "underlying_reference_price"
    elif evaluation.decision == "candidate_put":
        level = snap.recent_swing_high
        ref_type = "recent_swing_high"
        if level is None:
            level = snap.opening_range_high
            ref_type = "opening_range_high"
        if level is None:
            level = snap.underlying_reference_price
            ref_type = "underlying_reference_price"
    else:
        return {"basis": "underlying_structure", "reference_type": "none", "level": None}
    return {
        "basis": "underlying_structure",
        "reference_type": ref_type,
        "level": float(level) if level is not None else None,
    }


def build_sizing_policy_v1(
    *,
    account_equity_usd: float,
    entry_ask_per_share: float,
    quantity: int,
) -> Strategy1SizingPolicyV1:
    if quantity > MAX_CONTRACTS_SMALL_ACCOUNT:
        raise EntryPolicyRejected("paper_entry_quantity_exceeds_small_account_max")
    if quantity < 1:
        raise EntryPolicyRejected("paper_entry_quantity_invalid")
    risk_budget = account_equity_usd * MAX_RISK_FRACTION
    max_affordable_total = risk_budget / PREMIUM_FAIL_SAFE_FRACTION
    entry_total = float(entry_ask_per_share) * OPTION_CONTRACT_MULTIPLIER * quantity
    if entry_total > max_affordable_total + 1e-6:
        raise EntryPolicyRejected(
            "paper_entry_premium_exceeds_risk_budget",
            details={
                "attempted_ask": float(entry_ask_per_share),
                "attempted_total_premium_usd": float(entry_total),
                "account_equity_used": float(account_equity_usd),
                "max_risk_pct_used": float(MAX_RISK_FRACTION),
                "fail_safe_stop_pct_used": float(PREMIUM_FAIL_SAFE_FRACTION),
                "risk_budget_usd": float(risk_budget),
                "max_affordable_premium_usd": float(max_affordable_total),
                "premium_over_budget_usd": float(entry_total - max_affordable_total),
                "quantity": int(quantity),
                "contract_multiplier": int(OPTION_CONTRACT_MULTIPLIER),
                "affordability_block_reason": "premium_exceeds_risk_budget",
            },
        )
    return Strategy1SizingPolicyV1(
        account_equity_usd=float(account_equity_usd),
        max_risk_pct=MAX_RISK_FRACTION,
        max_contracts=MAX_CONTRACTS_SMALL_ACCOUNT,
        quantity=quantity,
        risk_budget_usd=risk_budget,
        fail_safe_stop_pct=PREMIUM_FAIL_SAFE_FRACTION,
        max_affordable_premium_usd=max_affordable_total,
        entry_ask_per_share=float(entry_ask_per_share),
        entry_total_premium_usd=entry_total,
    )


def assign_exit_and_sizing_policies_v1(
    *,
    evaluation: StrategyOneEvaluationResponse,
    contract: NearAtmContract,
    entry_ask_per_share: float,
    quantity: int,
    account_equity_usd: float,
    entry_clock_utc: datetime,
) -> tuple[Strategy1ExitPolicyV1, Strategy1SizingPolicyV1]:
    """Pick horizon from explicit swing eligibility + DTE bands; size against fail-safe budget."""
    if not contract.expiration_date:
        raise EntryPolicyRejected("paper_entry_missing_expiration_for_policy")

    dte = calendar_dte_to_expiration_us_eastern(
        expiration_date_str=contract.expiration_date,
        as_of_utc=entry_clock_utc,
    )

    swing_eligible = bool(evaluation.swing_promotion_eligible)
    if swing_eligible:
        if dte < SWING_DTE_MIN or dte > SWING_DTE_MAX:
            raise EntryPolicyRejected("paper_entry_promoted_swing_dte_not_in_band")
        horizon: Literal["intraday_continuation", "promoted_swing"] = "promoted_swing"
        expiry_band: Literal["2_5_dte", "7_21_dte"] = "7_21_dte"
        max_hold = 3
    else:
        if dte < INTRADAY_DTE_MIN or dte > INTRADAY_DTE_MAX:
            raise EntryPolicyRejected("paper_entry_intraday_dte_not_in_band")
        horizon = "intraday_continuation"
        expiry_band = "2_5_dte"
        max_hold = None

    thesis = _thesis_stop_reference(evaluation)
    exit_policy = Strategy1ExitPolicyV1(
        trade_horizon_class=horizon,
        calendar_dte_at_entry=dte,
        expiry_band=expiry_band,
        thesis_stop_reference=thesis,
        premium_fail_safe_stop_pct=PREMIUM_FAIL_SAFE_FRACTION,
        profit_trigger_r=1.0,
        trail_activation_r=1.5,
        trailing_style="underlying_structure_based",
        intraday_no_progress_timeout_minutes_min=30,
        intraday_no_progress_timeout_minutes_max=45,
        intraday_hard_flat_time_et="15:45",
        intraday_hard_flat_zone="America/New_York",
        promoted_swing_max_hold_trading_days=max_hold,
        promotion_requires_explicit_eligibility=True,
    )

    try:
        sizing = build_sizing_policy_v1(
            account_equity_usd=account_equity_usd,
            entry_ask_per_share=entry_ask_per_share,
            quantity=quantity,
        )
    except EntryPolicyRejected as exc:
        details = dict(exc.details)
        details.update(
            {
                "attempted_option_symbol": contract.option_symbol,
                "attempted_side": "long",
                "attempted_expiration_date": contract.expiration_date,
                "attempted_strike": float(contract.strike) if contract.strike is not None else None,
                "entry_clock_utc": entry_clock_utc.isoformat(),
            }
        )
        raise EntryPolicyRejected(exc.code, details=details) from exc
    return exit_policy, sizing
