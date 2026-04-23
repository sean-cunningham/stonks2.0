from __future__ import annotations

import unittest
from datetime import datetime, timezone

from app.models.trade import PaperTrade
from app.services.paper.strategy_dashboard_service import build_mvp_timeseries, compute_max_drawdown_from_curve


def _closed_at(ts: datetime, pnl: float, idx: int) -> PaperTrade:
    return PaperTrade(
        id=idx,
        strategy_id="strategy_1_spy",
        symbol="SPY",
        option_symbol=f"SPY{idx}",
        side="long",
        quantity=1,
        entry_time=ts,
        entry_price=1.0,
        exit_time=ts,
        exit_price=1.0,
        realized_pnl=pnl,
        status="closed",
        entry_decision="candidate_call",
        evaluation_snapshot_json={},
        entry_reference_basis="option_ask",
        exit_reference_basis="option_bid",
        exit_reason="x",
        entry_evaluation_fingerprint="fp",
    )


class StrategyDashboardTimeseriesTests(unittest.TestCase):
    def test_mvp_series_closed_steps_plus_current_snapshot(self) -> None:
        t1 = datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 12, 2, tzinfo=timezone.utc)
        as_of = datetime(2026, 1, 1, 12, 3, tzinfo=timezone.utc)
        ts = build_mvp_timeseries(
            closed_chronological=[_closed_at(t1, 10.0, 1), _closed_at(t2, -3.0, 2)],
            current_unrealized_pnl=5.0,
            starting_cash=1000.0,
            current_cash=1007.0,
            as_of=as_of,
        )
        self.assertTrue(ts.is_minimal_viable)
        self.assertTrue(any("MVP estimate" in s for s in ts.limitations))
        self.assertEqual(ts.realized_pnl_cumulative[-1].value, 7.0)
        self.assertEqual(ts.equity_or_value[-1].timestamp, as_of)
        self.assertEqual(ts.equity_or_value[-1].value, 1012.0)
        self.assertEqual(ts.cash_over_time[-1].value, 1007.0)
        self.assertAlmostEqual(ts.equity_return_pct[-1].value, 1.2, places=6)

    def test_drawdown_from_curve(self) -> None:
        t1 = datetime(2026, 1, 1, 12, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 1, 12, 2, tzinfo=timezone.utc)
        t3 = datetime(2026, 1, 1, 12, 3, tzinfo=timezone.utc)
        from app.schemas.strategy_dashboard import TimeSeriesPoint

        dd = compute_max_drawdown_from_curve(
            [
                TimeSeriesPoint(timestamp=t1, value=10.0),
                TimeSeriesPoint(timestamp=t2, value=4.0),
                TimeSeriesPoint(timestamp=t3, value=9.0),
            ]
        )
        self.assertEqual(dd, -6.0)
