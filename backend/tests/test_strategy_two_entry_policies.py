from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.schemas.market import NearAtmContract
from app.schemas.strategy import StrategyOneContextSnapshot, StrategyOneEvaluationResponse
from app.services.paper.strategy_two_entry_policies import (
    EntryPolicyRejected,
    assign_exit_and_sizing_policies_v1,
)


def _candidate_eval(contract: NearAtmContract) -> StrategyOneEvaluationResponse:
    ctx = StrategyOneContextSnapshot(
        us_equity_rth_open=True,
        context_ready_for_live_trading=True,
        context_block_reason="none",
        latest_price=500.0,
        session_vwap=500.0,
        opening_range_high=502.0,
        opening_range_low=498.0,
        latest_5m_atr=1.0,
        recent_swing_high=503.0,
        recent_swing_low=497.0,
        market_ready=True,
        market_block_reason="none",
        chain_available=True,
        chain_option_quotes_available=True,
        chain_selected_expiration=contract.expiration_date,
        underlying_reference_price=500.0,
    )
    return StrategyOneEvaluationResponse(
        decision="candidate_call",
        blockers=[],
        reasons=["ok"],
        context_snapshot_used=ctx,
        contract_candidate=contract,
        evaluation_timestamp=datetime.now(timezone.utc),
    )


class StrategyTwoEntryPoliciesTests(unittest.TestCase):
    def test_exit_policy_uses_v1_targets_and_hard_flat_time(self) -> None:
        today_et = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()
        contract = NearAtmContract(
            option_symbol="SPY  260425C00500000",
            strike=500.0,
            option_type="call",
            expiration_date=today_et,
            bid=0.50,
            ask=0.60,
            mid=0.55,
            spread_percent=5.0,
            is_call=True,
            is_put=False,
        )
        exit_policy, _ = assign_exit_and_sizing_policies_v1(
            evaluation=_candidate_eval(contract),
            contract=contract,
            entry_ask_per_share=0.60,
            quantity=1,
            account_equity_usd=5000.0,
            entry_clock_utc=datetime.now(timezone.utc),
        )
        self.assertEqual(exit_policy.premium_fail_safe_stop_pct, 0.15)
        self.assertEqual(exit_policy.profit_target_pct, 0.20)
        self.assertEqual(exit_policy.speed_failure_seconds, 90)
        self.assertEqual(exit_policy.max_hold_seconds, 300)
        self.assertEqual(exit_policy.hard_flat_time_et, "15:45")

    def test_rejects_non_0dte_contract(self) -> None:
        non_0dte = (datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date() + timedelta(days=1)).isoformat()
        contract = NearAtmContract(
            option_symbol="SPY  260426C00500000",
            strike=500.0,
            option_type="call",
            expiration_date=non_0dte,
            bid=0.50,
            ask=0.60,
            mid=0.55,
            spread_percent=5.0,
            is_call=True,
            is_put=False,
        )
        with self.assertRaises(EntryPolicyRejected) as ctx:
            assign_exit_and_sizing_policies_v1(
                evaluation=_candidate_eval(contract),
                contract=contract,
                entry_ask_per_share=0.60,
                quantity=1,
                account_equity_usd=5000.0,
                entry_clock_utc=datetime.now(timezone.utc),
            )
        self.assertEqual(ctx.exception.code, "paper_entry_0dte_required_for_strategy_two")

    def test_sizing_scales_to_max_position_cost(self) -> None:
        today_et = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()
        contract = NearAtmContract(
            option_symbol="SPY  260425C00500000",
            strike=500.0,
            option_type="call",
            expiration_date=today_et,
            bid=0.40,
            ask=0.50,
            mid=0.45,
            spread_percent=5.0,
            is_call=True,
            is_put=False,
        )
        _, sizing = assign_exit_and_sizing_policies_v1(
            evaluation=_candidate_eval(contract),
            contract=contract,
            entry_ask_per_share=0.50,
            quantity=1,
            account_equity_usd=5000.0,
            entry_clock_utc=datetime.now(timezone.utc),
        )
        self.assertEqual(sizing.quantity, 3)  # floor(150 / 50)
        self.assertAlmostEqual(sizing.entry_total_premium_usd, 150.0, places=4)

    def test_rejects_when_single_contract_exceeds_max_position_cost(self) -> None:
        today_et = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()
        contract = NearAtmContract(
            option_symbol="SPY  260425C00500000",
            strike=500.0,
            option_type="call",
            expiration_date=today_et,
            bid=1.55,
            ask=1.60,
            mid=1.575,
            spread_percent=5.0,
            is_call=True,
            is_put=False,
        )
        with self.assertRaises(EntryPolicyRejected) as ctx:
            assign_exit_and_sizing_policies_v1(
                evaluation=_candidate_eval(contract),
                contract=contract,
                entry_ask_per_share=1.60,
                quantity=1,
                account_equity_usd=5000.0,
                entry_clock_utc=datetime.now(timezone.utc),
            )
        self.assertEqual(ctx.exception.code, "paper_entry_exceeds_max_position_cost")

