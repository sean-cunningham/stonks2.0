"""Strategy 1 SPY read-only evaluator — tests define tightened structure and no-trade zones."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.schemas.context import ContextStatusResponse, ContextSummaryResponse
from app.schemas.market import ChainLatestResponse, MarketStatusResponse, NearAtmContract
from app.services.strategy.strategy_one_spy import StrategyOneEvalInput, evaluate_strategy_one_spy

# Fixed clock so calendar DTE vs expiration dates is deterministic in tests.
EVAL_CLOCK = datetime(2026, 4, 20, 16, 0, 0, tzinfo=timezone.utc)


def _status(*, live: bool = True, block: str = "none") -> ContextStatusResponse:
    return ContextStatusResponse(
        symbol="SPY",
        us_equity_rth_open=True,
        context_ready_for_live_trading=live,
        context_ready_for_analysis=True,
        context_ready=live,
        block_reason=block,
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
        bars_source="tastytrade_dxlink_candle",
    )


def _summary(
    *,
    px: float,
    vwap: float,
    orh: float,
    orl: float,
    atr: float,
    swing_h: float,
    swing_l: float,
) -> ContextSummaryResponse:
    return ContextSummaryResponse(
        symbol="SPY",
        us_equity_rth_open=True,
        context_ready_for_live_trading=True,
        context_ready_for_analysis=True,
        latest_price=px,
        session_vwap=vwap,
        opening_range_high=orh,
        opening_range_low=orl,
        latest_5m_atr=atr,
        recent_swing_high=swing_h,
        recent_swing_low=swing_l,
        relative_volume_5m=None,
        relative_volume_available=False,
        latest_1m_bar_time=None,
        latest_5m_bar_time=None,
        latest_session_date_et=None,
        context_ready=True,
        block_reason="none",
        block_reason_analysis="none",
        source_status="ok",
        bars_source="tastytrade_dxlink_candle",
    )


def _market(*, ready: bool = True, block: str = "none") -> MarketStatusResponse:
    return MarketStatusResponse(
        symbol="SPY",
        market_ready=ready,
        block_reason=block,
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


def _chain(
    *,
    contracts: list[NearAtmContract],
    ref: float = 500.0,
    expiration_dates_found: list[str] | None = None,
    selected_expiration: str | None = None,
) -> ChainLatestResponse:
    exp_found = expiration_dates_found
    if exp_found is None:
        exp_found = sorted({c.expiration_date for c in contracts if c.expiration_date})
    return ChainLatestResponse(
        underlying_symbol="SPY",
        available=True,
        snapshot_timestamp=EVAL_CLOCK,
        expiration_dates_found=exp_found,
        selected_expiration=selected_expiration,
        underlying_reference_price=ref,
        total_contracts_seen=len(contracts),
        option_quotes_available=True,
        near_atm_contracts=contracts,
        source_status="ok",
    )


def _good_call(
    strike: float = 500.0,
    delta: float | None = None,
    *,
    sym: str | None = None,
    expiration_date: str = "2026-04-22",
) -> NearAtmContract:
    return NearAtmContract(
        option_symbol=sym or "SPY  260422C00500000",
        strike=strike,
        option_type="call",
        expiration_date=expiration_date,
        bid=2.0,
        ask=2.2,
        mid=2.1,
        spread_percent=9.52,
        delta=delta,
        is_call=True,
        is_put=False,
    )


def _good_put(
    strike: float = 500.0,
    delta: float | None = None,
    *,
    sym: str | None = None,
    expiration_date: str = "2026-04-22",
) -> NearAtmContract:
    return NearAtmContract(
        option_symbol=sym or "SPY  260422P00500000",
        strike=strike,
        option_type="put",
        expiration_date=expiration_date,
        bid=2.1,
        ask=2.3,
        mid=2.2,
        spread_percent=9.09,
        delta=delta,
        is_call=False,
        is_put=True,
    )


class StrategyOneEvaluationTests(unittest.TestCase):
    def test_bullish_breakout_returns_candidate_call(self) -> None:
        """Breakout: above OR high and above recent swing high."""
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=510.0, vwap=505.0, orh=508.0, orl=502.0, atr=1.5, swing_h=506.0, swing_l=500.0),
            market=_market(),
            chain=_chain(contracts=[_good_call(strike=500.0), _good_put()]),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "candidate_call")
        self.assertIsNotNone(out.contract_candidate)
        self.assertEqual(out.contract_candidate.option_type, "call")
        self.assertEqual(out.blockers, [])
        self.assertTrue(any("breakout" in r for r in out.reasons))
        self.assertTrue(any("nearest_strike_intraday_dte_band" in r for r in out.reasons))

    def test_bullish_reclaim_inside_or_returns_candidate_call(self) -> None:
        """Inside OR upper half: must be at/above recent swing high."""
        # orl=502, orh=508, mid=505; px=506 inside, above vwap 504, above swing high 505.5
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=506.0, vwap=504.0, orh=508.0, orl=502.0, atr=1.5, swing_h=505.5, swing_l=498.0),
            market=_market(),
            chain=_chain(contracts=[_good_call(strike=500.0)]),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "candidate_call")
        self.assertTrue(any("reclaim" in r or "inside_or" in r for r in out.reasons))
        self.assertTrue(any("nearest_strike_intraday_dte_band" in r for r in out.reasons))

    def test_bearish_breakdown_returns_candidate_put(self) -> None:
        """Below OR low and below recent swing low."""
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=497.0, vwap=502.0, orh=508.0, orl=500.0, atr=1.5, swing_h=510.0, swing_l=499.0),
            market=_market(),
            chain=_chain(contracts=[_good_call(), _good_put(strike=500.0)]),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "candidate_put")
        self.assertIsNotNone(out.contract_candidate)
        self.assertEqual(out.contract_candidate.option_type, "put")
        self.assertTrue(any("breakdown" in r for r in out.reasons))
        self.assertTrue(any("nearest_strike_intraday_dte_band" in r for r in out.reasons))

    def test_bearish_inside_or_returns_candidate_put(self) -> None:
        """Lower half inside OR: must be at/below recent swing low."""
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=503.0, vwap=506.0, orh=508.0, orl=502.0, atr=1.5, swing_h=509.0, swing_l=503.5),
            market=_market(),
            chain=_chain(contracts=[_good_put(strike=500.0)]),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "candidate_put")
        self.assertTrue(any("inside_or" in r or "distribution" in r for r in out.reasons))

    def test_no_trade_mixed_vwap_and_opening_range_geometry(self) -> None:
        """Bullish VWAP but lower half of opening range (inside OR only)."""
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=504.5, vwap=503.0, orh=508.0, orl=502.0, atr=2.0, swing_h=520.0, swing_l=500.0),
            market=_market(),
            chain=_chain(contracts=[_good_call()]),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "no_trade")
        self.assertTrue(any("mixed" in b for b in out.blockers))

    def test_no_trade_vwap_atr_chop_zone(self) -> None:
        """Price too close to VWAP vs ATR — no directional edge."""
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=500.1, vwap=500.0, orh=510.0, orl=490.0, atr=2.0, swing_h=515.0, swing_l=485.0),
            market=_market(),
            chain=_chain(contracts=[_good_call()]),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "no_trade")
        self.assertTrue(any("vwap_atr_band" in b for b in out.blockers))

    def test_weak_bear_old_pattern_no_candidate_put(self) -> None:
        """Below VWAP + lower OR half but NOT at/below swing low and NOT below ORL -> no bear candidate."""
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=504.0, vwap=506.0, orh=508.0, orl=502.0, atr=1.5, swing_h=520.0, swing_l=500.0),
            market=_market(),
            chain=_chain(contracts=[_good_put()]),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "no_trade")

    def test_weak_bull_old_pattern_no_candidate_call(self) -> None:
        """Above VWAP + upper OR half but NOT at/above swing high and NOT above ORH -> no bull candidate."""
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=506.0, vwap=504.0, orh=510.0, orl=502.0, atr=1.5, swing_h=508.0, swing_l=500.0),
            market=_market(),
            chain=_chain(contracts=[_good_call()]),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "no_trade")

    def test_contract_nearest_strike_only_delta_ignored_when_present(self) -> None:
        """Selection is nearest strike among quality rows; delta on row must not change pick."""
        c_far = _good_call(strike=498.0, delta=0.5, sym="SPY  260422C00498000")
        c_near = _good_call(strike=500.5, delta=0.1, sym="SPY  260422C00500500")
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=511.0, vwap=505.0, orh=508.0, orl=502.0, atr=1.5, swing_h=506.0, swing_l=500.0),
            market=_market(),
            chain=_chain(contracts=[c_far, c_near], ref=500.0),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "candidate_call")
        self.assertEqual(out.contract_candidate.strike, 500.5)
        self.assertTrue(any("nearest_strike_intraday_dte_band" in r for r in out.reasons))

    def test_no_trade_when_context_not_live_ready(self) -> None:
        inp = StrategyOneEvalInput.from_api(
            status=_status(live=False, block="stale_1m_bars"),
            summary=_summary(px=510.0, vwap=505.0, orh=508.0, orl=502.0, atr=1.5, swing_h=506.0, swing_l=500.0),
            market=_market(),
            chain=_chain(contracts=[_good_call()]),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "no_trade")
        self.assertTrue(any("context" in b.lower() for b in out.blockers))

    def test_no_trade_when_required_metrics_null(self) -> None:
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=510.0, vwap=505.0, orh=508.0, orl=502.0, atr=1.5, swing_h=506.0, swing_l=500.0).model_copy(
                update={"session_vwap": None}
            ),
            market=_market(),
            chain=_chain(contracts=[_good_call()]),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "no_trade")
        self.assertTrue(out.blockers)

    def test_no_trade_when_no_acceptable_contract(self) -> None:
        bad = NearAtmContract(
            option_symbol="SPY  260422C00500000",
            strike=500.0,
            option_type="call",
            expiration_date="2026-04-22",
            bid=0.01,
            ask=5.0,
            mid=2.5,
            spread_percent=199.0,
            is_call=True,
            is_put=False,
        )
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=510.0, vwap=505.0, orh=508.0, orl=502.0, atr=1.5, swing_h=506.0, swing_l=500.0),
            market=_market(),
            chain=_chain(contracts=[bad]),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "no_trade")
        self.assertTrue(any("contract" in b.lower() for b in out.blockers))

    def test_stale_quote_blocks_with_market_not_ready(self) -> None:
        stale_market = MarketStatusResponse(
            symbol="SPY",
            market_ready=False,
            block_reason="stale_quote",
            quote_available=True,
            chain_available=True,
            quote_age_seconds=120.0,
            chain_age_seconds=1.0,
            quote_is_fresh=False,
            chain_is_fresh=True,
            latest_quote_time=datetime(2026, 4, 21, 16, 0, 0, tzinfo=timezone.utc),
            latest_chain_time=datetime.now(timezone.utc),
            source_status="ok",
        )
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=510.0, vwap=505.0, orh=508.0, orl=502.0, atr=1.5, swing_h=506.0, swing_l=500.0),
            market=stale_market,
            chain=_chain(contracts=[_good_call()]),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "no_trade")
        self.assertIn("market_not_ready:stale_quote", out.blockers)

    def test_healthy_context_and_market_no_stale_quote_blocker(self) -> None:
        """Live context + fresh market should not emit a stale_quote market blocker."""
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=510.0, vwap=505.0, orh=508.0, orl=502.0, atr=1.5, swing_h=506.0, swing_l=500.0),
            market=_market(),
            chain=_chain(contracts=[_good_call(strike=500.0), _good_put()]),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertFalse(any("stale_quote" in b for b in out.blockers))

    def test_evaluation_snapshot_includes_quote_freshness_debug(self) -> None:
        qt = datetime(2026, 4, 21, 17, 30, 0, tzinfo=timezone.utc)
        m = MarketStatusResponse(
            symbol="SPY",
            market_ready=True,
            block_reason="none",
            quote_available=True,
            chain_available=True,
            quote_age_seconds=3.5,
            chain_age_seconds=2.0,
            quote_is_fresh=True,
            chain_is_fresh=True,
            latest_quote_time=qt,
            latest_chain_time=datetime.now(timezone.utc),
            source_status="ok",
        )
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=510.0, vwap=505.0, orh=508.0, orl=502.0, atr=1.5, swing_h=506.0, swing_l=500.0),
            market=m,
            chain=_chain(contracts=[_good_call(strike=500.0)]),
            quote_freshness_threshold_seconds=15,
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        snap = out.context_snapshot_used
        self.assertEqual(snap.quote_timestamp_used, qt)
        self.assertEqual(snap.quote_age_seconds, 3.5)
        self.assertEqual(snap.quote_freshness_threshold_seconds, 15)
        self.assertIs(snap.quote_stale, False)
        self.assertTrue(snap.market_ready)

    def test_prefers_intraday_dte_band_over_0dte_when_both_quality(self) -> None:
        """0DTE is out of the 2–5 entry band; a 2-calendar-DTE expiry must win when both are otherwise equal."""
        c_0dte = _good_call(strike=500.0, sym="SPY  260420C00500000", expiration_date="2026-04-20")
        c_2dte = _good_call(strike=500.0, sym="SPY  260422C00500000", expiration_date="2026-04-22")
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=510.0, vwap=505.0, orh=508.0, orl=502.0, atr=1.5, swing_h=506.0, swing_l=500.0),
            market=_market(),
            chain=_chain(
                contracts=[c_0dte, c_2dte],
                expiration_dates_found=["2026-04-20", "2026-04-22"],
                selected_expiration=None,
            ),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "candidate_call")
        self.assertEqual(out.contract_candidate.expiration_date, "2026-04-22")

    def test_no_trade_when_only_0dte_contracts(self) -> None:
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=510.0, vwap=505.0, orh=508.0, orl=502.0, atr=1.5, swing_h=506.0, swing_l=500.0),
            market=_market(),
            chain=_chain(
                contracts=[_good_call(strike=500.0, sym="SPY  260420C00500000", expiration_date="2026-04-20")],
                expiration_dates_found=["2026-04-20"],
                selected_expiration=None,
            ),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "no_trade")
        self.assertIn("no_acceptable_option_contract_in_intraday_dte_band_2_5", out.blockers)

    def test_no_trade_when_only_swing_dte_contracts(self) -> None:
        """7 calendar DTE is outside intraday entry band; swing band is not used at evaluator entry selection."""
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=510.0, vwap=505.0, orh=508.0, orl=502.0, atr=1.5, swing_h=506.0, swing_l=500.0),
            market=_market(),
            chain=_chain(
                contracts=[_good_call(strike=500.0, sym="SPY  260427C00500000", expiration_date="2026-04-27")],
                expiration_dates_found=["2026-04-27"],
                selected_expiration=None,
            ),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "no_trade")
        self.assertIn("no_acceptable_option_contract_in_intraday_dte_band_2_5", out.blockers)

    def test_nearest_strike_among_multiple_intraday_band_expiries(self) -> None:
        """After DTE filter, nearest strike to reference wins (two different in-band expiries)."""
        c_a = _good_call(strike=498.0, sym="SPY  260422C00498000", expiration_date="2026-04-22")
        c_b = _good_call(strike=500.5, sym="SPY  260423C00500500", expiration_date="2026-04-23")
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=511.0, vwap=505.0, orh=508.0, orl=502.0, atr=1.5, swing_h=506.0, swing_l=500.0),
            market=_market(),
            chain=_chain(
                contracts=[c_a, c_b],
                expiration_dates_found=["2026-04-22", "2026-04-23"],
                selected_expiration=None,
                ref=500.0,
            ),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "candidate_call")
        self.assertEqual(out.contract_candidate.strike, 500.5)
        self.assertEqual(out.contract_candidate.expiration_date, "2026-04-23")

    def test_quality_filter_can_exclude_only_in_band_contract(self) -> None:
        """In-band expiry with bad spread is excluded; 0DTE good row does not satisfy DTE — fail closed."""
        bad_in_band = NearAtmContract(
            option_symbol="SPY  260422C00500000",
            strike=500.0,
            option_type="call",
            expiration_date="2026-04-22",
            bid=0.01,
            ask=5.0,
            mid=2.5,
            spread_percent=199.0,
            is_call=True,
            is_put=False,
        )
        good_0dte = _good_call(strike=500.0, sym="SPY  260420C00500000", expiration_date="2026-04-20")
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=510.0, vwap=505.0, orh=508.0, orl=502.0, atr=1.5, swing_h=506.0, swing_l=500.0),
            market=_market(),
            chain=_chain(contracts=[bad_in_band, good_0dte], selected_expiration=None),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "no_trade")
        self.assertIn("no_acceptable_option_contract_in_intraday_dte_band_2_5", out.blockers)
        self.assertIsNotNone(out.diagnostics)
        self.assertEqual(out.diagnostics.primary_failed_gate, "contract_selected")
        self.assertFalse(out.diagnostics.gate_pass["contract_selected"])

    def test_diagnostics_context_gate_failure(self) -> None:
        inp = StrategyOneEvalInput.from_api(
            status=_status(live=False, block="market_closed"),
            summary=_summary(px=510.0, vwap=505.0, orh=508.0, orl=502.0, atr=1.5, swing_h=506.0, swing_l=500.0),
            market=_market(),
            chain=_chain(contracts=[_good_call()]),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "no_trade")
        self.assertIsNotNone(out.diagnostics)
        self.assertEqual(out.diagnostics.primary_failed_gate, "context_live_ready")
        self.assertIn("context not ready", (out.diagnostics.explanation or "").lower())

    def test_diagnostics_include_chop_near_miss_values(self) -> None:
        inp = StrategyOneEvalInput.from_api(
            status=_status(),
            summary=_summary(px=500.1, vwap=500.0, orh=510.0, orl=490.0, atr=2.0, swing_h=515.0, swing_l=485.0),
            market=_market(),
            chain=_chain(contracts=[_good_call()]),
        )
        out = evaluate_strategy_one_spy(inp, now=EVAL_CLOCK)
        self.assertEqual(out.decision, "no_trade")
        self.assertIsNotNone(out.diagnostics)
        self.assertEqual(out.diagnostics.primary_failed_gate, "outside_chop_zone")
        self.assertIn("abs_price_minus_vwap", out.diagnostics.near_miss)
        self.assertIn("chop_band_threshold", out.diagnostics.near_miss)


if __name__ == "__main__":
    unittest.main()
