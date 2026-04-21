"""Strategy evaluation auto-refresh: stale DB snapshot -> refresh -> fresh market for evaluator."""

from __future__ import annotations

import unittest
from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.strategy_one import get_context_service, get_market_service, router as strategy_router
from app.core.config import Settings, get_settings
from app.core.database import Base
from app.models.market import MarketSnapshot
from app.repositories.market_repository import MarketRepository
from app.schemas.context import ContextStatusResponse, ContextSummaryResponse
from app.services.market.market_store import MarketStoreService
import app.models.bars  # noqa: F401 — register models on Base.metadata
import app.models.market  # noqa: F401

_NEAR_ATM_ROW = {
    "option_symbol": "SPY  260422C00500000",
    "strike": 500.0,
    "option_type": "call",
    "expiration_date": "2026-04-22",
    "bid": 2.0,
    "ask": 2.2,
    "mid": 2.1,
    "spread_percent": 9.52,
    "delta": 0.5,
    "is_call": True,
    "is_put": False,
}


def _stub_status() -> ContextStatusResponse:
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


def _stub_summary_chop() -> ContextSummaryResponse:
    """VWAP/ATR chop so decision stays no_trade without hitting market gate."""
    return ContextSummaryResponse(
        symbol="SPY",
        us_equity_rth_open=True,
        context_ready_for_live_trading=True,
        context_ready_for_analysis=True,
        latest_price=500.1,
        session_vwap=500.0,
        opening_range_high=510.0,
        opening_range_low=490.0,
        latest_5m_atr=2.0,
        recent_swing_high=515.0,
        recent_swing_low=485.0,
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


class StubContextService:
    def get_status(self) -> ContextStatusResponse:
        return _stub_status()

    def get_summary(self) -> ContextSummaryResponse:
        return _stub_summary_chop()


def _fake_refresh_spy(self: MarketStoreService) -> None:
    """Broker-free refresh: insert a fresh snapshot row (same contract as real refresh)."""
    now = datetime.now(timezone.utc)
    MarketRepository(self._db).upsert_latest_snapshot(
        symbol="SPY",
        snapshot_time=now,
        chain_snapshot_time=now,
        underlying_bid=500.0,
        underlying_ask=500.1,
        underlying_mid=500.05,
        underlying_last=500.05,
        quote_age_seconds=0.05,
        chain_age_seconds=0.05,
        chain_contract_count=1,
        expiration_dates_json=["2026-04-22"],
        nearest_expiration="2026-04-22",
        atm_reference_price=500.05,
        near_atm_contracts_json=[_NEAR_ATM_ROW],
        is_data_fresh=True,
        data_source_status="ok",
        raw_quote_available=True,
        raw_chain_available=True,
    )


class StrategyEvaluationMarketRefreshIntegrationTests(unittest.TestCase):
    def test_evaluation_triggers_refresh_and_drops_stale_quote_blocker(self) -> None:
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        old = datetime(2026, 4, 21, 14, 0, 0, tzinfo=timezone.utc)
        db_seed = SessionLocal()
        try:
            db_seed.add(
                MarketSnapshot(
                    symbol="SPY",
                    snapshot_time=old,
                    chain_snapshot_time=old,
                    underlying_bid=499.0,
                    underlying_ask=499.1,
                    underlying_mid=499.05,
                    underlying_last=499.05,
                    quote_age_seconds=999.0,
                    chain_age_seconds=999.0,
                    chain_contract_count=1,
                    expiration_dates_json=["2026-04-22"],
                    nearest_expiration="2026-04-22",
                    atm_reference_price=499.05,
                    near_atm_contracts_json=[_NEAR_ATM_ROW],
                    is_data_fresh=False,
                    data_source_status="ok",
                    raw_quote_available=True,
                    raw_chain_available=True,
                )
            )
            db_seed.commit()
        finally:
            db_seed.close()

        test_settings = Settings(
            MARKET_QUOTE_MAX_AGE_SECONDS=15,
            MARKET_CHAIN_MAX_AGE_SECONDS=60,
        )

        def override_market() -> Generator:
            db = SessionLocal()
            try:
                yield MarketStoreService(db=db, settings=test_settings)
            finally:
                db.close()

        app = FastAPI()
        app.include_router(strategy_router)
        app.dependency_overrides[get_settings] = lambda: test_settings
        app.dependency_overrides[get_context_service] = lambda: StubContextService()
        app.dependency_overrides[get_market_service] = override_market

        with patch.object(MarketStoreService, "refresh_spy", _fake_refresh_spy):
            with TestClient(app) as client:
                response = client.get("/strategy/spy/strategy-1/evaluation")

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        trace = data["market_evaluation_trace"]
        self.assertTrue(trace["auto_refresh_attempted"])
        self.assertEqual(trace["market_status_source"], "refreshed_for_evaluation")
        self.assertEqual(trace["auto_refresh_trigger_reason"], "stale_quote")
        self.assertTrue(trace["post_refresh_market_ready"])
        self.assertEqual(trace["post_refresh_block_reason"], "none")
        blockers = data["blockers"]
        self.assertFalse(any("stale_quote" in b for b in blockers))


if __name__ == "__main__":
    unittest.main()
