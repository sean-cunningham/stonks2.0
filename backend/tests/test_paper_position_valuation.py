"""Mark-to-market valuation for open paper positions (chain snapshot; no synthetic prices)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.models.trade import PaperTrade
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.schemas.market import ChainLatestResponse, NearAtmContract
from app.services.paper.contract_constants import OPTION_CONTRACT_MULTIPLIER
from app.services.paper.paper_trade_service import PaperTradeService
from app.services.paper.paper_valuation import compute_open_position_valuation
import app.models.trade  # noqa: F401


def _ensure_open_contract_unique_index(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_trades_open_contract "
                "ON paper_trades (strategy_id, option_symbol, side) WHERE status = 'open'"
            )
        )


def _chain(
    *,
    sym: str,
    bid: float,
    ask: float,
    snapshot_ts: datetime,
    available: bool = True,
    option_quotes: bool = True,
) -> ChainLatestResponse:
    c = NearAtmContract(
        option_symbol=sym,
        strike=500.0,
        option_type="call",
        expiration_date="2026-04-22",
        bid=bid,
        ask=ask,
        mid=(bid + ask) / 2.0,
        spread_percent=10.0,
        delta=0.5,
        is_call=True,
        is_put=False,
    )
    return ChainLatestResponse(
        underlying_symbol="SPY",
        available=available,
        snapshot_timestamp=snapshot_ts,
        expiration_dates_found=["2026-04-22"],
        selected_expiration="2026-04-22",
        underlying_reference_price=500.0,
        total_contracts_seen=1,
        option_quotes_available=option_quotes,
        near_atm_contracts=[c],
        source_status="ok",
    )


def _open_row(*, option_symbol: str, entry_price: float, snap: dict | None = None) -> PaperTrade:
    return PaperTrade(
        strategy_id=PaperTradeService.STRATEGY_ID,
        symbol="SPY",
        option_symbol=option_symbol,
        side="long",
        quantity=1,
        entry_time=datetime(2026, 4, 21, 15, 0, 0, tzinfo=timezone.utc),
        entry_price=entry_price,
        exit_time=None,
        exit_price=None,
        realized_pnl=None,
        status="open",
        entry_decision="candidate_call",
        evaluation_snapshot_json=snap
        or {
            "symbol": "SPY",
            "decision": "candidate_call",
            "evaluation_timestamp": "2026-04-21T15:00:00+00:00",
        },
        entry_reference_basis="option_ask",
        exit_reference_basis=None,
        exit_reason=None,
        entry_evaluation_fingerprint="fp",
    )


class PaperPositionValuationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        _ensure_open_contract_unique_index(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.settings = Settings(MARKET_CHAIN_MAX_AGE_SECONDS=60, MARKET_QUOTE_MAX_AGE_SECONDS=15)

    def test_unrealized_pnl_bid_basis_matches_long_formula(self) -> None:
        sym = "SPY  260422C00500000"
        row = _open_row(option_symbol=sym, entry_price=2.0)
        now = datetime.now(timezone.utc)
        ch = _chain(sym=sym, bid=2.5, ask=2.7, snapshot_ts=now.replace(microsecond=0))
        v = compute_open_position_valuation(row, ch, self.settings, now=now)
        self.assertIsNone(v.valuation_error)
        self.assertAlmostEqual(v.current_bid or 0, 2.5)
        self.assertAlmostEqual(v.current_ask or 0, 2.7)
        expected = (2.5 - 2.0) * OPTION_CONTRACT_MULTIPLIER * 1
        self.assertAlmostEqual(v.unrealized_pnl_bid_basis or 0.0, expected, places=4)
        self.assertTrue(v.exit_actionable)
        self.assertTrue(v.quote_is_fresh)

    def test_mid_and_mid_basis_only_when_two_sided(self) -> None:
        sym = "SPY  260422C00500000"
        row = _open_row(option_symbol=sym, entry_price=2.0)
        now = datetime.now(timezone.utc)
        ch = _chain(sym=sym, bid=2.4, ask=2.6, snapshot_ts=now.replace(microsecond=0))
        v = compute_open_position_valuation(row, ch, self.settings, now=now)
        self.assertAlmostEqual(v.current_mid or 0, 2.5)
        mid_pnl = (2.5 - 2.0) * OPTION_CONTRACT_MULTIPLIER
        self.assertAlmostEqual(v.unrealized_pnl_mid_basis or 0.0, mid_pnl, places=4)

    def test_mid_absent_without_ask_side(self) -> None:
        sym = "SPY  260422C00500000"
        row = _open_row(option_symbol=sym, entry_price=2.0)
        now = datetime.now(timezone.utc)
        ts = now.replace(microsecond=0)
        c = NearAtmContract(
            option_symbol=sym,
            strike=500.0,
            option_type="call",
            expiration_date="2026-04-22",
            bid=2.4,
            ask=None,
            mid=None,
            spread_percent=0.0,
            delta=0.5,
            is_call=True,
            is_put=False,
        )
        ch = ChainLatestResponse(
            underlying_symbol="SPY",
            available=True,
            snapshot_timestamp=ts,
            expiration_dates_found=["2026-04-22"],
            selected_expiration="2026-04-22",
            underlying_reference_price=500.0,
            total_contracts_seen=1,
            option_quotes_available=True,
            near_atm_contracts=[c],
            source_status="ok",
        )
        v = compute_open_position_valuation(row, ch, self.settings, now=now)
        self.assertIsNone(v.current_mid)
        self.assertIsNone(v.unrealized_pnl_mid_basis)
        self.assertFalse(v.exit_actionable)
        self.assertIsNotNone(v.unrealized_pnl_bid_basis)

    def test_missing_contract_fail_closed(self) -> None:
        row = _open_row(option_symbol="SPY  260422C00999999", entry_price=2.0)
        now = datetime.now(timezone.utc)
        ch = _chain(sym="SPY  260422C00500000", bid=2.0, ask=2.2, snapshot_ts=now.replace(microsecond=0))
        v = compute_open_position_valuation(row, ch, self.settings, now=now)
        self.assertIsNotNone(v.valuation_error)
        self.assertEqual(v.quote_blocker_code, "option_contract_not_in_near_atm_chain_snapshot")
        self.assertFalse(v.exit_actionable)
        self.assertIsNone(v.current_bid)
        self.assertIsNone(v.unrealized_pnl_bid_basis)

    def test_stale_chain_makes_actionable_false_and_freshness_false(self) -> None:
        sym = "SPY  260422C00500000"
        row = _open_row(option_symbol=sym, entry_price=2.0)
        now = datetime.now(timezone.utc)
        old = now - timedelta(seconds=9999)
        ch = _chain(sym=sym, bid=2.1, ask=2.3, snapshot_ts=old)
        v = compute_open_position_valuation(row, ch, self.settings, now=now)
        self.assertFalse(v.quote_is_fresh)
        self.assertFalse(v.exit_actionable)
        self.assertGreater(v.quote_age_seconds or 0, float(self.settings.MARKET_CHAIN_MAX_AGE_SECONDS))

    def test_closed_row_not_returned_from_open_list_service(self) -> None:
        """Valuation list uses repository list_open — closed rows never appear."""
        db = self.Session()
        try:
            repo = PaperTradeRepository(db)
            open_row = _open_row(option_symbol="SPY  260422C00500000", entry_price=2.0)
            open_row = repo.create_trade(open_row)
            closed = PaperTrade(
                strategy_id=PaperTradeService.STRATEGY_ID,
                symbol="SPY",
                option_symbol="SPY  260422P00500000",
                side="long",
                quantity=1,
                entry_time=datetime(2026, 4, 21, 14, 0, 0, tzinfo=timezone.utc),
                entry_price=3.0,
                exit_time=datetime(2026, 4, 21, 16, 0, 0, tzinfo=timezone.utc),
                exit_price=2.5,
                realized_pnl=-50.0,
                status="closed",
                entry_decision="candidate_put",
                evaluation_snapshot_json={},
                entry_reference_basis="option_ask",
                exit_reference_basis="option_bid",
                exit_reason="done",
                entry_evaluation_fingerprint="fp2",
            )
            repo.create_trade(closed)
            opens = repo.list_open(strategy_id=PaperTradeService.STRATEGY_ID)
            self.assertEqual(len(opens), 1)
            self.assertEqual(opens[0].id, open_row.id)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
