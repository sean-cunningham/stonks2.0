from __future__ import annotations

import threading
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.core.config import Settings
from app.schemas.strategy_one_paper_execution import StrategyOneExecuteOnceResponse
from app.services.paper.strategy_one_runtime_service import (
    RESULT_ERROR,
    SKIPPED_OVERLAP,
    SKIPPED_PAUSED,
    StrategyOneRuntimeCoordinator,
)


def _state() -> SimpleNamespace:
    return SimpleNamespace(
        strategy_id="strategy_1_spy",
        paused=False,
        entry_enabled=True,
        exit_enabled=True,
        last_cycle_started_at=None,
        last_cycle_finished_at=None,
        last_cycle_result=None,
        last_error=None,
    )


class StrategyOneRuntimeServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(APP_MODE="paper")
        self.db = MagicMock()
        self.context = MagicMock()
        self.market = MagicMock()

    def test_paused_tick_skips_and_logs(self) -> None:
        coord = StrategyOneRuntimeCoordinator()
        st = _state()
        st.paused = True
        repo = MagicMock()
        repo.get_or_create_state.return_value = st
        with patch(
            "app.services.paper.strategy_one_runtime_service.StrategyRuntimeRepository",
            return_value=repo,
        ):
            out = coord.run_tick(self.db, context=self.context, market=self.market, settings=self.settings)
        self.assertEqual(out.last_cycle_result, SKIPPED_PAUSED)
        self.assertFalse(out.running)
        repo.append_cycle_log.assert_called_once()

    def test_overlap_tick_skips_when_lock_held(self) -> None:
        coord = StrategyOneRuntimeCoordinator()
        st = _state()
        repo = MagicMock()
        repo.get_or_create_state.return_value = st
        lock = threading.Lock()
        lock.acquire()
        coord._lock = lock
        try:
            with patch(
                "app.services.paper.strategy_one_runtime_service.StrategyRuntimeRepository",
                return_value=repo,
            ):
                out = coord.run_tick(self.db, context=self.context, market=self.market, settings=self.settings)
        finally:
            lock.release()
        self.assertTrue(out.running)
        self.assertEqual(repo.append_cycle_log.call_args.args[0].result, SKIPPED_OVERLAP)

    def test_successful_tick_persists_cycle_action(self) -> None:
        coord = StrategyOneRuntimeCoordinator()
        st = _state()
        repo = MagicMock()
        repo.get_or_create_state.return_value = st
        cycle = StrategyOneExecuteOnceResponse(
            cycle_action="opened",
            had_open_position_at_start=False,
            notes=["ok"],
            evaluation_timestamp=datetime.now(timezone.utc),
        )
        with (
            patch(
                "app.services.paper.strategy_one_runtime_service.StrategyRuntimeRepository",
                return_value=repo,
            ),
            patch(
                "app.services.paper.strategy_one_runtime_service.run_strategy_one_paper_execute_once",
                return_value=cycle,
            ) as exec_once_mock,
        ):
            out = coord.run_tick(self.db, context=self.context, market=self.market, settings=self.settings)
        self.assertEqual(out.last_cycle_result, "opened")
        self.assertIsNone(out.last_error)
        exec_once_mock.assert_called_once()

    def test_tick_error_sets_last_error(self) -> None:
        coord = StrategyOneRuntimeCoordinator()
        st = _state()
        repo = MagicMock()
        repo.get_or_create_state.return_value = st
        with (
            patch(
                "app.services.paper.strategy_one_runtime_service.StrategyRuntimeRepository",
                return_value=repo,
            ),
            patch(
                "app.services.paper.strategy_one_runtime_service.run_strategy_one_paper_execute_once",
                side_effect=RuntimeError("boom"),
            ),
        ):
            out = coord.run_tick(self.db, context=self.context, market=self.market, settings=self.settings)
        self.assertEqual(out.last_cycle_result, RESULT_ERROR)
        self.assertEqual(out.last_error, "boom")
