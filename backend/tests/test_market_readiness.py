"""Quote/chain readiness: wall-clock age vs thresholds and evaluation refresh path."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.core.config import Settings
from app.models.market import MarketSnapshot
from app.schemas.market import MarketStatusResponse
from app.services.market.market_status import compute_market_readiness
from app.services.market.market_store import MarketStoreService


def _snapshot(
    *,
    snapshot_time: datetime,
    chain_time: datetime | None,
    quote_ok: bool = True,
    chain_ok: bool = True,
    source: str = "ok",
) -> MarketSnapshot:
    return MarketSnapshot(
        symbol="SPY",
        snapshot_time=snapshot_time,
        chain_snapshot_time=chain_time,
        underlying_bid=500.0,
        underlying_ask=500.1,
        underlying_mid=500.05,
        underlying_last=500.05,
        quote_age_seconds=0.0,
        chain_age_seconds=0.0,
        chain_contract_count=10,
        expiration_dates_json=["2026-04-22"],
        nearest_expiration="2026-04-22",
        atm_reference_price=500.05,
        near_atm_contracts_json=[],
        is_data_fresh=False,
        data_source_status=source,
        raw_quote_available=quote_ok,
        raw_chain_available=chain_ok,
    )


class ComputeMarketReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            MARKET_QUOTE_MAX_AGE_SECONDS=15,
            MARKET_CHAIN_MAX_AGE_SECONDS=60,
        )

    def test_fresh_quote_and_chain_market_ready(self) -> None:
        now = datetime(2026, 4, 21, 17, 0, 0, tzinfo=timezone.utc)
        snap = _snapshot(
            snapshot_time=now - timedelta(seconds=5),
            chain_time=now - timedelta(seconds=10),
        )
        r = compute_market_readiness(snap, self.settings, now=now)
        self.assertTrue(r.market_ready)
        self.assertEqual(r.block_reason, "none")
        self.assertTrue(r.quote_is_fresh)
        self.assertTrue(r.chain_is_fresh)
        self.assertAlmostEqual(r.quote_age_seconds or 0, 5.0, places=3)

    def test_stale_quote_blocks_with_stale_quote(self) -> None:
        now = datetime(2026, 4, 21, 17, 0, 0, tzinfo=timezone.utc)
        snap = _snapshot(
            snapshot_time=now - timedelta(seconds=30),
            chain_time=now - timedelta(seconds=5),
        )
        r = compute_market_readiness(snap, self.settings, now=now)
        self.assertFalse(r.market_ready)
        self.assertEqual(r.block_reason, "stale_quote")
        self.assertFalse(r.quote_is_fresh)
        self.assertTrue(r.chain_is_fresh)

    def test_stale_chain_blocks_when_quote_fresh(self) -> None:
        now = datetime(2026, 4, 21, 17, 0, 0, tzinfo=timezone.utc)
        snap = _snapshot(
            snapshot_time=now - timedelta(seconds=5),
            chain_time=now - timedelta(seconds=90),
        )
        r = compute_market_readiness(snap, self.settings, now=now)
        self.assertFalse(r.market_ready)
        self.assertEqual(r.block_reason, "stale_chain")
        self.assertTrue(r.quote_is_fresh)
        self.assertFalse(r.chain_is_fresh)


class EvaluationMarketStatusRefreshTests(unittest.TestCase):
    def test_refreshes_once_when_stale_quote(self) -> None:
        stale = MarketStatusResponse(
            symbol="SPY",
            market_ready=False,
            block_reason="stale_quote",
            quote_available=True,
            chain_available=True,
            quote_age_seconds=99.0,
            chain_age_seconds=1.0,
            quote_is_fresh=False,
            chain_is_fresh=True,
            latest_quote_time=None,
            latest_chain_time=None,
            source_status="ok",
        )
        fresh = MarketStatusResponse(
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
        with patch.object(MarketStoreService, "get_spy_status", side_effect=[stale, fresh]):
            with patch.object(MarketStoreService, "refresh_spy") as mock_refresh:
                svc = MarketStoreService.__new__(MarketStoreService)  # type: ignore[misc]
                svc._db = MagicMock()
                out = MarketStoreService.get_spy_status_for_evaluation(svc)
        self.assertTrue(out.market_ready)
        mock_refresh.assert_called_once()
        svc._db.expire_all.assert_called_once()

    def test_no_refresh_when_already_ready(self) -> None:
        fresh = MarketStatusResponse(
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
        with patch.object(MarketStoreService, "get_spy_status", return_value=fresh):
            with patch.object(MarketStoreService, "refresh_spy") as mock_refresh:
                svc = MarketStoreService.__new__(MarketStoreService)  # type: ignore[misc]
                svc._db = MagicMock()
                out = MarketStoreService.get_spy_status_for_evaluation(svc)
        self.assertTrue(out.market_ready)
        mock_refresh.assert_not_called()

    def test_resolve_skips_refresh_when_not_stale_cache_blocker(self) -> None:
        """Credentials / broker blockers must not trigger a blind refresh."""
        blocked = MarketStatusResponse(
            symbol="SPY",
            market_ready=False,
            block_reason="missing_credentials",
            quote_available=False,
            chain_available=False,
            quote_age_seconds=None,
            chain_age_seconds=None,
            quote_is_fresh=False,
            chain_is_fresh=False,
            latest_quote_time=None,
            latest_chain_time=None,
            source_status="not_ready",
        )
        with patch.object(MarketStoreService, "get_spy_status", return_value=blocked):
            with patch.object(MarketStoreService, "refresh_spy") as mock_refresh:
                svc = MarketStoreService.__new__(MarketStoreService)  # type: ignore[misc]
                svc._db = MagicMock()
                res = MarketStoreService.resolve_spy_market_for_evaluation(svc)
        mock_refresh.assert_not_called()
        self.assertEqual(res.market_status_source, "cached")
        self.assertFalse(res.auto_refresh_attempted)
        self.assertIsNone(res.auto_refresh_trigger_reason)
        self.assertFalse(res.post_refresh_market_ready)
        self.assertEqual(res.post_refresh_block_reason, "missing_credentials")
