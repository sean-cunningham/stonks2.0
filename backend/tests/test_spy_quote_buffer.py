from __future__ import annotations

import threading
import unittest
from datetime import datetime, timedelta, timezone

from app.services.market.spy_quote_buffer import SpyQuoteBuffer


class SpyQuoteBufferTests(unittest.TestCase):
    def test_append_and_latest(self) -> None:
        b = SpyQuoteBuffer(max_age_seconds=300)
        t = datetime.now(timezone.utc)
        b.append(timestamp=t, price=500.0, source="quote_mid")
        latest = b.get_latest()
        self.assertIsNotNone(latest)
        assert latest is not None
        self.assertEqual(latest.price, 500.0)
        self.assertEqual(latest.source, "quote_mid")

    def test_prunes_old_samples(self) -> None:
        b = SpyQuoteBuffer(max_age_seconds=300)
        now = datetime.now(timezone.utc)
        b.append(timestamp=now - timedelta(minutes=6), price=499.0, source="quote_mid")
        b.append(timestamp=now, price=500.0, source="quote_mid")
        snap = b.get_micro_snapshot()
        self.assertEqual(snap["sample_count"], 1)

    def test_get_delta_works_with_uneven_samples(self) -> None:
        b = SpyQuoteBuffer(max_age_seconds=300)
        t0 = datetime.now(timezone.utc)
        b.append(timestamp=t0 - timedelta(seconds=41), price=500.0, source="quote_mid")
        b.append(timestamp=t0 - timedelta(seconds=29), price=500.3, source="quote_mid")
        b.append(timestamp=t0 - timedelta(seconds=13), price=500.5, source="quote_mid")
        b.append(timestamp=t0, price=500.8, source="quote_mid")
        d30 = b.get_delta(30)
        d15 = b.get_delta(15)
        self.assertIsNotNone(d30)
        self.assertIsNotNone(d15)
        assert d30 is not None and d15 is not None
        self.assertAlmostEqual(d30, 0.8, places=6)  # anchor at -41s
        self.assertAlmostEqual(d15, 0.5, places=6)  # anchor at -29s

    def test_missing_data_flags_false(self) -> None:
        b = SpyQuoteBuffer(max_age_seconds=300)
        now = datetime.now(timezone.utc)
        b.append(timestamp=now, price=500.0, source="quote_mid")
        snap = b.get_micro_snapshot(atr_5m=1.0)
        self.assertFalse(bool(snap["data_available_15s"]))
        self.assertFalse(bool(snap["data_available_30s"]))
        self.assertIsNone(snap["price_change_15s"])
        self.assertIsNone(snap["price_change_30s"])

    def test_thread_safety_smoke(self) -> None:
        b = SpyQuoteBuffer(max_age_seconds=300)
        base = datetime.now(timezone.utc)

        def writer(offset: int) -> None:
            for i in range(50):
                b.append(
                    timestamp=base + timedelta(milliseconds=offset + i),
                    price=500.0 + (offset * 0.001) + (i * 0.0001),
                    source="quote_mid",
                )

        threads = [threading.Thread(target=writer, args=(k * 1000,)) for k in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        snap = b.get_micro_snapshot()
        self.assertGreaterEqual(int(snap["sample_count"]), 1)

