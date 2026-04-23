"""Strategy 1 paper execute-once automation and emergency close."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.core.config import Settings
from app.models.trade import PaperTrade
from app.schemas.market import ChainLatestResponse, MarketStatusResponse
from app.schemas.paper_trade import PaperOpenPositionValuationResponse, PaperTradeResponse
from app.schemas.strategy import StrategyOneEvaluationResponse
from app.schemas.strategy_one_exit_evaluation import StrategyOneExitEvaluationResponse
from app.services.paper.paper_trade_service import PaperTradeError, PaperTradeService
from app.services.paper.strategy_one_execute_once import (
    require_acceptable_exit_quote_for_execution,
    run_emergency_close_open_paper_trade,
    run_strategy_one_paper_execute_once,
)


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


def _paper_trade_response_open(trade_id: int) -> PaperTradeResponse:
    t = datetime.now(timezone.utc)
    return PaperTradeResponse(
        id=trade_id,
        strategy_id=PaperTradeService.STRATEGY_ID,
        symbol="SPY",
        option_symbol="SPY  251219C00600000",
        side="long",
        quantity=1,
        status="open",
        entry_time=t,
        entry_price=1.5,
        entry_decision="candidate_call",
        entry_reference_basis="mid",
        entry_evaluation_fingerprint="test",
        exit_policy={},
        sizing_policy={},
    )


def _paper_trade_response_closed(trade_id: int) -> PaperTradeResponse:
    t = datetime.now(timezone.utc)
    return PaperTradeResponse(
        id=trade_id,
        strategy_id=PaperTradeService.STRATEGY_ID,
        symbol="SPY",
        option_symbol="SPY  251219C00600000",
        side="long",
        quantity=1,
        status="closed",
        entry_time=t,
        entry_price=1.5,
        entry_decision="candidate_call",
        entry_reference_basis="mid",
        entry_evaluation_fingerprint="test",
        exit_time=t,
        exit_price=1.25,
        exit_reference_basis="bid",
        exit_reason="strategy_1_auto_exit_close_now",
        realized_pnl=-0.25,
        exit_policy={},
        sizing_policy={},
    )


class RequireAcceptableExitQuoteTests(unittest.TestCase):
    def test_rejects_stale(self) -> None:
        v = PaperOpenPositionValuationResponse(
            paper_trade_id=1,
            option_symbol="X",
            side="long",
            quantity=1,
            entry_time=datetime.now(timezone.utc),
            entry_price=1.0,
            quote_is_fresh=False,
            exit_actionable=True,
        )
        with self.assertRaises(PaperTradeError):
            require_acceptable_exit_quote_for_execution(v)

    def test_rejects_not_actionable(self) -> None:
        v = PaperOpenPositionValuationResponse(
            paper_trade_id=1,
            option_symbol="X",
            side="long",
            quantity=1,
            entry_time=datetime.now(timezone.utc),
            entry_price=1.0,
            quote_is_fresh=True,
            exit_actionable=False,
        )
        with self.assertRaises(PaperTradeError):
            require_acceptable_exit_quote_for_execution(v)

    def test_accepts_fresh_actionable(self) -> None:
        v = PaperOpenPositionValuationResponse(
            paper_trade_id=1,
            option_symbol="X",
            side="long",
            quantity=1,
            entry_time=datetime.now(timezone.utc),
            entry_price=1.0,
            quote_is_fresh=True,
            exit_actionable=True,
        )
        require_acceptable_exit_quote_for_execution(v)


class ExecuteOnceUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = MagicMock()
        self.context = MagicMock()
        self.market = MagicMock()
        self.settings = Settings(APP_MODE="paper")

    def test_no_trade_returns_no_action(self) -> None:
        ev = MagicMock(spec=StrategyOneEvaluationResponse)
        ev.decision = "no_trade"
        repo_inst = MagicMock()
        repo_inst.list_open.return_value = []
        with (
            patch(
                "app.services.paper.strategy_one_execute_once.PaperTradeRepository",
                return_value=repo_inst,
            ),
            patch(
                "app.services.paper.strategy_one_execute_once.build_strategy_one_evaluation_bundle",
                return_value=(ev, _mkt(), _chain()),
            ),
        ):
            out = run_strategy_one_paper_execute_once(
                self.db,
                context=self.context,
                market=self.market,
                settings=self.settings,
            )
        self.assertEqual(out.cycle_action, "no_action")
        self.assertFalse(out.had_open_position_at_start)

    def test_candidate_opens_position(self) -> None:
        ev = MagicMock(spec=StrategyOneEvaluationResponse)
        ev.decision = "candidate_call"
        opened = MagicMock(spec=PaperTrade)
        opened.id = 42
        repo_inst = MagicMock()
        repo_inst.list_open.return_value = []
        with (
            patch(
                "app.services.paper.strategy_one_execute_once.PaperTradeRepository",
                return_value=repo_inst,
            ),
            patch(
                "app.services.paper.strategy_one_execute_once.build_strategy_one_evaluation_bundle",
                return_value=(ev, _mkt(), _chain()),
            ),
            patch.object(PaperTradeService, "open_position", return_value=opened),
            patch(
                "app.services.paper.strategy_one_execute_once.PaperTradeResponse.model_validate",
                return_value=_paper_trade_response_open(42),
            ),
        ):
            out = run_strategy_one_paper_execute_once(
                self.db,
                context=self.context,
                market=self.market,
                settings=self.settings,
            )
        self.assertEqual(out.cycle_action, "opened")
        self.assertIsNotNone(out.opened_paper_trade)

    def test_duplicate_open_returns_no_action(self) -> None:
        ev = MagicMock(spec=StrategyOneEvaluationResponse)
        ev.decision = "candidate_call"
        repo_inst = MagicMock()
        repo_inst.list_open.return_value = []
        with (
            patch(
                "app.services.paper.strategy_one_execute_once.PaperTradeRepository",
                return_value=repo_inst,
            ),
            patch(
                "app.services.paper.strategy_one_execute_once.build_strategy_one_evaluation_bundle",
                return_value=(ev, _mkt(), _chain()),
            ),
            patch.object(
                PaperTradeService,
                "open_position",
                side_effect=PaperTradeError("duplicate_open_position"),
            ),
        ):
            out = run_strategy_one_paper_execute_once(
                self.db,
                context=self.context,
                market=self.market,
                settings=self.settings,
            )
        self.assertEqual(out.cycle_action, "no_action")
        self.assertTrue(any("duplicate" in n for n in out.notes))

    def test_affordability_failure_includes_diagnostics_note(self) -> None:
        ev = MagicMock(spec=StrategyOneEvaluationResponse)
        ev.decision = "candidate_call"
        ev.diagnostics = None
        repo_inst = MagicMock()
        repo_inst.list_open.return_value = []
        err = PaperTradeError(
            "paper_entry_premium_exceeds_risk_budget",
            details={
                "attempted_option_symbol": "SPY  260422C00500000",
                "attempted_ask": 2.86,
                "attempted_total_premium_usd": 286.0,
                "risk_budget_usd": 100.0,
                "max_affordable_premium_usd": 285.7142857,
                "premium_over_budget_usd": 0.2857143,
            },
        )
        with (
            patch(
                "app.services.paper.strategy_one_execute_once.PaperTradeRepository",
                return_value=repo_inst,
            ),
            patch(
                "app.services.paper.strategy_one_execute_once.build_strategy_one_evaluation_bundle",
                return_value=(ev, _mkt(), _chain()),
            ),
            patch.object(PaperTradeService, "open_position", side_effect=err),
        ):
            out = run_strategy_one_paper_execute_once(
                self.db,
                context=self.context,
                market=self.market,
                settings=self.settings,
            )
        self.assertEqual(out.cycle_action, "no_action")
        self.assertTrue(any(n.startswith("auto_open_failed:paper_entry_premium_exceeds_risk_budget") for n in out.notes))
        self.assertTrue(any(n.startswith("affordability_diag:") for n in out.notes))

    def test_open_position_skipped_when_runtime_exit_disabled(self) -> None:
        row = MagicMock(spec=PaperTrade)
        row.id = 7
        row.strategy_id = PaperTradeService.STRATEGY_ID
        row.status = "open"
        repo_inst = MagicMock()
        repo_inst.list_open.return_value = [row]
        with patch(
            "app.services.paper.strategy_one_execute_once.PaperTradeRepository",
            return_value=repo_inst,
        ):
            out = run_strategy_one_paper_execute_once(
                self.db,
                context=self.context,
                market=self.market,
                settings=self.settings,
                exit_enabled=False,
            )
        self.assertEqual(out.cycle_action, "no_action")
        self.assertIn("runtime_exit_disabled", out.notes)

    def test_open_position_still_auto_closes_when_entry_disabled(self) -> None:
        row = MagicMock(spec=PaperTrade)
        row.id = 7
        row.strategy_id = PaperTradeService.STRATEGY_ID
        row.status = "open"
        repo_inst = MagicMock()
        repo_inst.list_open.return_value = [row]
        exit_eval = MagicMock(spec=StrategyOneExitEvaluationResponse)
        exit_eval.action = "close_now"
        valuation = PaperOpenPositionValuationResponse(
            paper_trade_id=7,
            option_symbol="SPY  X",
            side="long",
            quantity=1,
            entry_time=datetime.now(timezone.utc),
            entry_price=2.0,
            quote_is_fresh=True,
            exit_actionable=True,
        )
        closed = MagicMock(spec=PaperTrade)
        with (
            patch(
                "app.services.paper.strategy_one_execute_once.PaperTradeRepository",
                return_value=repo_inst,
            ),
            patch(
                "app.services.paper.strategy_one_execute_once.compute_open_position_valuation",
                return_value=valuation,
            ),
            patch(
                "app.services.paper.strategy_one_execute_once.evaluate_strategy_one_open_exit_readonly",
                return_value=exit_eval,
            ),
            patch.object(PaperTradeService, "close_position", return_value=closed),
            patch(
                "app.services.paper.strategy_one_execute_once.PaperTradeResponse.model_validate",
                return_value=_paper_trade_response_closed(7),
            ),
        ):
            out = run_strategy_one_paper_execute_once(
                self.db,
                context=self.context,
                market=self.market,
                settings=self.settings,
                entry_enabled=False,
                exit_enabled=True,
            )
        self.assertEqual(out.cycle_action, "closed")

    def test_flat_book_skipped_when_runtime_entry_disabled(self) -> None:
        repo_inst = MagicMock()
        repo_inst.list_open.return_value = []
        with patch(
            "app.services.paper.strategy_one_execute_once.PaperTradeRepository",
            return_value=repo_inst,
        ):
            out = run_strategy_one_paper_execute_once(
                self.db,
                context=self.context,
                market=self.market,
                settings=self.settings,
                entry_enabled=False,
            )
        self.assertEqual(out.cycle_action, "no_action")
        self.assertIn("runtime_entry_disabled", out.notes)

    def test_flat_book_still_auto_opens_when_exit_disabled(self) -> None:
        ev = MagicMock(spec=StrategyOneEvaluationResponse)
        ev.decision = "candidate_call"
        opened = MagicMock(spec=PaperTrade)
        repo_inst = MagicMock()
        repo_inst.list_open.return_value = []
        with (
            patch(
                "app.services.paper.strategy_one_execute_once.PaperTradeRepository",
                return_value=repo_inst,
            ),
            patch(
                "app.services.paper.strategy_one_execute_once.build_strategy_one_evaluation_bundle",
                return_value=(ev, _mkt(), _chain()),
            ),
            patch.object(PaperTradeService, "open_position", return_value=opened),
            patch(
                "app.services.paper.strategy_one_execute_once.PaperTradeResponse.model_validate",
                return_value=_paper_trade_response_open(11),
            ),
        ):
            out = run_strategy_one_paper_execute_once(
                self.db,
                context=self.context,
                market=self.market,
                settings=self.settings,
                entry_enabled=True,
                exit_enabled=False,
            )
        self.assertEqual(out.cycle_action, "opened")

    def test_close_now_auto_closes_when_quote_ok(self) -> None:
        row = MagicMock(spec=PaperTrade)
        row.id = 7
        row.strategy_id = PaperTradeService.STRATEGY_ID
        row.status = "open"
        repo_inst = MagicMock()
        repo_inst.list_open.return_value = [row]
        exit_eval = MagicMock(spec=StrategyOneExitEvaluationResponse)
        exit_eval.action = "close_now"
        exit_eval.blockers = []
        exit_eval.reasons = ["premium_fail_safe_stop_breached"]
        valuation = PaperOpenPositionValuationResponse(
            paper_trade_id=7,
            option_symbol="SPY  X",
            side="long",
            quantity=1,
            entry_time=datetime.now(timezone.utc),
            entry_price=2.0,
            quote_is_fresh=True,
            exit_actionable=True,
        )
        closed = MagicMock(spec=PaperTrade)
        closed.id = 7
        closed.status = "closed"
        with (
            patch(
                "app.services.paper.strategy_one_execute_once.PaperTradeRepository",
                return_value=repo_inst,
            ),
            patch(
                "app.services.paper.strategy_one_execute_once.compute_open_position_valuation",
                return_value=valuation,
            ),
            patch(
                "app.services.paper.strategy_one_execute_once.evaluate_strategy_one_open_exit_readonly",
                return_value=exit_eval,
            ),
            patch.object(PaperTradeService, "close_position", return_value=closed),
            patch(
                "app.services.paper.strategy_one_execute_once.PaperTradeResponse.model_validate",
                return_value=_paper_trade_response_closed(7),
            ),
        ):
            out = run_strategy_one_paper_execute_once(
                self.db,
                context=self.context,
                market=self.market,
                settings=self.settings,
            )
        self.assertEqual(out.cycle_action, "closed")
        self.assertEqual(out.closed_paper_trade.id, 7)

    def test_close_now_skipped_when_quote_not_acceptable(self) -> None:
        row = MagicMock(spec=PaperTrade)
        row.id = 1
        row.strategy_id = PaperTradeService.STRATEGY_ID
        row.status = "open"
        repo_inst = MagicMock()
        repo_inst.list_open.return_value = [row]
        exit_eval = MagicMock(spec=StrategyOneExitEvaluationResponse)
        exit_eval.action = "close_now"
        valuation = PaperOpenPositionValuationResponse(
            paper_trade_id=1,
            option_symbol="SPY  X",
            side="long",
            quantity=1,
            entry_time=datetime.now(timezone.utc),
            entry_price=2.0,
            quote_is_fresh=False,
            exit_actionable=False,
        )
        with (
            patch(
                "app.services.paper.strategy_one_execute_once.PaperTradeRepository",
                return_value=repo_inst,
            ),
            patch(
                "app.services.paper.strategy_one_execute_once.compute_open_position_valuation",
                return_value=valuation,
            ),
            patch(
                "app.services.paper.strategy_one_execute_once.evaluate_strategy_one_open_exit_readonly",
                return_value=exit_eval,
            ),
            patch.object(PaperTradeService, "close_position") as close_mock,
        ):
            out = run_strategy_one_paper_execute_once(
                self.db,
                context=self.context,
                market=self.market,
                settings=self.settings,
            )
        self.assertEqual(out.cycle_action, "no_action")
        close_mock.assert_not_called()

    def test_second_cycle_safe_after_close(self) -> None:
        """After auto-close, a flat book cycle attempts entry (mocked no_trade here)."""
        repo_inst = MagicMock()
        repo_inst.list_open.side_effect = [[MagicMock(id=1)], []]
        ev = MagicMock(spec=StrategyOneEvaluationResponse)
        ev.decision = "no_trade"
        exit_eval = MagicMock(spec=StrategyOneExitEvaluationResponse)
        exit_eval.action = "close_now"
        valuation = PaperOpenPositionValuationResponse(
            paper_trade_id=1,
            option_symbol="SPY  X",
            side="long",
            quantity=1,
            entry_time=datetime.now(timezone.utc),
            entry_price=2.0,
            quote_is_fresh=True,
            exit_actionable=True,
        )
        closed = MagicMock(spec=PaperTrade)
        closed.id = 1
        closed.status = "closed"
        with (
            patch(
                "app.services.paper.strategy_one_execute_once.PaperTradeRepository",
                return_value=repo_inst,
            ),
            patch(
                "app.services.paper.strategy_one_execute_once.compute_open_position_valuation",
                return_value=valuation,
            ),
            patch(
                "app.services.paper.strategy_one_execute_once.evaluate_strategy_one_open_exit_readonly",
                return_value=exit_eval,
            ),
            patch.object(PaperTradeService, "close_position", return_value=closed),
            patch(
                "app.services.paper.strategy_one_execute_once.PaperTradeResponse.model_validate",
                return_value=_paper_trade_response_closed(1),
            ),
            patch(
                "app.services.paper.strategy_one_execute_once.build_strategy_one_evaluation_bundle",
                return_value=(ev, _mkt(), _chain()),
            ),
        ):
            first = run_strategy_one_paper_execute_once(
                self.db,
                context=self.context,
                market=self.market,
                settings=self.settings,
            )
            second = run_strategy_one_paper_execute_once(
                self.db,
                context=self.context,
                market=self.market,
                settings=self.settings,
            )
        self.assertEqual(first.cycle_action, "closed")
        self.assertEqual(second.cycle_action, "no_action")


class EmergencyCloseTests(unittest.TestCase):
    def test_not_open_raises(self) -> None:
        repo_inst = MagicMock()
        repo_inst.get_trade.return_value = None
        with (
            patch(
                "app.services.paper.strategy_one_execute_once.PaperTradeRepository",
                return_value=repo_inst,
            ),
            patch(
                "app.services.paper.strategy_one_execute_once.compute_open_position_valuation",
            ),
        ):
            with self.assertRaises(PaperTradeError) as ctx:
                run_emergency_close_open_paper_trade(
                    MagicMock(),
                    paper_trade_id=99,
                    market=MagicMock(),
                    settings=Settings(APP_MODE="paper"),
                )
        self.assertEqual(str(ctx.exception), "paper_trade_not_open_for_emergency_close")
