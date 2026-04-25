from __future__ import annotations

import unittest
from unittest.mock import patch

from app.core.config import Settings
from app.jobs.strategy_two_runtime_scheduler import StrategyTwoRuntimeScheduler


class StrategyTwoRuntimeSchedulerTests(unittest.TestCase):
    def test_scheduler_disabled_by_default(self) -> None:
        settings = Settings(APP_MODE="paper")
        self.assertFalse(settings.STRATEGY2_PAPER_RUNTIME_ENABLED)
        scheduler = StrategyTwoRuntimeScheduler(settings)
        with patch("app.jobs.strategy_two_runtime_scheduler.threading.Thread") as thread_mock:
            scheduler.start()
        thread_mock.assert_not_called()

    def test_scheduler_starts_thread_when_enabled(self) -> None:
        settings = Settings(APP_MODE="paper", STRATEGY2_PAPER_RUNTIME_ENABLED=True)
        scheduler = StrategyTwoRuntimeScheduler(settings)
        with patch("app.jobs.strategy_two_runtime_scheduler.threading.Thread") as thread_mock:
            thread_inst = thread_mock.return_value
            scheduler.start()
            thread_mock.assert_called_once()
            thread_inst.start.assert_called_once()

