from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.models.trade import PaperTrade
from app.services.paper.strategy_dashboard_service import (
    closed_trade_purchase_and_sale_usd,
    compute_headline_metrics,
)


def _closed_trade(pnl: float) -> PaperTrade:
    now = datetime.now(timezone.utc)
    return PaperTrade(
        id=1,
        strategy_id="strategy_1_spy",
        symbol="SPY",
        option_symbol="SPY  251219C00600000",
        side="long",
        quantity=1,
        entry_time=now,
        entry_price=1.0,
        exit_time=now,
        exit_price=1.1,
        realized_pnl=pnl,
        status="closed",
        entry_decision="candidate_call",
        evaluation_snapshot_json={},
        entry_reference_basis="option_ask",
        exit_reference_basis="option_bid",
        exit_reason="x",
        entry_evaluation_fingerprint="fp",
    )


class StrategyDashboardMetricsTests(unittest.TestCase):
    def test_metrics_mixed_wins_losses(self) -> None:
        rows = [_closed_trade(100.0), _closed_trade(-40.0), _closed_trade(20.0)]
        m = compute_headline_metrics(closed=rows, unrealized_pnl=10.0, open_count=1)
        self.assertEqual(m.realized_pnl, 80.0)
        self.assertEqual(m.unrealized_pnl, 10.0)
        self.assertEqual(m.total_pnl, 90.0)
        self.assertEqual(m.trade_count, 3)
        self.assertAlmostEqual(m.win_rate or 0.0, 2 / 3, places=6)
        self.assertEqual(m.avg_win, 60.0)
        self.assertEqual(m.avg_loss, -40.0)
        self.assertAlmostEqual(m.expectancy or 0.0, 80.0 / 3, places=6)
        self.assertEqual(m.open_position_count, 1)

    def test_metrics_no_closed_trades(self) -> None:
        m = compute_headline_metrics(closed=[], unrealized_pnl=0.0, open_count=0)
        self.assertEqual(m.trade_count, 0)
        self.assertIsNone(m.win_rate)
        self.assertIsNone(m.avg_win)
        self.assertIsNone(m.avg_loss)
        self.assertIsNone(m.expectancy)

    def test_closed_trade_purchase_and_sale_usd(self) -> None:
        row = _closed_trade(10.0)
        purchase, sale = closed_trade_purchase_and_sale_usd(row)
        self.assertAlmostEqual(purchase or 0.0, 100.0)
        self.assertAlmostEqual(sale or 0.0, 110.0)
