"""Strategy 1 unified position monitor (derive state + row assembly)."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from app.core.config import Settings
from app.models.trade import PaperTrade
from app.schemas.context import ContextStatusResponse, ContextSummaryResponse
from app.schemas.market import ChainLatestResponse, MarketStatusResponse, NearAtmContract
from app.schemas.strategy_one_entry_policies import Strategy1ExitPolicyV1, Strategy1SizingPolicyV1
from app.schemas.strategy_one_exit_evaluation import StrategyOneExitEvaluationResponse
from app.services.paper.paper_trade_service import PaperTradeService
from app.services.paper.strategy_one_position_monitor import (
    build_open_positions_monitor,
    build_position_monitor_row,
    derive_monitor_state,
)


def _chain(sym: str, exp: str, *, bid: float = 2.0, ask: float = 2.2) -> ChainLatestResponse:
    ts = datetime(2026, 5, 1, 18, 0, 0, tzinfo=timezone.utc)
    c = NearAtmContract(
        option_symbol=sym,
        strike=500.0,
        option_type="call",
        expiration_date=exp,
        bid=bid,
        ask=ask,
        mid=(bid + ask) / 2.0,
        spread_percent=10.0,
        delta=0.5,
        is_call=True,
        is_put=False,
    )
    return ChainLatestResponse(
        underlying_symbol="SPY",
        available=True,
        snapshot_timestamp=ts,
        expiration_dates_found=[exp],
        selected_expiration=exp,
        underlying_reference_price=500.0,
        total_contracts_seen=1,
        option_quotes_available=True,
        near_atm_contracts=[c],
        source_status="ok",
    )


def _paper_row(*, sym: str, exp: str) -> PaperTrade:
    return PaperTrade(
        id=1,
        strategy_id=PaperTradeService.STRATEGY_ID,
        symbol="SPY",
        option_symbol=sym,
        side="long",
        quantity=1,
        entry_time=datetime(2026, 5, 1, 17, 55, 0, tzinfo=timezone.utc),
        entry_price=2.2,
        exit_time=None,
        exit_price=None,
        realized_pnl=None,
        status="open",
        entry_decision="candidate_call",
        evaluation_snapshot_json={},
        entry_reference_basis="option_ask",
        exit_reference_basis=None,
        exit_reason=None,
        entry_evaluation_fingerprint="fp",
        exit_policy=Strategy1ExitPolicyV1(
            trade_horizon_class="intraday_continuation",
            calendar_dte_at_entry=3,
            expiry_band="2_5_dte",
            thesis_stop_reference={"level": 400.0},
        ).model_dump(mode="json"),
        sizing_policy=Strategy1SizingPolicyV1(
            account_equity_usd=5000.0,
            risk_budget_usd=100.0,
            fail_safe_stop_pct=0.35,
            max_affordable_premium_usd=100.0 / 0.35,
            entry_ask_per_share=2.2,
            entry_total_premium_usd=220.0,
        ).model_dump(mode="json"),
    )


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
        bars_source="dxlink",
    )


def _summary(*, price: float = 500.0) -> ContextSummaryResponse:
    return ContextSummaryResponse(
        symbol="SPY",
        us_equity_rth_open=True,
        context_ready_for_live_trading=True,
        context_ready_for_analysis=True,
        latest_price=price,
        session_vwap=499.0,
        opening_range_high=510.0,
        opening_range_low=490.0,
        latest_5m_atr=2.0,
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


def _market() -> MarketStatusResponse:
    t = datetime(2026, 5, 1, 18, 0, 0, tzinfo=timezone.utc)
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
        latest_quote_time=t,
        latest_chain_time=t,
        source_status="ok",
    )


class DeriveMonitorStateTests(unittest.TestCase):
    def test_close_now(self) -> None:
        ev = StrategyOneExitEvaluationResponse(
            action="close_now",
            reasons=["x"],
            blockers=[],
            evaluation_timestamp=datetime.now(timezone.utc),
        )
        self.assertEqual(derive_monitor_state(ev), "close_now")

    def test_trail_active(self) -> None:
        ev = StrategyOneExitEvaluationResponse(
            action="trail_active",
            reasons=["x"],
            blockers=[],
            evaluation_timestamp=datetime.now(timezone.utc),
        )
        self.assertEqual(derive_monitor_state(ev), "trail_active")

    def test_tighten_stop_protected(self) -> None:
        ev = StrategyOneExitEvaluationResponse(
            action="tighten_stop",
            reasons=["x"],
            blockers=[],
            evaluation_timestamp=datetime.now(timezone.utc),
        )
        self.assertEqual(derive_monitor_state(ev), "protected")

    def test_hold_with_blockers_blocked(self) -> None:
        ev = StrategyOneExitEvaluationResponse(
            action="hold",
            reasons=["evaluation_blocked_non_actionable_state"],
            blockers=["stale_valuation"],
            evaluation_timestamp=datetime.now(timezone.utc),
        )
        self.assertEqual(derive_monitor_state(ev), "blocked")

    def test_hold_clear_healthy(self) -> None:
        ev = StrategyOneExitEvaluationResponse(
            action="hold",
            reasons=["no_exit_rules_triggered"],
            blockers=[],
            evaluation_timestamp=datetime.now(timezone.utc),
        )
        self.assertEqual(derive_monitor_state(ev), "healthy")

    def test_promote_maps_to_healthy(self) -> None:
        ev = StrategyOneExitEvaluationResponse(
            action="promote_to_swing_candidate",
            reasons=["hint"],
            blockers=[],
            evaluation_timestamp=datetime.now(timezone.utc),
        )
        self.assertEqual(derive_monitor_state(ev), "healthy")


class BuildMonitorRowTests(unittest.TestCase):
    def test_monitor_row_includes_valuation_and_exit_eval(self) -> None:
        sym, exp = "SPY  260501C00500000", "2026-05-01"
        row = _paper_row(sym=sym, exp=exp)
        ch = _chain(sym, exp)
        settings = Settings(MARKET_CHAIN_MAX_AGE_SECONDS=3600, MARKET_QUOTE_MAX_AGE_SECONDS=3600)
        ts = datetime(2026, 5, 1, 18, 0, 0, tzinfo=timezone.utc)
        m = build_position_monitor_row(
            row,
            chain=ch,
            settings=settings,
            context_status=_status(),
            context_summary=_summary(price=500.0),
            market_status=_market(),
            evaluation_timestamp=ts,
        )
        self.assertEqual(m.paper_trade_id, 1)
        self.assertEqual(m.monitor_state, "healthy")
        self.assertIsNotNone(m.valuation.unrealized_pnl_bid_basis)
        self.assertEqual(m.exit_evaluation.action, "hold")

    def test_batch_monitor_two_rows_shared_chain(self) -> None:
        sym1, exp1 = "SPY  260501C00500000", "2026-05-01"
        sym2, exp2 = "SPY  260501P00500000", "2026-05-01"
        r1 = _paper_row(sym=sym1, exp=exp1)
        r2 = _paper_row(sym=sym2, exp=exp2)
        r2.id = 2
        r2.option_symbol = sym2
        r2.entry_decision = "candidate_put"
        r2.exit_policy = Strategy1ExitPolicyV1(
            trade_horizon_class="intraday_continuation",
            calendar_dte_at_entry=3,
            expiry_band="2_5_dte",
            thesis_stop_reference={"level": 520.0},
        ).model_dump(mode="json")
        ch = ChainLatestResponse(
            underlying_symbol="SPY",
            available=True,
            snapshot_timestamp=datetime(2026, 5, 1, 18, 0, 0, tzinfo=timezone.utc),
            expiration_dates_found=[exp1],
            selected_expiration=exp1,
            underlying_reference_price=500.0,
            total_contracts_seen=2,
            option_quotes_available=True,
            near_atm_contracts=[
                NearAtmContract(
                    option_symbol=sym1,
                    strike=500.0,
                    option_type="call",
                    expiration_date=exp1,
                    bid=2.0,
                    ask=2.2,
                    mid=2.1,
                    spread_percent=10.0,
                    delta=0.5,
                    is_call=True,
                    is_put=False,
                ),
                NearAtmContract(
                    option_symbol=sym2,
                    strike=500.0,
                    option_type="put",
                    expiration_date=exp2,
                    bid=2.6,
                    ask=2.8,
                    mid=2.7,
                    spread_percent=8.0,
                    delta=-0.4,
                    is_call=False,
                    is_put=True,
                ),
            ],
            source_status="ok",
        )
        settings = Settings(MARKET_CHAIN_MAX_AGE_SECONDS=3600, MARKET_QUOTE_MAX_AGE_SECONDS=3600)
        out = build_open_positions_monitor(
            [r1, r2],
            chain=ch,
            settings=settings,
            context_status=_status(),
            context_summary=_summary(),
            market_status=_market(),
            evaluation_timestamp=datetime(2026, 5, 1, 18, 0, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(len(out.positions), 2)
        self.assertEqual(out.positions[0].option_symbol, sym1)
        self.assertEqual(out.positions[1].option_symbol, sym2)
