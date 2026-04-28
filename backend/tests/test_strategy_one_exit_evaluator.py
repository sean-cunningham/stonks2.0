"""Read-only Strategy 1 exit evaluator (decision support; no execution)."""

from __future__ import annotations

import os
import unittest
import unittest.mock as mock
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.models.trade import PaperTrade
from app.schemas.context import ContextStatusResponse, ContextSummaryResponse
from app.schemas.market import MarketStatusResponse
from app.schemas.paper_trade import PaperOpenPositionValuationResponse
from app.schemas.strategy_one_entry_policies import Strategy1ExitPolicyV1, Strategy1SizingPolicyV1
from app.services.paper.paper_trade_service import PaperTradeService
from app.services.paper.strategy_one_exit_evaluator import (
    ExitEvaluationInput,
    evaluate_strategy_one_open_exit_readonly,
)

# Fixed evaluation instant: 14:00 US/Eastern on 2026-05-01 (before 15:45 hard flat).
CLOCK = datetime(2026, 5, 1, 18, 0, 0, tzinfo=timezone.utc)
# 15:50 Eastern same calendar day (after hard flat while still in RTH window for tests).
CLOCK_LATE = datetime(2026, 5, 1, 19, 50, 0, tzinfo=timezone.utc)


def _exit_policy_intraday(**kwargs: object) -> dict:
    base = Strategy1ExitPolicyV1(
        trade_horizon_class="intraday_continuation",
        calendar_dte_at_entry=3,
        expiry_band="2_5_dte",
        thesis_stop_reference={"reference_type": "recent_swing_low", "level": 490.0},
        premium_fail_safe_stop_pct=0.35,
        profit_trigger_r=1.0,
        trail_activation_r=1.5,
        intraday_no_progress_timeout_minutes_min=30,
        intraday_no_progress_timeout_minutes_max=45,
        intraday_hard_flat_time_et="15:45",
        intraday_hard_flat_zone="America/New_York",
    )
    d = base.model_dump(mode="json")
    d.update(kwargs)
    return d


def _sizing_policy(entry_total: float = 220.0, ask: float = 2.2) -> dict:
    return Strategy1SizingPolicyV1(
        account_equity_usd=5000.0,
        risk_budget_usd=100.0,
        fail_safe_stop_pct=0.35,
        max_affordable_premium_usd=100.0 / 0.35,
        entry_ask_per_share=ask,
        entry_total_premium_usd=entry_total,
    ).model_dump(mode="json")


def _valuation(*, u_bid: float | None, fresh: bool = True) -> PaperOpenPositionValuationResponse:
    return PaperOpenPositionValuationResponse(
        paper_trade_id=1,
        option_symbol="SPY  260501C00500000",
        side="long",
        quantity=1,
        entry_time=CLOCK - timedelta(minutes=20),
        entry_price=2.2,
        current_bid=2.3,
        current_ask=2.4,
        current_mid=2.35,
        quote_timestamp_used=CLOCK,
        quote_age_seconds=5.0,
        quote_is_fresh=fresh,
        exit_actionable=True,
        unrealized_pnl_bid_basis=u_bid,
        unrealized_pnl_mid_basis=None,
        underlying_reference_price=500.0,
        evaluation_snapshot_reference=None,
        valuation_error=None,
    )


def _row(*, entry_decision: str = "candidate_call", entry_time: datetime | None = None) -> PaperTrade:
    t = entry_time or (CLOCK - timedelta(minutes=20))
    return PaperTrade(
        id=1,
        strategy_id=PaperTradeService.STRATEGY_ID,
        symbol="SPY",
        option_symbol="SPY  260501C00500000",
        side="long",
        quantity=1,
        entry_time=t,
        entry_price=2.2,
        exit_time=None,
        exit_price=None,
        realized_pnl=None,
        status="open",
        entry_decision=entry_decision,
        evaluation_snapshot_json={},
        entry_reference_basis="option_ask",
        exit_reference_basis=None,
        exit_reason=None,
        entry_evaluation_fingerprint="fp",
        exit_policy=_exit_policy_intraday(),
        sizing_policy=_sizing_policy(),
    )


def _market() -> MarketStatusResponse:
    return MarketStatusResponse(
        symbol="SPY",
        market_ready=True,
        block_reason="none",
        quote_available=True,
        chain_available=True,
        quote_age_seconds=1.0,
        chain_age_seconds=1.0,
        quote_is_fresh=True,
        chain_is_fresh=True,
        latest_quote_time=CLOCK,
        latest_chain_time=CLOCK,
        source_status="ok",
    )


def _status(*, rth: bool = True) -> ContextStatusResponse:
    return ContextStatusResponse(
        symbol="SPY",
        us_equity_rth_open=rth,
        context_ready_for_live_trading=rth,
        context_ready_for_analysis=True,
        context_ready=rth,
        block_reason="none",
        block_reason_analysis="none",
        latest_session_date_et=None,
        latest_1m_bar_time=None,
        latest_5m_bar_time=None,
        bars_1m_available=True,
        bars_5m_available=True,
        vwap_available=True,
        opening_range_available=True,
        atr_available=True,
        source_status="ok",
        bars_source="dxlink",
    )


def _summary(*, price: float = 500.0, atr: float = 2.0) -> ContextSummaryResponse:
    return ContextSummaryResponse(
        symbol="SPY",
        us_equity_rth_open=True,
        context_ready_for_live_trading=True,
        context_ready_for_analysis=True,
        latest_price=price,
        session_vwap=499.0,
        opening_range_high=510.0,
        opening_range_low=490.0,
        latest_5m_atr=atr,
        recent_swing_high=515.0,
        recent_swing_low=485.0,
        relative_volume_5m=None,
        relative_volume_available=False,
        latest_1m_bar_time=None,
        latest_5m_bar_time=None,
        latest_session_date_et=date(2026, 5, 1),
        context_ready=True,
        block_reason="none",
        block_reason_analysis="none",
        source_status="ok",
        bars_source="dxlink",
    )


class StrategyOneExitEvaluatorTests(unittest.TestCase):
    def test_legacy_open_row_bootstraps_exit_state_fields(self) -> None:
        row = _row()
        row.active_stop_price = None
        row.take_profit_price = None
        row.max_unrealized_pnl_percent = None
        row.profit_lock_stage = None
        v = _valuation(u_bid=0.0)
        v = v.model_copy(update={"current_bid": 2.2})
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(),
            context_summary=_summary(price=500.0),
            market_status=_market(),
            clock_utc=CLOCK,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertEqual(out.action, "hold")
        self.assertAlmostEqual(float(out.exit_levels_snapshot["active_stop_price"]), 1.65, places=6)
        self.assertAlmostEqual(float(out.exit_levels_snapshot["take_profit_price"]), 3.3, places=6)
        self.assertEqual(out.exit_levels_snapshot["profit_lock_stage"], "none")

    def test_fail_safe_breach_close_now(self) -> None:
        """Initial hard stop is -25% premium from entry."""
        row = _row()
        v = _valuation(u_bid=-60.0)
        v = v.model_copy(update={"current_bid": 1.64})  # below 2.2 * 0.75 = 1.65
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(),
            context_summary=_summary(price=500.0),
            market_status=_market(),
            clock_utc=CLOCK,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertEqual(out.action, "close_now")
        self.assertIn("hard_stop_25pct", out.reasons)

    def test_thesis_break_call_close_now(self) -> None:
        row = _row()
        v = _valuation(u_bid=10.0)
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(),
            context_summary=_summary(price=480.0),
            market_status=_market(),
            clock_utc=CLOCK,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertEqual(out.action, "close_now")
        self.assertTrue(any("thesis" in r.lower() for r in out.reasons))

    def test_thesis_break_put_close_now(self) -> None:
        pol = _exit_policy_intraday(
            thesis_stop_reference={"reference_type": "recent_swing_high", "level": 510.0}
        )
        row = _row(entry_decision="candidate_put")
        row.exit_policy = pol
        v = _valuation(u_bid=5.0)
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(),
            context_summary=_summary(price=520.0),
            market_status=_market(),
            clock_utc=CLOCK,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertEqual(out.action, "close_now")

    def test_intraday_hard_flat_close_now(self) -> None:
        row = _row()
        v = _valuation(u_bid=5.0)
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(rth=True),
            context_summary=_summary(),
            market_status=_market(),
            clock_utc=CLOCK_LATE,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertEqual(out.action, "close_now")
        self.assertTrue(any("hard_flat" in r for r in out.reasons))

    def test_take_profit_50pct_close_now(self) -> None:
        row = _row()
        v = _valuation(u_bid=120.0)
        v = v.model_copy(update={"current_bid": 3.30})  # 50% over 2.2
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(),
            context_summary=_summary(price=500.0),
            market_status=_market(),
            clock_utc=CLOCK,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertEqual(out.action, "close_now")
        self.assertIn("take_profit_50pct", out.reasons)

    def test_stage_advances_to_breakeven_at_25pct(self) -> None:
        row = _row()
        v = _valuation(u_bid=60.0)
        v = v.model_copy(update={"current_bid": 2.751})  # just above +25%
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(),
            context_summary=_summary(price=500.0),
            market_status=_market(),
            clock_utc=CLOCK,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertEqual(out.action, "hold")
        self.assertEqual(out.exit_levels_snapshot.get("profit_lock_stage"), "breakeven")
        self.assertAlmostEqual(float(out.exit_levels_snapshot["active_stop_price"]), 2.2, places=6)

    def test_pullback_to_entry_after_25pct_closes_breakeven(self) -> None:
        row = _row()
        row.max_unrealized_pnl_percent = 0.25
        row.profit_lock_stage = "breakeven"
        row.active_stop_price = 2.2
        v = _valuation(u_bid=0.0)
        v = v.model_copy(update={"current_bid": 2.2})
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(),
            context_summary=_summary(price=500.0),
            market_status=_market(),
            clock_utc=CLOCK,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertEqual(out.action, "close_now")
        self.assertIn("breakeven_stop_after_25pct", out.reasons)

    def test_stage_advances_to_lock_15_at_40pct(self) -> None:
        row = _row()
        v = _valuation(u_bid=90.0)
        v = v.model_copy(update={"current_bid": 3.081})  # just above +40%
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(),
            context_summary=_summary(price=500.0),
            market_status=_market(),
            clock_utc=CLOCK,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertEqual(out.action, "hold")
        self.assertEqual(out.exit_levels_snapshot.get("profit_lock_stage"), "lock_15")
        self.assertAlmostEqual(float(out.exit_levels_snapshot["active_stop_price"]), 2.53, places=6)

    def test_pullback_to_lock_15_after_40pct_closes(self) -> None:
        row = _row()
        row.max_unrealized_pnl_percent = 0.40
        row.profit_lock_stage = "lock_15"
        row.active_stop_price = 2.53
        v = _valuation(u_bid=0.0)
        v = v.model_copy(update={"current_bid": 2.53})
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(),
            context_summary=_summary(price=500.0),
            market_status=_market(),
            clock_utc=CLOCK,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertEqual(out.action, "close_now")
        self.assertIn("profit_lock_15pct_after_40pct", out.reasons)

    def test_healthy_below_profit_trigger_hold(self) -> None:
        row = _row()
        v = _valuation(u_bid=20.0)
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(),
            context_summary=_summary(price=500.0),
            market_status=_market(),
            clock_utc=CLOCK,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertEqual(out.action, "hold")
        self.assertEqual(out.blockers, [])
        self.assertNotIn("evaluation_blocked_non_actionable_state", out.reasons)

    def test_time_stop_closes_after_90min_when_under_15pct(self) -> None:
        row = _row(entry_time=CLOCK - timedelta(minutes=95))
        v = _valuation(u_bid=10.0)
        v = v.model_copy(update={"current_bid": 2.3})  # ~4.5%
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(),
            context_summary=_summary(price=500.0),
            market_status=_market(),
            clock_utc=CLOCK,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertEqual(out.action, "close_now")
        self.assertIn("time_stop_under_15pct_after_90min", out.reasons)

    def test_time_stop_does_not_close_when_at_or_above_15pct(self) -> None:
        row = _row(entry_time=CLOCK - timedelta(minutes=95))
        v = _valuation(u_bid=40.0)
        v = v.model_copy(update={"current_bid": 2.531})  # slightly above +15%
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(),
            context_summary=_summary(price=500.0),
            market_status=_market(),
            clock_utc=CLOCK,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertEqual(out.action, "hold")

    def test_closed_position_blocked(self) -> None:
        row = _row()
        row.status = "closed"
        v = _valuation(u_bid=0.0)
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(),
            context_summary=_summary(),
            market_status=_market(),
            clock_utc=CLOCK,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertEqual(out.action, "hold")
        self.assertIn("not_open_position", out.blockers)
        self.assertIn("evaluation_blocked_non_actionable_state", out.reasons)

    def test_missing_exit_policy_non_actionable(self) -> None:
        row = _row()
        row.exit_policy = None
        v = _valuation(u_bid=0.0)
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(),
            context_summary=_summary(),
            market_status=_market(),
            clock_utc=CLOCK,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertEqual(out.action, "hold")
        self.assertIn("missing_exit_policy", out.blockers)
        self.assertIn("evaluation_blocked_non_actionable_state", out.reasons)

    def test_missing_sizing_policy_non_actionable(self) -> None:
        row = _row()
        row.sizing_policy = None
        v = _valuation(u_bid=0.0)
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(),
            context_summary=_summary(),
            market_status=_market(),
            clock_utc=CLOCK,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertIn("missing_sizing_policy", out.blockers)
        self.assertIn("evaluation_blocked_non_actionable_state", out.reasons)

    def test_stale_valuation_non_actionable(self) -> None:
        row = _row()
        v = _valuation(u_bid=10.0, fresh=False)
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(),
            context_summary=_summary(),
            market_status=_market(),
            clock_utc=CLOCK,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertEqual(out.action, "hold")
        self.assertIn("stale_valuation", out.blockers)
        self.assertIn("evaluation_blocked_non_actionable_state", out.reasons)

    def test_exit_not_actionable_non_actionable(self) -> None:
        row = _row()
        v = _valuation(u_bid=10.0, fresh=True)
        v = v.model_copy(update={"exit_actionable": False})
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(),
            context_summary=_summary(),
            market_status=_market(),
            clock_utc=CLOCK,
        )
        out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertIn("exit_not_actionable_missing_fresh_option_quote", out.blockers)
        self.assertIn("evaluation_blocked_non_actionable_state", out.reasons)

    def test_hard_flat_independent_of_process_tz_env(self) -> None:
        """15:50 America/New_York == 19:50 UTC on 2026-05-01 (EDT); evaluator uses astimezone(policy zone)."""
        et = ZoneInfo("America/New_York")
        self.assertEqual(
            CLOCK_LATE.astimezone(et).strftime("%H:%M"),
            "15:50",
        )
        row = _row()
        v = _valuation(u_bid=5.0)
        inp = ExitEvaluationInput(
            position=row,
            valuation=v,
            context_status=_status(rth=True),
            context_summary=_summary(),
            market_status=_market(),
            clock_utc=CLOCK_LATE,
        )
        with mock.patch.dict(os.environ, {"TZ": "America/Los_Angeles"}, clear=False):
            out = evaluate_strategy_one_open_exit_readonly(inp)
        self.assertEqual(out.action, "close_now")
        self.assertTrue(any("hard_flat" in r for r in out.reasons))
