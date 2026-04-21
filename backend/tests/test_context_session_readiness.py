from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.models.bars import IntradayBar
from app.services.broker.dxlink_spy_candle_streamer import CANDLE_PARSER_MODE, DxLinkHealthSnapshot
from app.services.market.context_status import evaluate_context_readiness


def _dxlink_health(*, connected: bool = True, subscribed: bool = True) -> DxLinkHealthSnapshot:
    return DxLinkHealthSnapshot(
        connected=connected,
        subscribed=subscribed,
        last_message_time=None,
        last_candle_time=None,
        quote_token_present=True,
        dxlink_url_present=True,
        reconnect_count=0,
        source_status="ok" if connected and subscribed else "degraded",
        last_error=None if connected and subscribed else "test",
        subscribed_symbol="SPY{=1m,tho=true}",
        event_type="Candle",
        parser_mode=CANDLE_PARSER_MODE,
        latest_raw_period_time=None,
        latest_raw_event_time=None,
        latest_raw_close=None,
        latest_persisted_1m_bar_time=None,
        latest_persisted_1m_close=None,
    )


def _bar(symbol: str, timeframe: str, t: datetime, px: float) -> IntradayBar:
    return IntradayBar(
        symbol=symbol,
        timeframe=timeframe,
        bar_time=t,
        open=px,
        high=px + 0.12,
        low=px - 0.12,
        close=px + 0.03,
        volume=1000.0,
        source_status="tastytrade_dxlink_candle",
    )


def _session_bars_for_day(day: datetime) -> tuple[list[IntradayBar], list[IntradayBar]]:
    """
    Build one full RTH SPY session in UTC (13:30..19:59 for EDT dates used in tests).
    """
    start = day.replace(hour=13, minute=30, second=0, microsecond=0, tzinfo=timezone.utc)
    bars_1m: list[IntradayBar] = []
    bars_5m: list[IntradayBar] = []

    for i in range(390):
        t = start + timedelta(minutes=i)
        base = 700.0 + math.sin(i / 6.0) * 0.7
        bars_1m.append(_bar("SPY", "1m", t, base))

    for j in range(78):
        t = start + timedelta(minutes=5 * j)
        base = 700.2 + math.sin(j / 2.0) * 0.8
        bars_5m.append(_bar("SPY", "5m", t, base))

    return bars_1m, bars_5m


class ContextSessionReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings()

    def test_rth_fresh_current_session_bars_ready_for_live_and_analysis(self) -> None:
        now = datetime(2026, 4, 21, 18, 0, 0, tzinfo=timezone.utc)  # 14:00 ET
        b1, b5 = _session_bars_for_day(datetime(2026, 4, 21, tzinfo=timezone.utc))
        b1 = [x for x in b1 if x.bar_time <= now - timedelta(minutes=1)]
        b5 = [x for x in b5 if x.bar_time <= now - timedelta(minutes=5)]

        out = evaluate_context_readiness(
            bars_1m=b1,
            bars_5m=b5,
            settings=self.settings,
            dxlink=_dxlink_health(),
            now=now,
        )
        self.assertTrue(out.us_equity_rth_open)
        self.assertTrue(out.context_ready_for_live_trading)
        self.assertTrue(out.context_ready_for_analysis)
        self.assertEqual(out.block_reason, "none")
        self.assertEqual(out.block_reason_analysis, "none")

    def test_rth_stale_bars_block_live_and_analysis(self) -> None:
        now = datetime(2026, 4, 21, 18, 0, 0, tzinfo=timezone.utc)  # 14:00 ET
        b1, b5 = _session_bars_for_day(datetime(2026, 4, 20, tzinfo=timezone.utc))

        out = evaluate_context_readiness(
            bars_1m=b1,
            bars_5m=b5,
            settings=self.settings,
            dxlink=_dxlink_health(),
            now=now,
        )
        self.assertTrue(out.us_equity_rth_open)
        self.assertFalse(out.context_ready_for_live_trading)
        self.assertFalse(out.context_ready_for_analysis)
        self.assertEqual(out.block_reason, "stale_1m_bars")
        self.assertEqual(out.block_reason_analysis, "stale_1m_bars")

    def test_after_close_latest_completed_session_analysis_ready(self) -> None:
        now = datetime(2026, 4, 21, 22, 30, 0, tzinfo=timezone.utc)  # 18:30 ET
        b1, b5 = _session_bars_for_day(datetime(2026, 4, 21, tzinfo=timezone.utc))

        out = evaluate_context_readiness(
            bars_1m=b1,
            bars_5m=b5,
            settings=self.settings,
            dxlink=_dxlink_health(),
            now=now,
        )
        self.assertFalse(out.us_equity_rth_open)
        self.assertFalse(out.context_ready_for_live_trading)
        self.assertTrue(out.context_ready_for_analysis)
        self.assertEqual(out.block_reason, "market_closed")
        self.assertEqual(out.block_reason_analysis, "latest_session_complete")

    def test_premarket_prior_day_completed_session_analysis_ready(self) -> None:
        now = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)  # 08:00 ET
        b1, b5 = _session_bars_for_day(datetime(2026, 4, 21, tzinfo=timezone.utc))

        out = evaluate_context_readiness(
            bars_1m=b1,
            bars_5m=b5,
            settings=self.settings,
            dxlink=_dxlink_health(),
            now=now,
        )
        self.assertFalse(out.us_equity_rth_open)
        self.assertFalse(out.context_ready_for_live_trading)
        self.assertTrue(out.context_ready_for_analysis)
        self.assertEqual(out.block_reason, "market_closed")
        self.assertEqual(out.block_reason_analysis, "latest_session_complete")

    def test_premarket_with_older_session_fails_closed_for_analysis(self) -> None:
        now = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)  # 08:00 ET
        b1, b5 = _session_bars_for_day(datetime(2026, 4, 20, tzinfo=timezone.utc))

        out = evaluate_context_readiness(
            bars_1m=b1,
            bars_5m=b5,
            settings=self.settings,
            dxlink=_dxlink_health(),
            now=now,
        )
        self.assertFalse(out.us_equity_rth_open)
        self.assertFalse(out.context_ready_for_live_trading)
        self.assertFalse(out.context_ready_for_analysis)
        self.assertEqual(out.block_reason_analysis, "prior_session_data")

    def test_after_close_disconnected_stream_still_allows_analysis_from_persisted_session(self) -> None:
        now = datetime(2026, 4, 21, 22, 30, 0, tzinfo=timezone.utc)  # 18:30 ET
        b1, b5 = _session_bars_for_day(datetime(2026, 4, 21, tzinfo=timezone.utc))

        out = evaluate_context_readiness(
            bars_1m=b1,
            bars_5m=b5,
            settings=self.settings,
            dxlink=_dxlink_health(connected=False, subscribed=False),
            now=now,
        )
        self.assertFalse(out.us_equity_rth_open)
        self.assertFalse(out.context_ready_for_live_trading)
        self.assertTrue(out.context_ready_for_analysis)
        self.assertEqual(out.block_reason, "market_closed")
        self.assertEqual(out.block_reason_analysis, "latest_session_complete")

    def test_rth_5m_freshness_uses_latest_completed_bucket_semantics(self) -> None:
        now = datetime(2026, 4, 21, 18, 3, 0, tzinfo=timezone.utc)  # 14:03 ET
        b1, b5 = _session_bars_for_day(datetime(2026, 4, 21, tzinfo=timezone.utc))
        b1 = [x for x in b1 if x.bar_time <= datetime(2026, 4, 21, 18, 2, 0, tzinfo=timezone.utc)]
        # Keep 5m up through 17:55 (latest completed bucket for latest_1m=18:02).
        b5 = [x for x in b5 if x.bar_time <= datetime(2026, 4, 21, 17, 55, 0, tzinfo=timezone.utc)]

        out = evaluate_context_readiness(
            bars_1m=b1,
            bars_5m=b5,
            settings=self.settings,
            dxlink=_dxlink_health(),
            now=now,
        )
        self.assertNotEqual(out.block_reason, "stale_5m_bars")

    def test_rth_lagging_5m_remains_stale(self) -> None:
        now = datetime(2026, 4, 21, 18, 3, 0, tzinfo=timezone.utc)  # 14:03 ET
        b1, b5 = _session_bars_for_day(datetime(2026, 4, 21, tzinfo=timezone.utc))
        b1 = [x for x in b1 if x.bar_time <= datetime(2026, 4, 21, 18, 2, 0, tzinfo=timezone.utc)]
        # Lag one extra bucket behind expected latest completed (17:50 only).
        b5 = [x for x in b5 if x.bar_time <= datetime(2026, 4, 21, 17, 50, 0, tzinfo=timezone.utc)]

        out = evaluate_context_readiness(
            bars_1m=b1,
            bars_5m=b5,
            settings=self.settings,
            dxlink=_dxlink_health(),
            now=now,
        )
        self.assertEqual(out.block_reason, "stale_5m_bars")
        self.assertEqual(out.block_reason_analysis, "stale_5m_bars")

    def test_rth_latest_1m_1525_and_latest_5m_1520_not_stale(self) -> None:
        now = datetime(2026, 4, 21, 15, 26, 0, tzinfo=timezone.utc)
        b1, b5 = _session_bars_for_day(datetime(2026, 4, 21, tzinfo=timezone.utc))
        b1 = [x for x in b1 if x.bar_time <= datetime(2026, 4, 21, 15, 25, 0, tzinfo=timezone.utc)]
        b5 = [x for x in b5 if x.bar_time <= datetime(2026, 4, 21, 15, 20, 0, tzinfo=timezone.utc)]

        out = evaluate_context_readiness(
            bars_1m=b1,
            bars_5m=b5,
            settings=self.settings,
            dxlink=_dxlink_health(),
            now=now,
        )
        self.assertNotEqual(out.block_reason, "stale_5m_bars")

    def test_rth_latest_1m_1529_and_latest_5m_1520_is_stale(self) -> None:
        now = datetime(2026, 4, 21, 15, 29, 30, tzinfo=timezone.utc)
        b1, b5 = _session_bars_for_day(datetime(2026, 4, 21, tzinfo=timezone.utc))
        b1 = [x for x in b1 if x.bar_time <= datetime(2026, 4, 21, 15, 29, 0, tzinfo=timezone.utc)]
        b5 = [x for x in b5 if x.bar_time <= datetime(2026, 4, 21, 15, 20, 0, tzinfo=timezone.utc)]

        out = evaluate_context_readiness(
            bars_1m=b1,
            bars_5m=b5,
            settings=self.settings,
            dxlink=_dxlink_health(),
            now=now,
        )
        self.assertEqual(out.block_reason, "stale_5m_bars")
        self.assertEqual(out.block_reason_analysis, "stale_5m_bars")

    def test_rth_latest_1m_1530_and_latest_5m_1525_not_stale(self) -> None:
        now = datetime(2026, 4, 21, 15, 30, 30, tzinfo=timezone.utc)
        b1, b5 = _session_bars_for_day(datetime(2026, 4, 21, tzinfo=timezone.utc))
        b1 = [x for x in b1 if x.bar_time <= datetime(2026, 4, 21, 15, 30, 0, tzinfo=timezone.utc)]
        b5 = [x for x in b5 if x.bar_time <= datetime(2026, 4, 21, 15, 25, 0, tzinfo=timezone.utc)]

        out = evaluate_context_readiness(
            bars_1m=b1,
            bars_5m=b5,
            settings=self.settings,
            dxlink=_dxlink_health(),
            now=now,
        )
        self.assertNotEqual(out.block_reason, "stale_5m_bars")

    def test_rth_latest_1m_1538_and_latest_5m_1530_not_stale(self) -> None:
        now = datetime(2026, 4, 21, 15, 38, 30, tzinfo=timezone.utc)
        b1, b5 = _session_bars_for_day(datetime(2026, 4, 21, tzinfo=timezone.utc))
        b1 = [x for x in b1 if x.bar_time <= datetime(2026, 4, 21, 15, 38, 0, tzinfo=timezone.utc)]
        b5 = [x for x in b5 if x.bar_time <= datetime(2026, 4, 21, 15, 30, 0, tzinfo=timezone.utc)]

        out = evaluate_context_readiness(
            bars_1m=b1,
            bars_5m=b5,
            settings=self.settings,
            dxlink=_dxlink_health(),
            now=now,
        )
        self.assertFalse(out.stale_5m_boolean)
        self.assertEqual(out.expected_latest_completed_5m_start, datetime(2026, 4, 21, 15, 30, 0, tzinfo=timezone.utc))
        self.assertNotEqual(out.block_reason, "stale_5m_bars")

    def test_rth_latest_1m_1553_and_latest_5m_1545_not_stale(self) -> None:
        now = datetime(2026, 4, 21, 15, 53, 30, tzinfo=timezone.utc)
        b1, b5 = _session_bars_for_day(datetime(2026, 4, 21, tzinfo=timezone.utc))
        b1 = [x for x in b1 if x.bar_time <= datetime(2026, 4, 21, 15, 53, 0, tzinfo=timezone.utc)]
        b5 = [x for x in b5 if x.bar_time <= datetime(2026, 4, 21, 15, 45, 0, tzinfo=timezone.utc)]

        out = evaluate_context_readiness(
            bars_1m=b1,
            bars_5m=b5,
            settings=self.settings,
            dxlink=_dxlink_health(),
            now=now,
        )
        self.assertFalse(out.stale_5m_boolean)
        self.assertEqual(out.expected_latest_completed_5m_start, datetime(2026, 4, 21, 15, 45, 0, tzinfo=timezone.utc))
        self.assertNotEqual(out.block_reason, "stale_5m_bars")


if __name__ == "__main__":
    unittest.main()

