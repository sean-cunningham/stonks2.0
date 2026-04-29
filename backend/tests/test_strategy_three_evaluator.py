from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.schemas.bars import BarRow
from app.schemas.context import ContextStatusResponse, ContextSummaryResponse
from app.schemas.market import ChainLatestResponse, MarketStatusResponse, NearAtmContract
from app.services.market.spy_quote_buffer import get_spy_quote_buffer
from app.services.strategy.strategy_three_spy_micro_impulse import (
    StrategyThreeEvalInput,
    evaluate_strategy_three_spy_micro_impulse,
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
        bars_source="tastytrade_dxlink_candle",
    )


def _summary(price: float = 500.30, *, near: bool = True) -> ContextSummaryResponse:
    return ContextSummaryResponse(
        symbol="SPY",
        us_equity_rth_open=True,
        context_ready_for_live_trading=True,
        context_ready_for_analysis=True,
        latest_price=price,
        session_vwap=500.0 if near else 497.0,
        opening_range_high=500.4 if near else 503.0,
        opening_range_low=499.7 if near else 497.0,
        latest_5m_atr=1.0,
        recent_swing_high=500.35 if near else 503.0,
        recent_swing_low=499.60 if near else 497.0,
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


def _bars() -> list[BarRow]:
    now = datetime.now(timezone.utc)
    return [
        BarRow(
            symbol="SPY",
            timeframe="1m",
            bar_time=now - timedelta(minutes=1),
            open=500.0,
            high=500.2,
            low=499.9,
            close=500.1,
            volume=1000.0,
            source_status="ok",
        )
    ]


def _chain(today_exp: str, *, spread_wide: bool = False) -> ChainLatestResponse:
    ask = 1.00
    bid = 0.80 if spread_wide else 0.96
    c_call = NearAtmContract(
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
    c_put = NearAtmContract(
        option_symbol="SPY  260425P00500000",
        strike=500.0,
        option_type="put",
        expiration_date=today_exp,
        bid=bid,
        ask=ask,
        mid=(bid + ask) / 2.0,
        spread_percent=((ask - bid) / ((ask + bid) / 2.0)) * 100.0,
        is_call=False,
        is_put=True,
    )
    return ChainLatestResponse(
        underlying_symbol="SPY",
        available=True,
        snapshot_timestamp=datetime.now(timezone.utc),
        expiration_dates_found=[today_exp],
        selected_expiration=today_exp,
        underlying_reference_price=500.0,
        total_contracts_seen=2,
        option_quotes_available=True,
        near_atm_contracts=[c_call, c_put],
        source_status="ok",
    )


class StrategyThreeEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        get_spy_quote_buffer()._samples.clear()  # noqa: SLF001

    def test_micro_data_unavailable_returns_no_trade(self) -> None:
        today = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()
        inp = StrategyThreeEvalInput.from_api(
            status=_status(),
            summary=_summary(),
            market=_market(),
            chain=_chain(today),
            bars_1m=_bars(),
        )
        out = evaluate_strategy_three_spy_micro_impulse(inp)
        self.assertEqual(out.decision, "no_trade")
        self.assertIn("micro_data_unavailable", out.blockers)

    def test_near_trigger_false_returns_no_trade(self) -> None:
        now = datetime.now(timezone.utc)
        buffer = get_spy_quote_buffer()
        buffer.append(timestamp=now - timedelta(seconds=40), price=500.0, source="quote_mid")
        buffer.append(timestamp=now - timedelta(seconds=20), price=500.25, source="quote_mid")
        buffer.append(timestamp=now, price=500.35, source="quote_mid")
        today = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        inp = StrategyThreeEvalInput.from_api(
            status=_status(),
            summary=_summary(price=500.35, near=False),
            market=_market(),
            chain=_chain(today),
            bars_1m=_bars(),
        )
        out = evaluate_strategy_three_spy_micro_impulse(inp)
        self.assertEqual(out.decision, "no_trade")
        self.assertIn("not_near_any_trigger_level", out.blockers)

    def test_micro_impulse_true_but_no_cross_returns_no_trade(self) -> None:
        now = datetime.now(timezone.utc)
        buffer = get_spy_quote_buffer()
        buffer.append(timestamp=now - timedelta(seconds=40), price=500.09, source="quote_mid")
        buffer.append(timestamp=now - timedelta(seconds=20), price=500.15, source="quote_mid")
        buffer.append(timestamp=now, price=500.39, source="quote_mid")
        today = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        inp = StrategyThreeEvalInput.from_api(
            status=_status(),
            summary=_summary(price=500.39),
            market=_market(),
            chain=_chain(today),
            bars_1m=_bars(),
        )
        out = evaluate_strategy_three_spy_micro_impulse(inp)
        self.assertEqual(out.decision, "no_trade")
        self.assertIn("micro_no_trigger_cross", out.blockers)

    def test_call_micro_breakout_produces_candidate_call(self) -> None:
        now = datetime.now(timezone.utc)
        buffer = get_spy_quote_buffer()
        buffer.append(timestamp=now - timedelta(seconds=40), price=500.10, source="quote_mid")
        buffer.append(timestamp=now - timedelta(seconds=20), price=500.20, source="quote_mid")
        buffer.append(timestamp=now, price=500.45, source="quote_mid")
        today = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        inp = StrategyThreeEvalInput.from_api(
            status=_status(),
            summary=_summary(price=500.45),
            market=_market(),
            chain=_chain(today),
            bars_1m=_bars(),
        )
        out = evaluate_strategy_three_spy_micro_impulse(inp)
        self.assertEqual(out.decision, "candidate_call")

    def test_put_micro_breakdown_produces_candidate_put(self) -> None:
        now = datetime.now(timezone.utc)
        buffer = get_spy_quote_buffer()
        buffer.append(timestamp=now - timedelta(seconds=40), price=499.95, source="quote_mid")
        buffer.append(timestamp=now - timedelta(seconds=20), price=499.80, source="quote_mid")
        buffer.append(timestamp=now, price=499.45, source="quote_mid")
        today = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        inp = StrategyThreeEvalInput.from_api(
            status=_status(),
            summary=_summary(price=499.45),
            market=_market(),
            chain=_chain(today),
            bars_1m=_bars(),
        )
        out = evaluate_strategy_three_spy_micro_impulse(inp)
        self.assertEqual(out.decision, "candidate_put")

    def test_rejects_non_0dte_contracts(self) -> None:
        now = datetime.now(timezone.utc)
        buffer = get_spy_quote_buffer()
        buffer.append(timestamp=now - timedelta(seconds=40), price=500.10, source="quote_mid")
        buffer.append(timestamp=now - timedelta(seconds=20), price=500.20, source="quote_mid")
        buffer.append(timestamp=now, price=500.45, source="quote_mid")
        non_0dte = (now.astimezone(ZoneInfo("America/New_York")).date() + timedelta(days=1)).isoformat()
        inp = StrategyThreeEvalInput.from_api(
            status=_status(),
            summary=_summary(price=500.45),
            market=_market(),
            chain=_chain(non_0dte),
            bars_1m=_bars(),
        )
        out = evaluate_strategy_three_spy_micro_impulse(inp)
        self.assertEqual(out.decision, "no_trade")
        self.assertIn("no_acceptable_option_contract_0dte", out.blockers)

    def test_rejects_wide_spreads(self) -> None:
        now = datetime.now(timezone.utc)
        buffer = get_spy_quote_buffer()
        buffer.append(timestamp=now - timedelta(seconds=40), price=500.10, source="quote_mid")
        buffer.append(timestamp=now - timedelta(seconds=20), price=500.20, source="quote_mid")
        buffer.append(timestamp=now, price=500.45, source="quote_mid")
        today = now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        inp = StrategyThreeEvalInput.from_api(
            status=_status(),
            summary=_summary(price=500.45),
            market=_market(),
            chain=_chain(today, spread_wide=True),
            bars_1m=_bars(),
        )
        out = evaluate_strategy_three_spy_micro_impulse(inp)
        self.assertEqual(out.decision, "no_trade")
        self.assertIn("no_acceptable_option_contract_0dte", out.blockers)
