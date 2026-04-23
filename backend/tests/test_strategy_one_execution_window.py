"""US/Eastern RTH window for Strategy 1 scheduler (server TZ–independent)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.services.paper.strategy_one_execution_window import is_within_spy_rth_et


class StrategyOneExecutionWindowTests(unittest.TestCase):
    def test_weekday_inside_rth_mid_morning_et(self) -> None:
        # 2026-04-22 is Wednesday. 14:00 UTC ≈ 10:00 Eastern (EDT, UTC-4).
        clock = datetime(2026, 4, 22, 14, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(is_within_spy_rth_et(clock_utc=clock))

    def test_weekday_before_open_et(self) -> None:
        # 13:29 UTC ≈ 09:29 ET same day — before 9:30.
        clock = datetime(2026, 4, 22, 13, 29, 0, tzinfo=timezone.utc)
        self.assertFalse(is_within_spy_rth_et(clock_utc=clock))

    def test_weekday_at_open_boundary_inclusive(self) -> None:
        # 13:30 UTC ≈ 09:30 ET — first minute of RTH.
        clock = datetime(2026, 4, 22, 13, 30, 0, tzinfo=timezone.utc)
        self.assertTrue(is_within_spy_rth_et(clock_utc=clock))

    def test_weekday_at_close_boundary_exclusive(self) -> None:
        # 20:00 UTC ≈ 16:00 ET — end of session, outside half-open window.
        clock = datetime(2026, 4, 22, 20, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(is_within_spy_rth_et(clock_utc=clock))

    def test_weekday_evening_et(self) -> None:
        clock = datetime(2026, 4, 22, 21, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(is_within_spy_rth_et(clock_utc=clock))

    def test_saturday_midday_et(self) -> None:
        # 2026-04-25 is Saturday; 14:00 UTC ≈ 10:00 ET — still weekend.
        clock = datetime(2026, 4, 25, 14, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(is_within_spy_rth_et(clock_utc=clock))

    def test_naive_clock_raises(self) -> None:
        with self.assertRaises(ValueError):
            is_within_spy_rth_et(clock_utc=datetime(2026, 4, 22, 14, 0, 0))
