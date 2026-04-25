from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.models.trade import PaperTrade
from app.schemas.context import ContextStatusResponse, ContextSummaryResponse
from app.schemas.market import MarketStatusResponse
from app.schemas.paper_trade import PaperOpenPositionValuationResponse
from app.services.paper.strategy_two_exit_evaluator import ExitEvaluationInput, evaluate_strategy_two_open_exit_readonly


def _status() -> ContextStatusResponse:
    return ContextStatusResponse(
        symbol="SPY",
        us_equity_rth_open=True,
        context_ready_for_live_trading=True,
        context_ready_for_analysis=True,
        context_ready=True,
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
        bars_source="ok",
    )


def _summary(latest_price: float = 500.0) -> ContextSummaryResponse:
    return ContextSummaryResponse(
        symbol="SPY",
        us_equity_rth_open=True,
        context_ready_for_live_trading=True,
        context_ready_for_analysis=True,
        latest_price=latest_price,
        session_vwap=500.0,
        opening_range_high=502.0,
        opening_range_low=498.0,
        latest_5m_atr=1.0,
        recent_swing_high=503.0,
        recent_swing_low=497.0,
        relative_volume_5m=None,
        relative_volume_available=False,
        latest_1m_bar_time=None,
        latest_5m_bar_time=None,
        latest_session_date_et=None,
        context_ready=True,
        block_reason="none",
        block_reason_analysis="none",
        source_status="ok",
        bars_source="ok",
    )


def _market() -> MarketStatusResponse:
    now = datetime.now(timezone.utc)
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
        latest_quote_time=now,
        latest_chain_time=now,
        source_status="ok",
    )


def _position(*, entry_price: float, entry_minutes_ago: int, setup_type: str = "call_breakout") -> PaperTrade:
    now = datetime.now(timezone.utc)
    return PaperTrade(
        id=1,
        strategy_id="strategy_2_spy_0dte_vol_sniper",
        symbol="SPY",
        option_symbol="SPY  260425C00500000",
        side="long",
        quantity=1,
        entry_time=now - timedelta(minutes=entry_minutes_ago),
        entry_price=entry_price,
        exit_time=None,
        exit_price=None,
        realized_pnl=None,
        status="open",
        entry_decision="candidate_call",
        evaluation_snapshot_json={"diagnostics": {"near_miss": {"nearest_trigger_level": 500.0, "setup_type": setup_type}}},
        entry_reference_basis="option_ask",
        exit_reference_basis=None,
        exit_reason=None,
        entry_evaluation_fingerprint="x",
        exit_policy={
            "premium_fail_safe_stop_pct": 0.15,
            "profit_target_pct": 0.20,
            "speed_failure_seconds": 90,
            "max_hold_seconds": 300,
            "hard_flat_time_et": "15:45",
        },
        sizing_policy={},
    )


def _valuation(*, bid: float, unrealized: float) -> PaperOpenPositionValuationResponse:
    return PaperOpenPositionValuationResponse(
        paper_trade_id=1,
        strategy_id="strategy_2_spy_0dte_vol_sniper",
        symbol="SPY",
        option_symbol="SPY  260425C00500000",
        side="long",
        quantity=1,
        entry_time=datetime.now(timezone.utc) - timedelta(minutes=1),
        entry_price=1.0,
        current_bid=bid,
        current_ask=bid + 0.02,
        current_mid=bid + 0.01,
        quote_time=datetime.now(timezone.utc),
        quote_age_seconds=1.0,
        quote_is_fresh=True,
        valuation_error=None,
        unrealized_pnl_bid_basis=unrealized,
        unrealized_return_pct_bid_basis=(unrealized / 100.0) * 100.0,
        exit_actionable=True,
        valuation_timestamp=datetime.now(timezone.utc),
    )


class StrategyTwoExitEvaluatorTests(unittest.TestCase):
    def test_exits_at_profit_target_plus_twenty_percent(self) -> None:
        row = _position(entry_price=1.0, entry_minutes_ago=1)
        val = _valuation(bid=1.20, unrealized=20.0)
        out = evaluate_strategy_two_open_exit_readonly(
            ExitEvaluationInput(
                position=row,
                valuation=val,
                context_status=_status(),
                context_summary=_summary(latest_price=501.0),
                market_status=_market(),
            )
        )
        self.assertEqual(out.action, "close_now")
        self.assertIn("profit_target_reached", out.reasons)

    def test_exits_at_hard_stop_minus_fifteen_percent(self) -> None:
        row = _position(entry_price=1.0, entry_minutes_ago=1)
        val = _valuation(bid=0.85, unrealized=-15.0)
        out = evaluate_strategy_two_open_exit_readonly(
            ExitEvaluationInput(position=row, valuation=val, context_status=_status(), context_summary=_summary(499.0), market_status=_market())
        )
        self.assertEqual(out.action, "close_now")
        self.assertIn("hard_stop_reached", out.reasons)

    def test_exits_on_speed_failure_after_ninety_seconds(self) -> None:
        row = _position(entry_price=1.0, entry_minutes_ago=2, setup_type="call_breakout")
        val = _valuation(bid=1.00, unrealized=0.0)
        out = evaluate_strategy_two_open_exit_readonly(
            ExitEvaluationInput(position=row, valuation=val, context_status=_status(), context_summary=_summary(499.8), market_status=_market())
        )
        self.assertEqual(out.action, "close_now")
        self.assertIn("speed_failure_after_90s", out.reasons)

    def test_exits_after_max_hold_five_minutes(self) -> None:
        row = _position(entry_price=1.0, entry_minutes_ago=6)
        val = _valuation(bid=1.00, unrealized=0.0)
        out = evaluate_strategy_two_open_exit_readonly(
            ExitEvaluationInput(position=row, valuation=val, context_status=_status(), context_summary=_summary(500.1), market_status=_market())
        )
        self.assertEqual(out.action, "close_now")
        self.assertIn("max_hold_time_reached", out.reasons)

    def test_force_flat_by_1545(self) -> None:
        row = _position(entry_price=1.0, entry_minutes_ago=1)
        val = _valuation(bid=1.00, unrealized=0.0)
        forced_clock = datetime.now(timezone.utc).replace(hour=20, minute=0, second=0, microsecond=0)  # 16:00 ET during DST
        out = evaluate_strategy_two_open_exit_readonly(
            ExitEvaluationInput(
                position=row,
                valuation=val,
                context_status=_status(),
                context_summary=_summary(500.1),
                market_status=_market(),
                clock_utc=forced_clock,
            )
        )
        self.assertEqual(out.action, "close_now")
        self.assertIn("hard_flat_0dte_time", out.reasons)

