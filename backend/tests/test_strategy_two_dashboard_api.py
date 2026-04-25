from __future__ import annotations

import unittest
from collections.abc import Generator
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.paper_strategy_two import router as paper_router
from app.core.config import Settings
from app.core.database import Base, get_db
from app.schemas.strategy_dashboard import (
    StrategyControlsView,
    StrategyDashboardResponse,
    StrategyHeadlineMetrics,
    StrategyIdentity,
    StrategyRuntimeView,
    StrategyTimeseries,
    TimeSeriesPoint,
)


class StrategyTwoDashboardApiTests(unittest.TestCase):
    def test_dashboard_route_returns_common_shape(self) -> None:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        def override_get_db() -> Generator:
            db = session_local()
            try:
                yield db
            finally:
                db.close()

        app = FastAPI()
        app.include_router(paper_router)
        app.dependency_overrides[get_db] = override_get_db

        now = datetime.now(timezone.utc)
        payload = StrategyDashboardResponse(
            as_of_timestamp=now,
            strategy=StrategyIdentity(
                strategy_id="strategy_2_spy_0dte_vol_sniper",
                strategy_name="SPY 0DTE Volatility Sniper",
                symbol_scope=["SPY"],
            ),
            runtime=StrategyRuntimeView(
                mode="paper",
                scheduler_enabled=False,
                paused=False,
                entry_enabled=True,
                exit_enabled=True,
                running=False,
                lock_scope="single_process_only",
            ),
            controls=StrategyControlsView(),
            headline_metrics=StrategyHeadlineMetrics(
                realized_pnl=0.0,
                unrealized_pnl=0.0,
                total_pnl=0.0,
                trade_count=0,
                win_rate=None,
                avg_win=None,
                avg_loss=None,
                expectancy=None,
                max_drawdown=None,
                open_position_count=0,
            ),
            timeseries=StrategyTimeseries(
                equity_or_value=[TimeSeriesPoint(timestamp=now, value=0.0)],
                realized_pnl_cumulative=[TimeSeriesPoint(timestamp=now, value=0.0)],
                drawdown=[],
                is_minimal_viable=True,
                limitations=["mvp"],
            ),
            strategy_details={"sniper_profile": "deterministic_0dte_volatility"},
        )

        with (
            patch("app.api.paper_strategy_two.get_settings", return_value=Settings(APP_MODE="paper")),
            patch("app.api.paper_strategy_two.build_strategy_two_dashboard", return_value=payload),
            patch("app.api.paper_strategy_two.get_context_service", return_value=MagicMock()),
            patch("app.api.paper_strategy_two.get_market_service", return_value=MagicMock()),
            TestClient(app) as client,
        ):
            resp = client.get("/paper/strategy/spy/strategy-2/dashboard")
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()
        self.assertIn("as_of_timestamp", body)
        self.assertIn("strategy", body)
        self.assertIn("runtime", body)
        self.assertIn("headline_metrics", body)
        self.assertIn("open_positions", body)
        self.assertIn("recent_closed_trades", body)
        self.assertIn("recent_cycle_history", body)
        self.assertIn("timeseries", body)
        self.assertIn("strategy_details", body)

