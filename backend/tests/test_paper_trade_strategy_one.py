"""Paper trade scaffolding for Strategy 1 — service rules and P&L (no broker)."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.models.trade import PaperTrade, PaperTradeEvent
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.schemas.market import ChainLatestResponse, MarketStatusResponse, NearAtmContract
from app.schemas.strategy import StrategyOneContextSnapshot, StrategyOneEvaluationResponse
from app.services.paper.paper_trade_service import (
    OPTION_CONTRACT_MULTIPLIER,
    PaperTradeError,
    PaperTradeService,
)
import app.models.trade  # noqa: F401


def _fresh_chain(*, bid: float = 2.0, ask: float = 2.2, sym: str = "SPY  260422C00500000") -> ChainLatestResponse:
    ts = datetime.now(timezone.utc)
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


def _stale_chain() -> ChainLatestResponse:
    c = NearAtmContract(
        option_symbol="SPY  260422C00500000",
        strike=500.0,
        option_type="call",
        expiration_date="2026-04-22",
        bid=2.0,
        ask=2.2,
        mid=2.1,
        spread_percent=10.0,
        delta=0.5,
        is_call=True,
        is_put=False,
    )
    old = datetime.now(timezone.utc) - timedelta(seconds=9999)
    return ChainLatestResponse(
        underlying_symbol="SPY",
        available=True,
        snapshot_timestamp=old,
        expiration_dates_found=["2026-04-22"],
        selected_expiration="2026-04-22",
        underlying_reference_price=500.0,
        total_contracts_seen=1,
        option_quotes_available=True,
        near_atm_contracts=[c],
        source_status="ok",
    )


def _market_ready() -> MarketStatusResponse:
    now = datetime.now(timezone.utc)
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
        latest_quote_time=now,
        latest_chain_time=now,
        source_status="ok",
    )


def _ctx_snap() -> StrategyOneContextSnapshot:
    return StrategyOneContextSnapshot(
        us_equity_rth_open=True,
        context_ready_for_live_trading=True,
        context_block_reason="none",
        latest_price=500.0,
        session_vwap=499.0,
        opening_range_high=510.0,
        opening_range_low=490.0,
        latest_5m_atr=2.0,
        recent_swing_high=515.0,
        recent_swing_low=485.0,
        market_ready=True,
        market_block_reason="none",
        chain_available=True,
        chain_option_quotes_available=True,
        chain_selected_expiration="2026-04-22",
        underlying_reference_price=500.0,
    )


def _candidate_call_eval() -> StrategyOneEvaluationResponse:
    c = NearAtmContract(
        option_symbol="SPY  260422C00500000",
        strike=500.0,
        option_type="call",
        expiration_date="2026-04-22",
        bid=2.0,
        ask=2.2,
        mid=2.1,
        spread_percent=10.0,
        delta=0.5,
        is_call=True,
        is_put=False,
    )
    return StrategyOneEvaluationResponse(
        decision="candidate_call",
        blockers=[],
        reasons=["ok"],
        context_snapshot_used=_ctx_snap(),
        contract_candidate=c,
        evaluation_timestamp=datetime.now(timezone.utc),
    )


def _candidate_put_eval() -> StrategyOneEvaluationResponse:
    c = NearAtmContract(
        option_symbol="SPY  260422P00500000",
        strike=500.0,
        option_type="put",
        expiration_date="2026-04-22",
        bid=3.0,
        ask=3.2,
        mid=3.1,
        spread_percent=8.0,
        delta=-0.4,
        is_call=False,
        is_put=True,
    )
    return StrategyOneEvaluationResponse(
        decision="candidate_put",
        blockers=[],
        reasons=["ok"],
        context_snapshot_used=_ctx_snap(),
        contract_candidate=c,
        evaluation_timestamp=datetime.now(timezone.utc),
    )


def _no_trade_eval() -> StrategyOneEvaluationResponse:
    return StrategyOneEvaluationResponse(
        decision="no_trade",
        blockers=["no_trade_zone:vwap_atr_band"],
        reasons=[],
        context_snapshot_used=_ctx_snap(),
        contract_candidate=None,
        evaluation_timestamp=datetime.now(timezone.utc),
    )


class PaperTradeStrategyOneServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.settings = Settings(MARKET_CHAIN_MAX_AGE_SECONDS=60, MARKET_QUOTE_MAX_AGE_SECONDS=15)
        self.svc = PaperTradeService()

    def test_cannot_open_from_no_trade(self) -> None:
        db = self.Session()
        try:
            with self.assertRaises(PaperTradeError):
                self.svc.open_position(
                    db,
                    evaluation=_no_trade_eval(),
                    chain=_fresh_chain(),
                    market_status=_market_ready(),
                    settings=self.settings,
                )
        finally:
            db.close()

    def test_can_open_from_candidate_call(self) -> None:
        db = self.Session()
        try:
            ev = _candidate_call_eval()
            ch = _fresh_chain(bid=2.0, ask=2.2, sym=ev.contract_candidate.option_symbol)
            row = self.svc.open_position(
                db,
                evaluation=ev,
                chain=ch,
                market_status=_market_ready(),
                settings=self.settings,
            )
            self.assertEqual(row.status, "open")
            self.assertEqual(row.side, "long")
            self.assertEqual(row.quantity, 1)
            self.assertEqual(row.entry_decision, "candidate_call")
            self.assertAlmostEqual(row.entry_price, 2.2, places=4)
            self.assertEqual(row.entry_reference_basis, "option_ask")
            self.assertEqual(row.option_symbol, "SPY  260422C00500000")
            repo = PaperTradeRepository(db)
            events = repo.list_events_for_trade(row.id)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, "open")
        finally:
            db.close()

    def test_can_open_from_candidate_put(self) -> None:
        db = self.Session()
        try:
            ev = _candidate_put_eval()
            ch = _fresh_chain(bid=3.0, ask=3.2, sym=ev.contract_candidate.option_symbol)
            row = self.svc.open_position(
                db,
                evaluation=ev,
                chain=ch,
                market_status=_market_ready(),
                settings=self.settings,
            )
            self.assertEqual(row.entry_decision, "candidate_put")
            self.assertAlmostEqual(row.entry_price, 3.2, places=4)
        finally:
            db.close()

    def test_rejects_entry_when_chain_quote_stale(self) -> None:
        db = self.Session()
        try:
            with self.assertRaises(PaperTradeError) as ctx:
                self.svc.open_position(
                    db,
                    evaluation=_candidate_call_eval(),
                    chain=_stale_chain(),
                    market_status=_market_ready(),
                    settings=self.settings,
                )
            self.assertIn("chain", str(ctx.exception).lower())
        finally:
            db.close()

    def test_rejects_entry_when_ask_missing(self) -> None:
        db = self.Session()
        try:
            c = NearAtmContract(
                option_symbol="SPY  260422C00500000",
                strike=500.0,
                option_type="call",
                expiration_date="2026-04-22",
                bid=2.0,
                ask=None,
                mid=None,
                spread_percent=None,
                delta=0.5,
                is_call=True,
                is_put=False,
            )
            ch = ChainLatestResponse(
                underlying_symbol="SPY",
                available=True,
                snapshot_timestamp=datetime.now(timezone.utc),
                expiration_dates_found=["2026-04-22"],
                selected_expiration="2026-04-22",
                underlying_reference_price=500.0,
                total_contracts_seen=1,
                option_quotes_available=True,
                near_atm_contracts=[c],
                source_status="ok",
            )
            with self.assertRaises(PaperTradeError):
                self.svc.open_position(
                    db,
                    evaluation=_candidate_call_eval(),
                    chain=ch,
                    market_status=_market_ready(),
                    settings=self.settings,
                )
        finally:
            db.close()

    def test_close_open_position_and_pnl(self) -> None:
        db = self.Session()
        try:
            ev = _candidate_call_eval()
            entry_chain = _fresh_chain(bid=2.0, ask=2.2, sym=ev.contract_candidate.option_symbol)
            row = self.svc.open_position(
                db,
                evaluation=ev,
                chain=entry_chain,
                market_status=_market_ready(),
                settings=self.settings,
            )
            exit_chain = _fresh_chain(bid=2.5, ask=2.7, sym=ev.contract_candidate.option_symbol)
            closed = self.svc.close_position(
                db,
                paper_trade_id=row.id,
                chain=exit_chain,
                market_status=_market_ready(),
                exit_reason="test_take_profit",
                settings=self.settings,
            )
            self.assertEqual(closed.status, "closed")
            self.assertAlmostEqual(closed.exit_price, 2.5, places=4)
            self.assertEqual(closed.exit_reference_basis, "option_bid")
            # Long: (bid_exit - ask_entry) * 100 * qty
            expected = (2.5 - 2.2) * OPTION_CONTRACT_MULTIPLIER * 1
            self.assertAlmostEqual(closed.realized_pnl or 0.0, expected, places=4)
            repo = PaperTradeRepository(db)
            evs = repo.list_events_for_trade(row.id)
            self.assertEqual(len(evs), 2)
            types = sorted(e.event_type for e in evs)
            self.assertEqual(types, ["close", "open"])
        finally:
            db.close()

    def test_cannot_close_already_closed(self) -> None:
        db = self.Session()
        try:
            ev = _candidate_call_eval()
            ch = _fresh_chain(sym=ev.contract_candidate.option_symbol)
            row = self.svc.open_position(
                db,
                evaluation=ev,
                chain=ch,
                market_status=_market_ready(),
                settings=self.settings,
            )
            self.svc.close_position(
                db,
                paper_trade_id=row.id,
                chain=_fresh_chain(bid=2.1, ask=2.3, sym=ev.contract_candidate.option_symbol),
                market_status=_market_ready(),
                exit_reason="first",
                settings=self.settings,
            )
            with self.assertRaises(PaperTradeError):
                self.svc.close_position(
                    db,
                    paper_trade_id=row.id,
                    chain=_fresh_chain(bid=2.1, ask=2.3, sym=ev.contract_candidate.option_symbol),
                    market_status=_market_ready(),
                    exit_reason="second",
                    settings=self.settings,
                )
        finally:
            db.close()

    def test_journal_lists_events_newest_first(self) -> None:
        db = self.Session()
        try:
            ev = _candidate_call_eval()
            sym = ev.contract_candidate.option_symbol
            row = self.svc.open_position(
                db,
                evaluation=ev,
                chain=_fresh_chain(sym=sym),
                market_status=_market_ready(),
                settings=self.settings,
            )
            self.svc.close_position(
                db,
                paper_trade_id=row.id,
                chain=_fresh_chain(bid=2.1, ask=2.3, sym=sym),
                market_status=_market_ready(),
                exit_reason="done",
                settings=self.settings,
            )
            repo = PaperTradeRepository(db)
            journal = repo.list_journal(strategy_id=PaperTradeService.STRATEGY_ID, limit=50)
            self.assertGreaterEqual(len(journal), 2)
            self.assertTrue(all(isinstance(e, PaperTradeEvent) for e in journal))
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
