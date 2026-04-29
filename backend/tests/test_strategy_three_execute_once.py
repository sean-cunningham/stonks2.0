from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.core.config import Settings
from app.models.trade import PaperTrade
from app.schemas.market import ChainLatestResponse, MarketStatusResponse
from app.schemas.paper_trade import PaperTradeResponse
from app.schemas.strategy import (
    StrategyOneContextSnapshot,
    StrategyOneEvaluationDiagnostics,
    StrategyOneEvaluationResponse,
)
from app.services.paper.paper_trade_service import PaperTradeError
from app.services.paper.strategy_three_execute_once import run_strategy_three_paper_entry_once
from app.services.paper.strategy_three_paper_trade_service import StrategyThreePaperTradeService


def _mkt() -> MarketStatusResponse:
    return MarketStatusResponse(
        symbol="SPY",
        market_ready=True,
        block_reason="none",
        quote_available=True,
        chain_available=True,
        quote_age_seconds=1.0,
        chain_age_seconds=1.0,
        quote_is_fresh=True,
        chain_is_fresh=True,
        latest_quote_time=datetime.now(timezone.utc),
        latest_chain_time=datetime.now(timezone.utc),
        source_status="ok",
    )


def _chain() -> ChainLatestResponse:
    return ChainLatestResponse(
        underlying_symbol="SPY",
        available=True,
        snapshot_timestamp=datetime.now(timezone.utc),
        option_quotes_available=True,
        near_atm_contracts=[],
        source_status="ok",
    )


def _snap() -> StrategyOneContextSnapshot:
    return StrategyOneContextSnapshot(
        us_equity_rth_open=True,
        context_ready_for_live_trading=True,
        context_block_reason="none",
        market_ready=True,
        market_block_reason="none",
        chain_available=True,
        chain_option_quotes_available=True,
    )


def _candidate_eval() -> StrategyOneEvaluationResponse:
    return StrategyOneEvaluationResponse(
        decision="candidate_call",
        blockers=[],
        reasons=["setup_type:call_micro_breakout"],
        context_snapshot_used=_snap(),
        evaluation_timestamp=datetime.now(timezone.utc),
        diagnostics=StrategyOneEvaluationDiagnostics(gate_pass={"contract_selected": True}),
    )


def _paper_trade_response_open(trade_id: int) -> PaperTradeResponse:
    t = datetime.now(timezone.utc)
    return PaperTradeResponse(
        id=trade_id,
        strategy_id=StrategyThreePaperTradeService.STRATEGY_ID,
        symbol="SPY",
        option_symbol="SPY  260428C00500000",
        side="long",
        quantity=1,
        status="open",
        entry_time=t,
        entry_price=1.2,
        entry_decision="candidate_call",
        entry_reference_basis="option_ask",
        entry_evaluation_fingerprint="test",
        exit_policy={},
        sizing_policy={},
    )


class StrategyThreeExecuteOnceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = MagicMock()
        self.context = MagicMock()
        self.market = MagicMock()
        self.settings = Settings(APP_MODE="paper")

    def test_open_position_overlap_is_skipped(self) -> None:
        repo_inst = MagicMock()
        repo_inst.list_open.return_value = [MagicMock()]
        with patch("app.services.paper.strategy_three_execute_once.PaperTradeRepository", return_value=repo_inst):
            out = run_strategy_three_paper_entry_once(
                self.db,
                context=self.context,
                market=self.market,
                settings=self.settings,
            )
        self.assertEqual(out.cycle_action, "no_action")
        self.assertIn("open_position_exists_entry_skipped", out.notes)

    def test_cooldown_after_close_is_enforced(self) -> None:
        repo_inst = MagicMock()
        repo_inst.list_open.return_value = []
        closed = MagicMock()
        closed.entry_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        closed.exit_time = datetime.now(timezone.utc) - timedelta(minutes=1)
        repo_inst.list_closed_chronological.return_value = [closed]
        with patch("app.services.paper.strategy_three_execute_once.PaperTradeRepository", return_value=repo_inst):
            out = run_strategy_three_paper_entry_once(
                self.db,
                context=self.context,
                market=self.market,
                settings=self.settings,
            )
        self.assertEqual(out.cycle_action, "no_action")
        self.assertIn("cooldown_after_close_active", out.notes)

    def test_max_trades_per_day_is_enforced(self) -> None:
        repo_inst = MagicMock()
        repo_inst.list_open.return_value = []
        rows = []
        for _ in range(5):
            r = MagicMock()
            r.entry_time = datetime.now(timezone.utc) - timedelta(hours=1)
            r.exit_time = datetime.now(timezone.utc) - timedelta(minutes=20)
            rows.append(r)
        repo_inst.list_closed_chronological.return_value = rows
        with patch("app.services.paper.strategy_three_execute_once.PaperTradeRepository", return_value=repo_inst):
            out = run_strategy_three_paper_entry_once(
                self.db,
                context=self.context,
                market=self.market,
                settings=self.settings,
            )
        self.assertEqual(out.cycle_action, "no_action")
        self.assertIn("risk_limit_max_trades_per_day_reached", out.notes)

    def test_entry_position_cost_filter_is_enforced(self) -> None:
        repo_inst = MagicMock()
        repo_inst.list_open.return_value = []
        repo_inst.list_closed_chronological.return_value = []
        opened = MagicMock(spec=PaperTrade)
        opened.id = 42
        with (
            patch("app.services.paper.strategy_three_execute_once.PaperTradeRepository", return_value=repo_inst),
            patch(
                "app.services.paper.strategy_three_execute_once.build_strategy_three_evaluation_bundle",
                return_value=(_candidate_eval(), _mkt(), _chain()),
            ),
            patch.object(
                StrategyThreePaperTradeService,
                "open_position",
                side_effect=PaperTradeError("paper_entry_exceeds_max_position_cost"),
            ),
            patch(
                "app.services.paper.strategy_three_execute_once.PaperTradeResponse.model_validate",
                return_value=_paper_trade_response_open(42),
            ),
        ):
            out = run_strategy_three_paper_entry_once(
                self.db,
                context=self.context,
                market=self.market,
                settings=self.settings,
            )
        self.assertEqual(out.cycle_action, "no_action")
        self.assertTrue(any(n.startswith("auto_open_failed:paper_entry_exceeds_max_position_cost") for n in out.notes))
