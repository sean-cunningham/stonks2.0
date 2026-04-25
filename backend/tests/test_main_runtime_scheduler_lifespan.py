from __future__ import annotations

import asyncio
import unittest
from unittest.mock import MagicMock, patch

from fastapi import FastAPI

from app.core.config import Settings
from app.main import lifespan


class MainLifespanRuntimeSchedulerTests(unittest.TestCase):
    def test_lifespan_starts_and_stops_scheduler_when_enabled(self) -> None:
        async def _run() -> None:
            scheduler_one_inst = MagicMock()
            scheduler_two_inst = MagicMock()
            streamer = MagicMock()
            settings = Settings(
                APP_MODE="paper",
                STRATEGY1_PAPER_RUNTIME_ENABLED=True,
                STRATEGY2_PAPER_RUNTIME_ENABLED=True,
            )
            with (
                patch("app.main.get_settings", return_value=settings),
                patch("app.main.Base.metadata.create_all"),
                patch("app.main.ensure_market_snapshot_schema"),
                patch("app.main.ensure_paper_trade_schema"),
                patch("app.main.ensure_paper_trade_open_contract_unique_index"),
                patch("app.main.delete_legacy_spy_intraday_bars", return_value=0),
                patch("app.main.check_database_connectivity", return_value=True),
                patch("app.main.run_startup_market_refresh"),
                patch("app.main.run_startup_context_refresh"),
                patch("app.main.get_spy_candle_streamer", return_value=streamer),
                patch("app.main.StrategyOneRuntimeScheduler", return_value=scheduler_one_inst),
                patch("app.main.StrategyTwoRuntimeScheduler", return_value=scheduler_two_inst),
            ):
                async with lifespan(FastAPI()):
                    scheduler_one_inst.start.assert_called_once()
                    scheduler_two_inst.start.assert_called_once()
                scheduler_one_inst.stop.assert_called_once()
                scheduler_two_inst.stop.assert_called_once()
                streamer.start.assert_called_once()
                streamer.stop.assert_called_once()

        asyncio.run(_run())
