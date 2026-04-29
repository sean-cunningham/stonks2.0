from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.schemas.bars import BarRow
from app.schemas.context import ContextStatusResponse, ContextSummaryResponse
from app.schemas.market import ChainLatestResponse, MarketStatusResponse, NearAtmContract
from app.services.market.spy_quote_buffer import get_spy_quote_buffer
from app.services.strategy.strategy_two_spy_0dte_vol_sniper import StrategyTwoEvalInput, evaluate_strategy_two_spy_0dte_vol_sniper


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
        bars_source="tastytrade_dxlink_candle",
    )


def _summary() -> ContextSummaryResponse:
    return ContextSummaryResponse(
        symbol="SPY",
        us_equity_rth_open=True,
        context_ready_for_live_trading=True,
        context_ready_for_analysis=True,
        latest_price=500.30,
        session_vwap=500.0,
        opening_range_high=500.40,
        opening_range_low=499.70,
        latest_5m_atr=1.0,
        recent_swing_high=500.35,
        recent_swing_low=499.60,
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


def _bars(speed: bool = True, volume_ok: bool = True) -> list[BarRow]:
    now = datetime.now(timezone.utc)
    bars: list[BarRow] = []
    for i in range(21):
        bt = now - timedelta(minutes=20 - i)
        vol = 1000.0
        open_px = 500.0
        close_px = 500.01
        high_px = 500.10
        low_px = 499.95
        if i == 20:
            if speed:
                open_px = 500.0
                close_px = 500.5  # 0.1%
                high_px = 500.8
                low_px = 500.1
            if volume_ok:
                vol = 1800.0
        bars.append(
            BarRow(
                symbol="SPY",
                timeframe="1m",
                bar_time=bt,
                open=open_px,
                high=high_px,
                low=low_px,
                close=close_px,
                volume=vol,
                source_status="ok",
            )
        )
    return bars


def _chain(today_exp: str, spread_wide: bool = False) -> ChainLatestResponse:
    ask = 1.00
    bid = 0.80 if spread_wide else 0.96
    c = NearAtmContract(
        option_symbol="SPY  260425C00500000",
        strike=500.0,
        option_type="call",
        expiration_date=today_exp,
        bid=bid,
        ask=ask,
        mid=(bid + ask) / 2.0,
        spread_percent=((ask - bid) / ((ask + bid) / 2.0)) * 100.0,
        is_call=True,
        is_put=False,
    )
    return ChainLatestResponse(
        underlying_symbol="SPY",
        available=True,
        snapshot_timestamp=datetime.now(timezone.utc),
        expiration_dates_found=[today_exp],
        selected_expiration=today_exp,
        underlying_reference_price=500.0,
        total_contracts_seen=1,
        option_quotes_available=True,
        near_atm_contracts=[c],
        source_status="ok",
    )


class StrategyTwoEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        get_spy_quote_buffer()._samples.clear()  # noqa: SLF001 - test isolation

    def test_returns_candidate_when_trigger_speed_volume_and_quality_pass(self) -> None:
        today = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()
        inp = StrategyTwoEvalInput.from_api(
            status=_status(),
            summary=_summary(),
            market=_market(),
            chain=_chain(today),
            bars_1m=_bars(speed=True, volume_ok=True),
        )
        with patch("app.services.strategy.strategy_two_spy_0dte_vol_sniper._is_within_entry_window", return_value=True):
            out = evaluate_strategy_two_spy_0dte_vol_sniper(inp)
        self.assertIn(out.decision, ("candidate_call", "candidate_put"))
        self.assertEqual(out.blockers, [])
        self.assertTrue(out.diagnostics is not None and out.diagnostics.gate_pass.get("setup_type_detected"))

    def test_returns_no_trade_when_speed_or_volume_filters_fail(self) -> None:
        today = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()
        inp = StrategyTwoEvalInput.from_api(
            status=_status(),
            summary=_summary(),
            market=_market(),
            chain=_chain(today),
            bars_1m=_bars(speed=False, volume_ok=False),
        )
        with patch("app.services.strategy.strategy_two_spy_0dte_vol_sniper._is_within_entry_window", return_value=True):
            out = evaluate_strategy_two_spy_0dte_vol_sniper(inp)
        self.assertEqual(out.decision, "no_trade")

    def test_blocks_outside_entry_windows(self) -> None:
        today = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()
        inp = StrategyTwoEvalInput.from_api(
            status=_status(),
            summary=_summary(),
            market=_market(),
            chain=_chain(today),
            bars_1m=_bars(),
        )
        with patch("app.services.strategy.strategy_two_spy_0dte_vol_sniper._is_within_entry_window", return_value=False):
            out = evaluate_strategy_two_spy_0dte_vol_sniper(inp)
        self.assertEqual(out.decision, "no_trade")
        self.assertTrue(any("outside_strategy_2_entry_window" in b for b in out.blockers))

    def test_rejects_wide_spreads(self) -> None:
        today = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()
        inp = StrategyTwoEvalInput.from_api(
            status=_status(),
            summary=_summary(),
            market=_market(),
            chain=_chain(today, spread_wide=True),
            bars_1m=_bars(),
        )
        with patch("app.services.strategy.strategy_two_spy_0dte_vol_sniper._is_within_entry_window", return_value=True):
            out = evaluate_strategy_two_spy_0dte_vol_sniper(inp)
        self.assertEqual(out.decision, "no_trade")

    def test_rejects_non_0dte_contracts(self) -> None:
        non_0dte = (datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date() + timedelta(days=1)).isoformat()
        inp = StrategyTwoEvalInput.from_api(
            status=_status(),
            summary=_summary(),
            market=_market(),
            chain=_chain(non_0dte),
            bars_1m=_bars(),
        )
        with patch("app.services.strategy.strategy_two_spy_0dte_vol_sniper._is_within_entry_window", return_value=True):
            out = evaluate_strategy_two_spy_0dte_vol_sniper(inp)
        self.assertEqual(out.decision, "no_trade")

    def test_evaluation_includes_micro_diagnostics_when_buffer_has_data(self) -> None:
        now = datetime.now(timezone.utc)
        buffer = get_spy_quote_buffer()
        buffer.append(timestamp=now - timedelta(seconds=35), price=500.00, source="quote_mid")
        buffer.append(timestamp=now - timedelta(seconds=20), price=500.15, source="quote_mid")
        buffer.append(timestamp=now, price=500.30, source="quote_mid")

        today = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()
        inp = StrategyTwoEvalInput.from_api(
            status=_status(),
            summary=_summary(),
            market=_market(),
            chain=_chain(today),
            bars_1m=_bars(speed=False, volume_ok=False),
        )
        with patch("app.services.strategy.strategy_two_spy_0dte_vol_sniper._is_within_entry_window", return_value=True):
            out = evaluate_strategy_two_spy_0dte_vol_sniper(inp)

        self.assertEqual(out.decision, "no_trade")
        self.assertIsNotNone(out.diagnostics)
        near_miss = (out.diagnostics.near_miss if out.diagnostics else {}) or {}
        self.assertIn("micro_latest_price", near_miss)
        self.assertIn("micro_sample_count", near_miss)
        self.assertIn("micro_price_change_15s", near_miss)
        self.assertIn("micro_price_change_30s", near_miss)
        self.assertIn("micro_abs_price_change_15s", near_miss)
        self.assertIn("micro_abs_price_change_30s", near_miss)
        self.assertIn("micro_atr_fraction_30s", near_miss)
        self.assertIn("micro_data_available_15s", near_miss)
        self.assertIn("micro_data_available_30s", near_miss)

