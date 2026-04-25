from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.schemas.context import ContextStatusResponse, ContextSummaryResponse
from app.schemas.market import ChainLatestResponse, MarketStatusResponse, NearAtmContract
from app.services.strategy.strategy_one_spy import StrategyOneEvalInput, evaluate_strategy_one_spy


class StrategyOneRegressionGuardTests(unittest.TestCase):
    def test_baseline_candidate_call_shape_is_unchanged(self) -> None:
        status = ContextStatusResponse(
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
        summary = ContextSummaryResponse(
            symbol="SPY",
            us_equity_rth_open=True,
            context_ready_for_live_trading=True,
            context_ready_for_analysis=True,
            latest_price=510.0,
            session_vwap=505.0,
            opening_range_high=508.0,
            opening_range_low=502.0,
            latest_5m_atr=1.5,
            recent_swing_high=506.0,
            recent_swing_low=500.0,
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
        market = MarketStatusResponse(
            symbol="SPY",
            market_ready=True,
            block_reason="none",
            quote_available=True,
            chain_available=True,
            quote_age_seconds=1.0,
            chain_age_seconds=1.0,
            quote_is_fresh=True,
            chain_is_fresh=True,
            latest_quote_time=datetime.now(timezone.utc),
            latest_chain_time=datetime.now(timezone.utc),
            source_status="ok",
        )
        chain = ChainLatestResponse(
            underlying_symbol="SPY",
            available=True,
            snapshot_timestamp=datetime.now(timezone.utc),
            expiration_dates_found=["2026-04-22"],
            selected_expiration=None,
            underlying_reference_price=500.0,
            total_contracts_seen=1,
            option_quotes_available=True,
            near_atm_contracts=[
                NearAtmContract(
                    option_symbol="SPY  260422C00500000",
                    strike=500.0,
                    option_type="call",
                    expiration_date="2026-04-22",
                    bid=2.0,
                    ask=2.2,
                    mid=2.1,
                    spread_percent=9.5,
                    delta=0.5,
                    is_call=True,
                    is_put=False,
                )
            ],
            source_status="ok",
        )
        inp = StrategyOneEvalInput.from_api(status=status, summary=summary, market=market, chain=chain)
        out = evaluate_strategy_one_spy(inp, now=datetime(2026, 4, 20, 16, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(out.decision, "candidate_call")
        self.assertIsNotNone(out.contract_candidate)

