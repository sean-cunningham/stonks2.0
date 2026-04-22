from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.jobs.strategy_one_runtime_scheduler import seconds_until_next_minute_offset


class StrategyOneRuntimeSchedulerTests(unittest.TestCase):
    def test_wait_until_next_offset_same_minute(self) -> None:
        now = datetime(2026, 1, 1, 12, 30, 1, tzinfo=timezone.utc)
        wait = seconds_until_next_minute_offset(now=now, offset_seconds=4)
        self.assertAlmostEqual(wait, 3.0, places=3)

    def test_wait_until_next_offset_next_minute(self) -> None:
        now = datetime(2026, 1, 1, 12, 30, 5, tzinfo=timezone.utc)
        wait = seconds_until_next_minute_offset(now=now, offset_seconds=4)
        self.assertAlmostEqual(wait, 59.0, places=3)
