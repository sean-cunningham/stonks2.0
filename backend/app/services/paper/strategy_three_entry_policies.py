"""Strategy 3 (0DTE micro impulse) entry policy assignment for paper mode."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.schemas.market import NearAtmContract
from app.schemas.strategy import StrategyOneEvaluationResponse
from app.services.paper.contract_constants import OPTION_CONTRACT_MULTIPLIER

_ET = ZoneInfo("America/New_York")

PROFIT_TARGET_PCT = 0.25
HARD_STOP_PCT = 0.15
SPEED_FAILURE_SECONDS = 75
SPEED_FAILURE_MIN_PROFIT_PCT = 0.05
MAX_HOLD_SECONDS = 240
MAX_POSITION_COST_USD = 200.0


class EntryPolicyRejected(Exception):
    def __init__(self, code: str, *, details: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


def calendar_dte_to_expiration_us_eastern(*, expiration_date_str: str, as_of_utc: datetime) -> int:
    exp = date.fromisoformat(expiration_date_str)
    return (exp - as_of_utc.astimezone(_ET).date()).days


@dataclass(frozen=True)
class StrategyThreeExitPolicyV1:
    policy_version: str
    trade_horizon_class: str
    calendar_dte_at_entry: int
    expiry_band: str
    premium_fail_safe_stop_pct: float
    profit_target_pct: float
    speed_failure_seconds: int
    speed_failure_min_profit_pct: float
    max_hold_seconds: int
    hard_flat_time_et: str
    hard_flat_zone: str

    def as_dict(self) -> dict:
        return {
            "policy_version": self.policy_version,
            "trade_horizon_class": self.trade_horizon_class,
            "calendar_dte_at_entry": self.calendar_dte_at_entry,
            "expiry_band": self.expiry_band,
            "premium_fail_safe_stop_pct": self.premium_fail_safe_stop_pct,
            "profit_target_pct": self.profit_target_pct,
            "speed_failure_seconds": self.speed_failure_seconds,
            "speed_failure_min_profit_pct": self.speed_failure_min_profit_pct,
            "max_hold_seconds": self.max_hold_seconds,
            "hard_flat_time_et": self.hard_flat_time_et,
            "hard_flat_zone": self.hard_flat_zone,
        }


@dataclass(frozen=True)
class StrategyThreeSizingPolicyV1:
    policy_version: str
    sizing_profile: str
    account_equity_usd: float
    quantity: int
    max_position_cost_usd: float
    entry_ask_per_share: float
    entry_total_premium_usd: float

    def as_dict(self) -> dict:
        return {
            "policy_version": self.policy_version,
            "sizing_profile": self.sizing_profile,
            "account_equity_usd": self.account_equity_usd,
            "quantity": self.quantity,
            "max_position_cost_usd": self.max_position_cost_usd,
            "entry_ask_per_share": self.entry_ask_per_share,
            "entry_total_premium_usd": self.entry_total_premium_usd,
        }


def build_sizing_policy_v1(*, account_equity_usd: float, entry_ask_per_share: float, quantity: int) -> StrategyThreeSizingPolicyV1:
    if quantity <= 0:
        raise EntryPolicyRejected("paper_entry_quantity_invalid")
    cost_per_contract = float(entry_ask_per_share) * OPTION_CONTRACT_MULTIPLIER
    if cost_per_contract > MAX_POSITION_COST_USD:
        raise EntryPolicyRejected(
            "paper_entry_exceeds_max_position_cost",
            details={
                "attempted_ask": float(entry_ask_per_share),
                "max_position_cost_usd": MAX_POSITION_COST_USD,
                "contract_cost_usd": cost_per_contract,
                "affordability_block_reason": "single_contract_over_max_position_cost",
            },
        )
    sized_quantity = int(MAX_POSITION_COST_USD // cost_per_contract)
    if sized_quantity < 1:
        raise EntryPolicyRejected("paper_entry_quantity_invalid")
    total_premium = float(entry_ask_per_share) * OPTION_CONTRACT_MULTIPLIER * int(sized_quantity)
    return StrategyThreeSizingPolicyV1(
        policy_version="strategy_3_sizing_v1",
        sizing_profile="micro_impulse_small_account",
        account_equity_usd=float(account_equity_usd),
        quantity=int(sized_quantity),
        max_position_cost_usd=MAX_POSITION_COST_USD,
        entry_ask_per_share=float(entry_ask_per_share),
        entry_total_premium_usd=total_premium,
    )


def assign_exit_and_sizing_policies_v1(
    *,
    evaluation: StrategyOneEvaluationResponse,
    contract: NearAtmContract,
    entry_ask_per_share: float,
    quantity: int,
    account_equity_usd: float,
    entry_clock_utc: datetime,
) -> tuple[StrategyThreeExitPolicyV1, StrategyThreeSizingPolicyV1]:
    _ = evaluation
    if not contract.expiration_date:
        raise EntryPolicyRejected("paper_entry_missing_expiration_for_policy")
    dte = calendar_dte_to_expiration_us_eastern(expiration_date_str=contract.expiration_date, as_of_utc=entry_clock_utc)
    if dte != 0:
        raise EntryPolicyRejected("paper_entry_0dte_required_for_strategy_three")
    exit_policy = StrategyThreeExitPolicyV1(
        policy_version="strategy_3_exit_v1",
        trade_horizon_class="intraday_micro_impulse",
        calendar_dte_at_entry=dte,
        expiry_band="0_dte",
        premium_fail_safe_stop_pct=HARD_STOP_PCT,
        profit_target_pct=PROFIT_TARGET_PCT,
        speed_failure_seconds=SPEED_FAILURE_SECONDS,
        speed_failure_min_profit_pct=SPEED_FAILURE_MIN_PROFIT_PCT,
        max_hold_seconds=MAX_HOLD_SECONDS,
        hard_flat_time_et="15:45",
        hard_flat_zone="America/New_York",
    )
    sizing = build_sizing_policy_v1(
        account_equity_usd=account_equity_usd,
        entry_ask_per_share=entry_ask_per_share,
        quantity=quantity,
    )
    return exit_policy, sizing
