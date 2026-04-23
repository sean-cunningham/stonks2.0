from __future__ import annotations

import unittest

from app.services.paper.strategy_one_dashboard_service import _extract_affordability_details


class StrategyOneDashboardAffordabilityHelperTests(unittest.TestCase):
    def test_extract_affordability_details_from_notes(self) -> None:
        notes = (
            "auto_open_failed:paper_entry_premium_exceeds_risk_budget|"
            "affordability_diag:attempted_option_symbol=SPY  260422C00500000;"
            "attempted_ask=2.86;attempted_total_premium_usd=286.0;risk_budget_usd=100.0;"
            "max_affordable_premium_usd=285.7142857;premium_over_budget_usd=0.2857143"
        )
        out = _extract_affordability_details(notes)
        assert out is not None
        self.assertEqual(out["attempted_option_symbol"], "SPY  260422C00500000")
        self.assertEqual(out["attempted_ask"], "2.86")
        self.assertEqual(out["risk_budget_usd"], "100.0")

    def test_extract_affordability_details_none_when_missing(self) -> None:
        self.assertIsNone(_extract_affordability_details("auto_open_failed:duplicate_open_position"))

