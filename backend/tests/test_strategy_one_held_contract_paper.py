"""Strategy 1 held-contract quote resolution, manual close, and emergency unquoted close."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base, get_db
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.paper_strategy_one import router as paper_router
from app.api.strategy_one import get_market_service
from app.models.trade import PaperTrade
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.schemas.market import ChainLatestResponse, MarketStatusResponse, NearAtmContract
from app.schemas.strategy_one_entry_policies import Strategy1ExitPolicyV1, Strategy1SizingPolicyV1
from app.services.paper.held_option_contract_resolution import (
    HeldOptionContractResolution,
    build_near_atm_contract_for_held_direct_quote,
)
from app.services.paper import paper_trade_service as paper_trade_service_mod
from app.services.paper.paper_trade_service import PaperTradeError, PaperTradeService
from app.services.paper.paper_valuation import compute_open_position_valuation
from app.services.strategy.strategy_two_spy_0dte_vol_sniper import STRATEGY2_ID
import app.models.trade  # noqa: F401
import app.models.strategy_runtime  # noqa: F401


def _chain_missing_held(*, snapshot_ts: datetime) -> ChainLatestResponse:
    """Chain contains a different symbol than the open row (near-ATM pool miss)."""
    other = NearAtmContract(
        option_symbol="SPY  260429C00500000",
        strike=500.0,
        option_type="call",
        expiration_date="2026-04-29",
        bid=2.0,
        ask=2.2,
        mid=2.1,
        spread_percent=5.0,
        delta=0.5,
        is_call=True,
        is_put=False,
    )
    return ChainLatestResponse(
        underlying_symbol="SPY",
        available=True,
        snapshot_timestamp=snapshot_ts,
        expiration_dates_found=["2026-04-29"],
        selected_expiration="2026-04-29",
        underlying_reference_price=500.0,
        total_contracts_seen=1,
        option_quotes_available=True,
        near_atm_contracts=[other],
        source_status="ok",
    )


def _held_sym() -> str:
    return "SPY  260429C00714000"


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


def _open_trade_row(*, held: str, entry_price: float = 2.1) -> PaperTrade:
    return PaperTrade(
        strategy_id=PaperTradeService.STRATEGY_ID,
        symbol="SPY",
        option_symbol=held,
        side="long",
        quantity=1,
        entry_time=datetime(2026, 4, 27, 16, 0, 0, tzinfo=timezone.utc),
        entry_price=entry_price,
        exit_time=None,
        exit_price=None,
        realized_pnl=None,
        status="open",
        entry_decision="candidate_call",
        evaluation_snapshot_json={"symbol": "SPY", "latest_price": 712.5, "decision": "candidate_call"},
        entry_reference_basis="option_ask",
        exit_reference_basis=None,
        exit_reason=None,
        entry_evaluation_fingerprint="fp",
        exit_policy=Strategy1ExitPolicyV1(
            trade_horizon_class="intraday_continuation",
            calendar_dte_at_entry=2,
            expiry_band="2_5_dte",
            thesis_stop_reference={"level": 400.0},
        ).model_dump(mode="json"),
        sizing_policy=Strategy1SizingPolicyV1(
            account_equity_usd=5000.0,
            risk_budget_usd=100.0,
            fail_safe_stop_pct=0.35,
            max_affordable_premium_usd=300.0,
            entry_ask_per_share=entry_price,
            entry_total_premium_usd=entry_price * 100.0,
        ).model_dump(mode="json"),
    )


class HeldContractValuationTests(unittest.TestCase):
    def test_valuation_uses_direct_resolution_when_not_in_chain(self) -> None:
        settings = Settings(MARKET_CHAIN_MAX_AGE_SECONDS=120)
        now = datetime(2026, 4, 27, 17, 0, 0, tzinfo=timezone.utc)
        ch = _chain_missing_held(snapshot_ts=now)
        row = _open_trade_row(held=_held_sym())
        c = build_near_atm_contract_for_held_direct_quote(_held_sym(), bid=2.15, ask=2.25)
        held = HeldOptionContractResolution(contract=c, quote_timestamp=now, source="direct_dxlink")
        v = compute_open_position_valuation(row, ch, settings, now=now, held_resolution=held)
        self.assertIsNone(v.valuation_error)
        self.assertEqual(v.quote_resolution_source, "direct_dxlink")
        self.assertTrue(v.exit_actionable)
        self.assertAlmostEqual(v.current_bid or 0, 2.15)
        self.assertIsNone(v.quote_blocker_code)

    def test_valuation_quote_blocker_when_direct_stale(self) -> None:
        settings = Settings(MARKET_CHAIN_MAX_AGE_SECONDS=30)
        clock = datetime(2026, 4, 27, 17, 5, 0, tzinfo=timezone.utc)
        old = datetime(2026, 4, 27, 16, 0, 0, tzinfo=timezone.utc)
        ch = _chain_missing_held(snapshot_ts=clock)
        row = _open_trade_row(held=_held_sym())
        c = build_near_atm_contract_for_held_direct_quote(_held_sym(), bid=2.0, ask=2.2)
        held = HeldOptionContractResolution(contract=c, quote_timestamp=old, source="direct_dxlink")
        v = compute_open_position_valuation(row, ch, settings, now=clock, held_resolution=held)
        self.assertFalse(v.quote_is_fresh)
        self.assertEqual(v.quote_blocker_code, "stale_option_quote_for_open_position")


class HeldContractCloseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)

    def test_close_with_held_resolution_bypasses_near_atm_pool(self) -> None:
        db = self.Session()
        try:
            repo = PaperTradeRepository(db)
            row = repo.create_trade(_open_trade_row(held=_held_sym()))
            now = datetime(2026, 4, 27, 17, 0, 0, tzinfo=timezone.utc)
            ch = _chain_missing_held(snapshot_ts=now)
            c = build_near_atm_contract_for_held_direct_quote(_held_sym(), bid=2.0, ask=2.2)
            held = HeldOptionContractResolution(contract=c, quote_timestamp=now, source="direct_dxlink")
            svc = PaperTradeService()
            with patch.object(PaperTradeRepository, "utc_now", return_value=now):
                closed = svc.close_position(
                    db,
                    paper_trade_id=int(row.id),
                    chain=ch,
                    market_status=_market_ready(),
                    exit_reason="test_close",
                    settings=Settings(MARKET_CHAIN_MAX_AGE_SECONDS=120),
                    held_contract_resolution=held,
                )
            self.assertEqual(closed.status, "closed")
            self.assertAlmostEqual(float(closed.exit_price or 0), 2.0)
        finally:
            db.close()

    def test_close_raises_missing_bid_structured(self) -> None:
        db = self.Session()
        try:
            repo = PaperTradeRepository(db)
            row = repo.create_trade(_open_trade_row(held=_held_sym()))
            now = datetime(2026, 4, 27, 17, 0, 0, tzinfo=timezone.utc)
            ch = _chain_missing_held(snapshot_ts=now)
            c = build_near_atm_contract_for_held_direct_quote(_held_sym(), bid=None, ask=2.2)
            held = HeldOptionContractResolution(contract=c, quote_timestamp=now, source="direct_dxlink")
            svc = PaperTradeService()
            with patch.object(PaperTradeRepository, "utc_now", return_value=now):
                with self.assertRaises(PaperTradeError) as ctx:
                    svc.close_position(
                        db,
                        paper_trade_id=int(row.id),
                        chain=ch,
                        market_status=_market_ready(),
                        exit_reason="x",
                        settings=Settings(MARKET_CHAIN_MAX_AGE_SECONDS=120),
                        held_contract_resolution=held,
                    )
            self.assertEqual(ctx.exception.code, "missing_option_quote_for_open_position")
        finally:
            db.close()

    def test_emergency_unquoted_closes_at_zero(self) -> None:
        db = self.Session()
        try:
            repo = PaperTradeRepository(db)
            row = repo.create_trade(_open_trade_row(held=_held_sym(), entry_price=2.0))
            svc = PaperTradeService()
            now = datetime(2026, 4, 27, 17, 0, 0, tzinfo=timezone.utc)
            mock_m = MagicMock()
            mock_m.resolve_spy_market_for_evaluation.return_value = MagicMock(final_status=_market_ready())
            mock_m.get_latest_chain.return_value = _chain_missing_held(snapshot_ts=now)
            mock_m.resolve_open_paper_option_contract.return_value = None
            closed = svc.emergency_close_unquoted_paper_position(
                db,
                paper_trade_id=int(row.id),
                market=mock_m,
                settings=Settings(MARKET_CHAIN_MAX_AGE_SECONDS=120),
            )
            self.assertEqual(closed.status, "closed")
            self.assertAlmostEqual(float(closed.exit_price or 0), 0.0)
            self.assertEqual(closed.exit_reason, paper_trade_service_mod.MANUAL_EMERGENCY_CLOSE_UNQUOTED)
        finally:
            db.close()

    def test_emergency_prefers_live_bid_when_quote_actionable(self) -> None:
        db = self.Session()
        try:
            repo = PaperTradeRepository(db)
            row = repo.create_trade(_open_trade_row(held=_held_sym(), entry_price=2.0))
            svc = PaperTradeService()
            now = datetime(2026, 4, 27, 17, 0, 0, tzinfo=timezone.utc)
            mock_m = MagicMock()
            mock_m.resolve_spy_market_for_evaluation.return_value = MagicMock(final_status=_market_ready())
            mock_m.get_latest_chain.return_value = _chain_missing_held(snapshot_ts=now)
            c = build_near_atm_contract_for_held_direct_quote(_held_sym(), bid=1.85, ask=2.05)
            mock_m.resolve_open_paper_option_contract.return_value = HeldOptionContractResolution(
                contract=c, quote_timestamp=now, source="direct_dxlink"
            )
            with patch.object(PaperTradeRepository, "utc_now", return_value=now):
                closed = svc.emergency_close_unquoted_paper_position(
                    db,
                    paper_trade_id=int(row.id),
                    market=mock_m,
                    settings=Settings(MARKET_CHAIN_MAX_AGE_SECONDS=120),
                )
            self.assertEqual(closed.exit_reason, paper_trade_service_mod.MANUAL_EMERGENCY_CLOSE_AT_MARKET_BID)
            self.assertAlmostEqual(float(closed.exit_price or 0), 1.85)
        finally:
            db.close()


class HeldContractApiTests(unittest.TestCase):
    def test_emergency_unquoted_endpoint(self) -> None:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        def override_get_db():
            db = session_local()
            try:
                yield db
            finally:
                db.close()

        app = FastAPI()
        app.include_router(paper_router)
        app.dependency_overrides[get_db] = override_get_db

        now = datetime(2026, 4, 27, 17, 0, 0, tzinfo=timezone.utc)
        mock_mkt = MagicMock()
        mock_mkt.resolve_spy_market_for_evaluation.return_value = MagicMock(final_status=_market_ready())
        mock_mkt.get_latest_chain.return_value = _chain_missing_held(snapshot_ts=now)
        mock_mkt.resolve_open_paper_option_contract.return_value = None
        app.dependency_overrides[get_market_service] = lambda: mock_mkt

        with patch("app.api.paper_strategy_one.get_settings", return_value=Settings(APP_MODE="paper")):
            db = session_local()
            try:
                repo = PaperTradeRepository(db)
                row = repo.create_trade(_open_trade_row(held=_held_sym()))
                db.commit()
                tid = int(row.id)
            finally:
                db.close()

            try:
                with TestClient(app) as client:
                    r = client.post(f"/paper/strategy/spy/strategy-1/positions/{tid}/emergency-close-unquoted")
                    self.assertEqual(r.status_code, 200, r.text)
                    body = r.json()
                    self.assertEqual(body["exit_reason"], "manual_emergency_close_unquoted")
                    self.assertAlmostEqual(body["exit_price"], 0.0)
            finally:
                app.dependency_overrides.pop(get_market_service, None)


class StrategyTwoIsolationHeldPathTests(unittest.TestCase):
    def test_emergency_unquoted_rejects_strategy_two_row(self) -> None:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        db = session_local()
        try:
            repo = PaperTradeRepository(db)
            row = PaperTrade(
                strategy_id=STRATEGY2_ID,
                symbol="SPY",
                option_symbol="SPY  260429C00500000",
                side="long",
                quantity=1,
                entry_time=datetime(2026, 4, 27, 16, 0, 0, tzinfo=timezone.utc),
                entry_price=2.0,
                status="open",
                entry_decision="candidate_call",
                evaluation_snapshot_json={},
                entry_reference_basis="option_ask",
                entry_evaluation_fingerprint="fp2",
            )
            row = repo.create_trade(row)
            svc = PaperTradeService()
            with self.assertRaises(PaperTradeError) as ctx:
                svc.emergency_close_unquoted_paper_position(
                    db,
                    paper_trade_id=int(row.id),
                    market=MagicMock(),
                    settings=Settings(),
                )
            self.assertEqual(ctx.exception.code, "paper_trade_strategy_mismatch")
        finally:
            db.close()
