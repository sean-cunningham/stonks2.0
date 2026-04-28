from __future__ import annotations

import unittest

from app.services.paper.strategy_two_runtime_service import _normalize_runtime_error_code


class StrategyTwoRuntimeServiceTests(unittest.TestCase):
    def test_normalizes_dxlink_timeout(self) -> None:
        code = _normalize_runtime_error_code(TimeoutError("timed out during opening handshake"))
        self.assertEqual(code, "dxlink_handshake_timeout")

    def test_normalizes_option_quote_errors(self) -> None:
        code = _normalize_runtime_error_code(RuntimeError("missing_option_quote_for_open_position"))
        self.assertEqual(code, "option_quote_refresh_failed")

    def test_fallback_preserves_message(self) -> None:
        code = _normalize_runtime_error_code(RuntimeError("unexpected failure"))
        self.assertEqual(code, "unexpected failure")

