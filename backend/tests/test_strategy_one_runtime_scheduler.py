from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.core.config import Settings
from app.jobs.strategy_one_runtime_scheduler import StrategyOneRuntimeScheduler, seconds_until_next_minute_offset


class StrategyOneRuntimeSchedulerTests(unittest.TestCase):
    def test_wait_until_next_offset_same_minute(self) -> None:
        now = datetime(2026, 1, 1, 12, 30, 1, tzinfo=timezone.utc)
        wait = seconds_until_next_minute_offset(now=now, offset_seconds=4)
        self.assertAlmostEqual(wait, 3.0, places=3)

    def test_wait_until_next_offset_next_minute(self) -> None:
        now = datetime(2026, 1, 1, 12, 30, 5, tzinfo=timezone.utc)
        wait = seconds_until_next_minute_offset(now=now, offset_seconds=4)
        self.assertAlmostEqual(wait, 59.0, places=3)

    def test_wait_until_next_offset_at_boundary_rolls_one_minute(self) -> None:
        now = datetime(2026, 1, 1, 12, 30, 4, tzinfo=timezone.utc)
        wait = seconds_until_next_minute_offset(now=now, offset_seconds=4)
        self.assertAlmostEqual(wait, 60.0, places=3)

    def test_wait_until_next_offset_before_boundary_microseconds(self) -> None:
        now = datetime(2026, 1, 1, 12, 30, 3, 500000, tzinfo=timezone.utc)
        wait = seconds_until_next_minute_offset(now=now, offset_seconds=4)
        self.assertAlmostEqual(wait, 0.5, places=3)

    def test_scheduler_disabled_by_default(self) -> None:
        s = Settings(APP_MODE="paper")
        self.assertFalse(s.STRATEGY1_PAPER_RUNTIME_ENABLED)
        sched = StrategyOneRuntimeScheduler(s)
        with patch("app.jobs.strategy_one_runtime_scheduler.threading.Thread") as thread_mock:
            sched.start()
        thread_mock.assert_not_called()
