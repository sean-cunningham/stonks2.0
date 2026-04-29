from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import unittest
from unittest.mock import Mock, patch

from app.core.config import Settings
from app.services.broker.dxlink_spy_candle_streamer import DxLinkSpyCandleStreamer
from app.services.broker.tastytrade_auth import TastytradeQuoteToken
from app.services.broker.tastytrade_market_data import MarketDataError, TastytradeMarketDataService, UnderlyingQuoteNormalized


class MarketDataAuthRecoveryTests(unittest.TestCase):
    def test_quote_fetch_with_auth_retry_requests_fresh_quote_token(self) -> None:
        auth = Mock()
        auth.get_access_token.return_value = Mock(access_token="a2")
        auth.get_quote_token.return_value = TastytradeQuoteToken(token="q2", dxlink_url="wss://new")
        service = TastytradeMarketDataService(settings=Settings(), auth_service=auth)
        with patch.object(
            service,
            "_fetch_quotes_via_dxlink",
            side_effect=[
                MarketDataError("dxlink_auth_session_not_found:Session not found: api"),
                {"SPY": {"bid": 500.0, "ask": 500.2}},
            ],
        ) as mocked_fetch:
            out = service._fetch_quotes_via_dxlink_with_auth_retry(
                dxlink_url="wss://old",
                quote_token="q1",
                symbols=["SPY"],
            )
        self.assertIn("SPY", out)
        self.assertEqual(mocked_fetch.call_count, 2)
        auth.get_access_token.assert_called_once()
        auth.get_quote_token.assert_called_once()

    def test_spy_quote_retries_once_after_auth_session_error(self) -> None:
        service = TastytradeMarketDataService(settings=Settings(), auth_service=Mock())
        ok_quote = UnderlyingQuoteNormalized(
            symbol="SPY",
            bid=500.0,
            ask=500.2,
            mid=500.1,
            last=500.1,
            quote_timestamp=datetime.now(timezone.utc),
            source_status="ok",
        )
        with patch.object(
            service,
            "_fetch_spy_quote_once",
            side_effect=[MarketDataError("dxlink_auth_session_not_found:Session not found: api"), ok_quote],
        ) as mocked:
            out = service.fetch_spy_quote()
        self.assertEqual(mocked.call_count, 2)
        self.assertIn("quote_token_refresh_succeeded", out.source_status)

    def test_spy_quote_retry_failure_reports_clear_diagnostic(self) -> None:
        service = TastytradeMarketDataService(settings=Settings(), auth_service=Mock())
        with patch.object(
            service,
            "_fetch_spy_quote_once",
            side_effect=[
                MarketDataError("dxlink_auth_session_not_found:Session not found: api"),
                MarketDataError("dxlink_auth_session_not_found:Session not found: api"),
            ],
        ):
            with self.assertRaises(MarketDataError) as ctx:
                service.fetch_spy_quote()
        self.assertIn("quote_token_refresh_attempted", str(ctx.exception))
        self.assertIn("dxlink_reconnect_failed", str(ctx.exception))


class CandleStreamerAuthRecoveryTests(unittest.TestCase):
    def test_auth_session_reason_detection(self) -> None:
        self.assertTrue(DxLinkSpyCandleStreamer._is_auth_session_not_found("Session not found: api"))
        self.assertFalse(DxLinkSpyCandleStreamer._is_auth_session_not_found("timeout"))

    def test_streamer_refreshes_quote_token_once_after_auth_session_error(self) -> None:
        settings = Settings()
        streamer = DxLinkSpyCandleStreamer(settings=settings)
        fake_auth = Mock()
        fake_auth.has_credentials.return_value = True
        fake_auth.get_access_token.side_effect = [Mock(access_token="a1"), Mock(access_token="a2")]
        fake_auth.get_quote_token.side_effect = [
            TastytradeQuoteToken(token="q1", dxlink_url="wss://x"),
            TastytradeQuoteToken(token="q2", dxlink_url="wss://x"),
        ]

        async def _fail_then_pass(*args, **kwargs):
            if not hasattr(_fail_then_pass, "called"):
                setattr(_fail_then_pass, "called", True)
                raise RuntimeError("dxlink_auth_session_not_found:Session not found: api")
            return None

        with patch("app.services.broker.dxlink_spy_candle_streamer.TastytradeAuthService", return_value=fake_auth):
            with patch.object(streamer, "_run_connected_session", side_effect=_fail_then_pass):
                asyncio.run(streamer._run_session_until_disconnect())

        snap = streamer.health_snapshot()
        self.assertTrue(snap.quote_token_refresh_attempted)
        self.assertTrue(snap.quote_token_refresh_succeeded)
        self.assertTrue(snap.dxlink_reconnect_after_auth_error)


if __name__ == "__main__":
    unittest.main()

