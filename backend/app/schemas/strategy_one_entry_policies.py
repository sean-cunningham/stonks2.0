"""Strategy 1 v1 entry-time policy payloads (paper; monitoring / exits later)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Strategy1ExitPolicyV1(BaseModel):
    """Exit policy assigned at entry — informational until monitoring exists."""

    policy_version: Literal["strategy_1_exit_v1"] = "strategy_1_exit_v1"
    trade_horizon_class: Literal["intraday_continuation", "promoted_swing"]
    calendar_dte_at_entry: int
    expiry_band: Literal["2_5_dte", "7_21_dte"]
    thesis_stop_reference: dict[str, Any] = Field(
        default_factory=dict,
        description="Underlying-structure thesis stop anchor (levels from evaluation snapshot).",
    )
    premium_fail_safe_stop_pct: float = 0.35
    profit_trigger_r: float = 1.0
    trail_activation_r: float = 1.5
    trailing_style: Literal["underlying_structure_based"] = "underlying_structure_based"
    intraday_no_progress_timeout_minutes_min: int = 30
    intraday_no_progress_timeout_minutes_max: int = 45
    intraday_hard_flat_time_et: str = "15:45"
    intraday_hard_flat_zone: str = "America/New_York"
    promoted_swing_max_hold_trading_days: int | None = None
    promotion_requires_explicit_eligibility: bool = True


class Strategy1SizingPolicyV1(BaseModel):
    """Small-account sizing snapshot at entry (paper profile)."""

    policy_version: Literal["strategy_1_sizing_v1"] = "strategy_1_sizing_v1"
    sizing_profile: Literal["small_account_live"] = "small_account_live"
    account_equity_usd: float
    max_risk_pct: float = 0.02
    max_contracts: int = 1
    quantity: int = 1
    risk_budget_usd: float
    fail_safe_stop_pct: float = 0.35
    max_affordable_premium_usd: float
    entry_ask_per_share: float
    entry_total_premium_usd: float
