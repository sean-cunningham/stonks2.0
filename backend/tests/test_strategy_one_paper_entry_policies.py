"""Unit tests for Strategy 1 paper entry policy assignment (no DB)."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.schemas.market import NearAtmContract
from app.schemas.strategy import StrategyOneContextSnapshot, StrategyOneEvaluationResponse
from app.schemas.strategy_one_entry_policies import Strategy1ExitPolicyV1, Strategy1SizingPolicyV1
from app.services.paper.strategy_one_entry_policies import (
    EntryPolicyRejected,
    assign_exit_and_sizing_policies_v1,
    build_sizing_policy_v1,
    calendar_dte_to_expiration_us_eastern,
)


def _snap(exp: str) -> StrategyOneContextSnapshot:
    return StrategyOneContextSnapshot(
        us_equity_rth_open=True,
        context_ready_for_live_trading=True,
        context_block_reason="none",
        latest_price=500.0,
        session_vwap=499.0,
        opening_range_high=510.0,
        opening_range_low=490.0,
        latest_5m_atr=2.0,
        recent_swing_high=515.0,
        recent_swing_low=485.0,
        market_ready=True,
        market_block_reason="none",
        chain_available=True,
        chain_option_quotes_available=True,
        chain_selected_expiration=exp,
        underlying_reference_price=500.0,
    )


def _occ_call_sym(exp_iso: str) -> str:
    d = date.fromisoformat(exp_iso)
    return f"SPY  {d.strftime('%y')}{d.strftime('%m%d')}C00500000"


def _call_eval(*, exp_iso: str, swing_eligible: bool = False) -> StrategyOneEvaluationResponse:
    occ_sym = _occ_call_sym(exp_iso)
    c = NearAtmContract(
        option_symbol=occ_sym,
        strike=500.0,
        option_type="call",
        expiration_date=exp_iso,
        bid=2.0,
        ask=2.2,
        mid=2.1,
        spread_percent=10.0,
        delta=0.5,
        is_call=True,
        is_put=False,
    )
    return StrategyOneEvaluationResponse(
        decision="candidate_call",
        blockers=[],
        reasons=["ok"],
        context_snapshot_used=_snap(exp_iso),
        contract_candidate=c,
        evaluation_timestamp=datetime.now(timezone.utc),
        swing_promotion_eligible=swing_eligible,
    )


class StrategyOnePaperEntryPolicyTests(unittest.TestCase):
    def test_calendar_dte_uses_us_eastern_midnight(self) -> None:
        et = ZoneInfo("America/New_York")
        today = datetime.now(et).date()
        target = (today + timedelta(days=4)).isoformat()
        as_of = datetime.now(timezone.utc)
        self.assertEqual(calendar_dte_to_expiration_us_eastern(expiration_date_str=target, as_of_utc=as_of), 4)

    def test_sizing_fivek_five_percent_budget_and_max_affordable(self) -> None:
        s = build_sizing_policy_v1(account_equity_usd=5000.0, entry_ask_per_share=2.2, quantity=1)
        self.assertAlmostEqual(s.risk_budget_usd, 250.0, places=6)
        self.assertAlmostEqual(s.max_affordable_premium_usd, 250.0 / 0.35, places=6)
        self.assertAlmostEqual(s.entry_total_premium_usd, 220.0, places=6)

    def test_affordability_rejects_over_budget(self) -> None:
        with self.assertRaises(EntryPolicyRejected) as ctx:
            build_sizing_policy_v1(account_equity_usd=5000.0, entry_ask_per_share=7.20, quantity=1)
        self.assertEqual(ctx.exception.code, "paper_entry_premium_exceeds_risk_budget")
        d = ctx.exception.details
        self.assertEqual(d["attempted_ask"], 7.20)
        self.assertAlmostEqual(d["attempted_total_premium_usd"], 720.0, places=6)
        self.assertAlmostEqual(d["risk_budget_usd"], 250.0, places=6)
        self.assertAlmostEqual(d["max_affordable_premium_usd"], 250.0 / 0.35, places=6)
        self.assertAlmostEqual(d["premium_over_budget_usd"], 720.0 - (250.0 / 0.35), places=6)
        self.assertEqual(d["affordability_block_reason"], "premium_exceeds_risk_budget")

    def test_assign_defaults_to_intraday_when_not_swing_eligible(self) -> None:
        et = ZoneInfo("America/New_York")
        exp = (datetime.now(et).date() + timedelta(days=3)).isoformat()
        ev = _call_eval(exp_iso=exp, swing_eligible=False)
        assert ev.contract_candidate is not None
        exit_p, sizing_p = assign_exit_and_sizing_policies_v1(
            evaluation=ev,
            contract=ev.contract_candidate,
            entry_ask_per_share=2.2,
            quantity=1,
            account_equity_usd=5000.0,
            entry_clock_utc=datetime.now(timezone.utc),
        )
        self.assertEqual(exit_p.trade_horizon_class, "intraday_continuation")
        self.assertEqual(exit_p.expiry_band, "2_5_dte")
        self.assertIsNone(exit_p.promoted_swing_max_hold_trading_days)
        self.assertEqual(sizing_p.sizing_profile, "small_account_live")

    def test_promoted_swing_policy_shape_exists_in_schema(self) -> None:
        """Contract for promoted_swing payloads (assignment is gated elsewhere)."""
        p = Strategy1ExitPolicyV1(
            trade_horizon_class="promoted_swing",
            calendar_dte_at_entry=10,
            expiry_band="7_21_dte",
            thesis_stop_reference={"basis": "underlying_structure"},
            promoted_swing_max_hold_trading_days=3,
        )
        d = p.model_dump(mode="json")
        self.assertEqual(d["trade_horizon_class"], "promoted_swing")
        self.assertEqual(d["promoted_swing_max_hold_trading_days"], 3)
        self.assertEqual(d["premium_fail_safe_stop_pct"], 0.35)

    def test_sizing_policy_v1_schema_fields(self) -> None:
        s = Strategy1SizingPolicyV1(
            account_equity_usd=5000.0,
            max_risk_pct=0.05,
            max_contracts=1,
            quantity=1,
            risk_budget_usd=250.0,
            fail_safe_stop_pct=0.35,
            max_affordable_premium_usd=250.0 / 0.35,
            entry_ask_per_share=2.2,
            entry_total_premium_usd=220.0,
        )
        self.assertEqual(s.max_contracts, 1)
