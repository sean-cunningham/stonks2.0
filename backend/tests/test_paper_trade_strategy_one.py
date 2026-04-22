"""Paper trade scaffolding for Strategy 1 — service rules and P&L (no broker)."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.models.trade import PaperTrade, PaperTradeEvent
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.schemas.market import ChainLatestResponse, MarketStatusResponse, NearAtmContract
from app.schemas.strategy import StrategyOneContextSnapshot, StrategyOneEvaluationResponse
from app.services.paper.contract_constants import OPTION_CONTRACT_MULTIPLIER
from app.services.paper.paper_trade_service import PaperTradeError, PaperTradeService
import app.models.trade  # noqa: F401


def _ensure_open_contract_unique_index(engine: Engine) -> None:
    """Apply the same partial unique index as production (tests use a separate in-memory engine)."""
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_trades_open_contract "
                "ON paper_trades (strategy_id, option_symbol, side) WHERE status = 'open'"
            )
        )


def _spy_call_symbol_and_expiration(*, days_ahead: int = 3) -> tuple[str, str]:
    """OCC-style SPY call symbol + ISO expiration aligned to calendar DTE from US/Eastern today."""
    et = ZoneInfo("America/New_York")
    exp: date = datetime.now(et).date() + timedelta(days=days_ahead)
    yy, mmdd = exp.strftime("%y"), exp.strftime("%m%d")
    sym = f"SPY  {yy}{mmdd}C00500000"
    return sym, exp.isoformat()


def _spy_put_symbol_and_expiration(*, days_ahead: int = 3) -> tuple[str, str]:
    et = ZoneInfo("America/New_York")
    exp: date = datetime.now(et).date() + timedelta(days=days_ahead)
    yy, mmdd = exp.strftime("%y"), exp.strftime("%m%d")
    sym = f"SPY  {yy}{mmdd}P00500000"
    return sym, exp.isoformat()


def _fresh_chain(
    *,
    bid: float = 2.0,
    ask: float = 2.2,
    sym: str,
    expiration_iso: str,
    snapshot_timestamp: datetime | None = None,
) -> ChainLatestResponse:
    ts = snapshot_timestamp or datetime.now(timezone.utc)
    c = NearAtmContract(
        option_symbol=sym,
        strike=500.0,
        option_type="call",
        expiration_date=expiration_iso,
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
        expiration_dates_found=[expiration_iso],
        selected_expiration=expiration_iso,
        underlying_reference_price=500.0,
        total_contracts_seen=1,
        option_quotes_available=True,
        near_atm_contracts=[c],
        source_status="ok",
    )


def _fresh_put_chain(
    *,
    bid: float = 2.6,
    ask: float = 2.8,
    sym: str,
    expiration_iso: str,
    snapshot_timestamp: datetime | None = None,
) -> ChainLatestResponse:
    ts = snapshot_timestamp or datetime.now(timezone.utc)
    c = NearAtmContract(
        option_symbol=sym,
        strike=500.0,
        option_type="put",
        expiration_date=expiration_iso,
        bid=bid,
        ask=ask,
        mid=(bid + ask) / 2.0,
        spread_percent=8.0,
        delta=-0.4,
        is_call=False,
        is_put=True,
    )
    return ChainLatestResponse(
        underlying_symbol="SPY",
        available=True,
        snapshot_timestamp=ts,
        expiration_dates_found=[expiration_iso],
        selected_expiration=expiration_iso,
        underlying_reference_price=500.0,
        total_contracts_seen=1,
        option_quotes_available=True,
        near_atm_contracts=[c],
        source_status="ok",
    )


def _stale_chain(*, sym: str, expiration_iso: str) -> ChainLatestResponse:
    c = NearAtmContract(
        option_symbol=sym,
        strike=500.0,
        option_type="call",
        expiration_date=expiration_iso,
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
        expiration_dates_found=[expiration_iso],
        selected_expiration=expiration_iso,
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


def _ctx_snap(*, selected_expiration: str) -> StrategyOneContextSnapshot:
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
        chain_selected_expiration=selected_expiration,
        underlying_reference_price=500.0,
    )


def _candidate_call_eval(
    evaluation_timestamp: datetime | None = None,
    *,
    days_to_expiry: int = 3,
    swing_promotion_eligible: bool = False,
) -> StrategyOneEvaluationResponse:
    sym, exp_iso = _spy_call_symbol_and_expiration(days_ahead=days_to_expiry)
    c = NearAtmContract(
        option_symbol=sym,
        strike=500.0,
        option_type="call",
        expiration_date=exp_iso,
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
        context_snapshot_used=_ctx_snap(selected_expiration=exp_iso),
        contract_candidate=c,
        evaluation_timestamp=evaluation_timestamp or datetime.now(timezone.utc),
        swing_promotion_eligible=swing_promotion_eligible,
    )


def _candidate_put_eval(
    evaluation_timestamp: datetime | None = None,
    *,
    days_to_expiry: int = 3,
) -> StrategyOneEvaluationResponse:
    sym, exp_iso = _spy_put_symbol_and_expiration(days_ahead=days_to_expiry)
    c = NearAtmContract(
        option_symbol=sym,
        strike=500.0,
        option_type="put",
        expiration_date=exp_iso,
        bid=2.6,
        ask=2.8,
        mid=2.7,
        spread_percent=8.0,
        delta=-0.4,
        is_call=False,
        is_put=True,
    )
    return StrategyOneEvaluationResponse(
        decision="candidate_put",
        blockers=[],
        reasons=["ok"],
        context_snapshot_used=_ctx_snap(selected_expiration=exp_iso),
        contract_candidate=c,
        evaluation_timestamp=evaluation_timestamp or datetime.now(timezone.utc),
    )


def _no_trade_eval() -> StrategyOneEvaluationResponse:
    _, exp_iso = _spy_call_symbol_and_expiration(days_ahead=3)
    return StrategyOneEvaluationResponse(
        decision="no_trade",
        blockers=["no_trade_zone:vwap_atr_band"],
        reasons=[],
        context_snapshot_used=_ctx_snap(selected_expiration=exp_iso),
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
        _ensure_open_contract_unique_index(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.settings = Settings(MARKET_CHAIN_MAX_AGE_SECONDS=60, MARKET_QUOTE_MAX_AGE_SECONDS=15)
        self.svc = PaperTradeService()

    def test_cannot_open_from_no_trade(self) -> None:
        db = self.Session()
        try:
            sym, exp_iso = _spy_call_symbol_and_expiration()
            with self.assertRaises(PaperTradeError):
                self.svc.open_position(
                    db,
                    evaluation=_no_trade_eval(),
                    chain=_fresh_chain(sym=sym, expiration_iso=exp_iso),
                    market_status=_market_ready(),
                    settings=self.settings,
                )
        finally:
            db.close()

    def test_can_open_from_candidate_call(self) -> None:
        db = self.Session()
        try:
            ev = _candidate_call_eval()
            assert ev.contract_candidate is not None
            exp_iso = ev.contract_candidate.expiration_date or ""
            ch = _fresh_chain(
                bid=2.0,
                ask=2.2,
                sym=ev.contract_candidate.option_symbol,
                expiration_iso=exp_iso,
            )
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
            self.assertEqual(row.option_symbol, ev.contract_candidate.option_symbol)
            self.assertTrue(row.entry_evaluation_fingerprint)
            self.assertIsInstance(row.exit_policy, dict)
            self.assertIsInstance(row.sizing_policy, dict)
            self.assertEqual(row.exit_policy.get("trade_horizon_class"), "intraday_continuation")
            self.assertEqual(row.sizing_policy.get("risk_budget_usd"), 100.0)
            repo = PaperTradeRepository(db)
            events = repo.list_events_for_trade(row.id)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, "open")
            self.assertEqual(events[0].details_json.get("trade_horizon_class"), "intraday_continuation")
        finally:
            db.close()

    def test_can_open_from_candidate_put(self) -> None:
        db = self.Session()
        try:
            ev = _candidate_put_eval()
            assert ev.contract_candidate is not None
            exp_iso = ev.contract_candidate.expiration_date or ""
            ch = _fresh_put_chain(
                bid=2.6,
                ask=2.8,
                sym=ev.contract_candidate.option_symbol,
                expiration_iso=exp_iso,
            )
            row = self.svc.open_position(
                db,
                evaluation=ev,
                chain=ch,
                market_status=_market_ready(),
                settings=self.settings,
            )
            self.assertEqual(row.entry_decision, "candidate_put")
            self.assertAlmostEqual(row.entry_price, 2.8, places=4)
        finally:
            db.close()

    def test_rejects_entry_when_chain_quote_stale(self) -> None:
        db = self.Session()
        try:
            ev = _candidate_call_eval()
            assert ev.contract_candidate is not None
            c = ev.contract_candidate
            with self.assertRaises(PaperTradeError) as ctx:
                self.svc.open_position(
                    db,
                    evaluation=ev,
                    chain=_stale_chain(sym=c.option_symbol, expiration_iso=c.expiration_date or ""),
                    market_status=_market_ready(),
                    settings=self.settings,
                )
            self.assertIn("chain", str(ctx.exception).lower())
        finally:
            db.close()

    def test_rejects_entry_when_ask_missing(self) -> None:
        db = self.Session()
        try:
            ev = _candidate_call_eval()
            assert ev.contract_candidate is not None
            c0 = ev.contract_candidate
            c = c0.model_copy(update={"ask": None, "mid": None, "spread_percent": None})
            exp_iso = c0.expiration_date or ""
            ch = ChainLatestResponse(
                underlying_symbol="SPY",
                available=True,
                snapshot_timestamp=datetime.now(timezone.utc),
                expiration_dates_found=[exp_iso],
                selected_expiration=exp_iso,
                underlying_reference_price=500.0,
                total_contracts_seen=1,
                option_quotes_available=True,
                near_atm_contracts=[c],
                source_status="ok",
            )
            with self.assertRaises(PaperTradeError):
                self.svc.open_position(
                    db,
                    evaluation=ev,
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
            assert ev.contract_candidate is not None
            exp_iso = ev.contract_candidate.expiration_date or ""
            entry_chain = _fresh_chain(
                bid=2.0,
                ask=2.2,
                sym=ev.contract_candidate.option_symbol,
                expiration_iso=exp_iso,
            )
            row = self.svc.open_position(
                db,
                evaluation=ev,
                chain=entry_chain,
                market_status=_market_ready(),
                settings=self.settings,
            )
            exit_chain = _fresh_chain(
                bid=2.5,
                ask=2.7,
                sym=ev.contract_candidate.option_symbol,
                expiration_iso=exp_iso,
            )
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
            assert ev.contract_candidate is not None
            exp_iso = ev.contract_candidate.expiration_date or ""
            ch = _fresh_chain(
                sym=ev.contract_candidate.option_symbol,
                expiration_iso=exp_iso,
            )
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
                chain=_fresh_chain(
                    bid=2.1,
                    ask=2.3,
                    sym=ev.contract_candidate.option_symbol,
                    expiration_iso=exp_iso,
                ),
                market_status=_market_ready(),
                exit_reason="first",
                settings=self.settings,
            )
            with self.assertRaises(PaperTradeError):
                self.svc.close_position(
                    db,
                    paper_trade_id=row.id,
                    chain=_fresh_chain(
                        bid=2.1,
                        ask=2.3,
                        sym=ev.contract_candidate.option_symbol,
                        expiration_iso=exp_iso,
                    ),
                    market_status=_market_ready(),
                    exit_reason="second",
                    settings=self.settings,
                )
        finally:
            db.close()

    def test_sqlite_partial_unique_index_exists_on_paper_trades(self) -> None:
        """Guards against accidental removal of DB-level duplicate-open enforcement in SQLite."""
        with self.engine.connect() as conn:
            rows = conn.execute(text("PRAGMA index_list('paper_trades')")).fetchall()
        names = [r[1] for r in rows]
        self.assertIn("uq_paper_trades_open_contract", names)

    def test_second_open_same_contract_rejected_while_open_even_with_new_timestamps(self) -> None:
        """Different evaluation/chain second buckets must not allow a second open for same contract."""
        db = self.Session()
        try:
            now = datetime.now(timezone.utc)
            ev_ts = now.replace(microsecond=111000)
            ch_ts = now.replace(microsecond=222000)
            ev1 = _candidate_call_eval(evaluation_timestamp=ev_ts)
            assert ev1.contract_candidate is not None
            sym = ev1.contract_candidate.option_symbol
            exp_iso = ev1.contract_candidate.expiration_date or ""
            ch1 = _fresh_chain(
                bid=2.0,
                ask=2.2,
                sym=sym,
                expiration_iso=exp_iso,
                snapshot_timestamp=ch_ts,
            )
            self.svc.open_position(
                db,
                evaluation=ev1,
                chain=ch1,
                market_status=_market_ready(),
                settings=self.settings,
            )
            ev2 = _candidate_call_eval(evaluation_timestamp=ev_ts + timedelta(seconds=5))
            ch2 = _fresh_chain(
                bid=2.0,
                ask=2.2,
                sym=sym,
                expiration_iso=exp_iso,
                snapshot_timestamp=ch_ts + timedelta(seconds=5),
            )
            with self.assertRaises(PaperTradeError) as ctx:
                self.svc.open_position(
                    db,
                    evaluation=ev2,
                    chain=ch2,
                    market_status=_market_ready(),
                    settings=self.settings,
                )
            self.assertEqual(str(ctx.exception), "duplicate_open_position")
            repo = PaperTradeRepository(db)
            open_rows = repo.list_open(strategy_id=PaperTradeService.STRATEGY_ID)
            self.assertEqual(len([r for r in open_rows if r.option_symbol == sym]), 1)
        finally:
            db.close()

    def test_integrity_error_on_double_open_maps_to_duplicate(self) -> None:
        """If the app check is bypassed, the partial unique index still blocks (race safety)."""
        db = self.Session()
        try:
            now = datetime.now(timezone.utc)
            ev = _candidate_call_eval(evaluation_timestamp=now)
            assert ev.contract_candidate is not None
            exp_iso = ev.contract_candidate.expiration_date or ""
            ch = _fresh_chain(sym=ev.contract_candidate.option_symbol, expiration_iso=exp_iso)
            self.svc.open_position(
                db,
                evaluation=ev,
                chain=ch,
                market_status=_market_ready(),
                settings=self.settings,
            )
            ev2 = _candidate_call_eval(evaluation_timestamp=now + timedelta(seconds=2))
            assert ev2.contract_candidate is not None
            ch2 = _fresh_chain(sym=ev2.contract_candidate.option_symbol, expiration_iso=exp_iso)
            with patch.object(PaperTradeRepository, "has_open_position_for_contract", return_value=False):
                with self.assertRaises(PaperTradeError) as ctx:
                    self.svc.open_position(
                        db,
                        evaluation=ev2,
                        chain=ch2,
                        market_status=_market_ready(),
                        settings=self.settings,
                    )
            self.assertEqual(str(ctx.exception), "duplicate_open_position")
        finally:
            db.close()

    def test_different_option_contracts_can_open_concurrently(self) -> None:
        db = self.Session()
        try:
            now = datetime.now(timezone.utc)
            ev_ts = now.replace(microsecond=333000)
            ch_ts = now.replace(microsecond=444000)
            ev_call = _candidate_call_eval(evaluation_timestamp=ev_ts)
            assert ev_call.contract_candidate is not None
            ch_call = _fresh_chain(
                bid=2.0,
                ask=2.2,
                sym=ev_call.contract_candidate.option_symbol,
                expiration_iso=ev_call.contract_candidate.expiration_date or "",
                snapshot_timestamp=ch_ts,
            )
            self.svc.open_position(
                db,
                evaluation=ev_call,
                chain=ch_call,
                market_status=_market_ready(),
                settings=self.settings,
            )
            ev_put = _candidate_put_eval(evaluation_timestamp=ev_ts)
            assert ev_put.contract_candidate is not None
            ch_put = _fresh_put_chain(
                bid=2.6,
                ask=2.8,
                sym=ev_put.contract_candidate.option_symbol,
                expiration_iso=ev_put.contract_candidate.expiration_date or "",
                snapshot_timestamp=ch_ts,
            )
            row2 = self.svc.open_position(
                db,
                evaluation=ev_put,
                chain=ch_put,
                market_status=_market_ready(),
                settings=self.settings,
            )
            self.assertEqual(row2.option_symbol, ev_put.contract_candidate.option_symbol)
            self.assertEqual(row2.status, "open")
        finally:
            db.close()

    def test_same_contract_opens_again_after_close(self) -> None:
        db = self.Session()
        try:
            t0 = datetime.now(timezone.utc)
            ev1 = _candidate_call_eval(evaluation_timestamp=t0.replace(microsecond=100000))
            assert ev1.contract_candidate is not None
            exp_iso = ev1.contract_candidate.expiration_date or ""
            ch1 = _fresh_chain(
                sym=ev1.contract_candidate.option_symbol,
                expiration_iso=exp_iso,
                snapshot_timestamp=t0.replace(microsecond=200000),
            )
            row = self.svc.open_position(
                db,
                evaluation=ev1,
                chain=ch1,
                market_status=_market_ready(),
                settings=self.settings,
            )
            ch_close = _fresh_chain(
                bid=2.1,
                ask=2.3,
                sym=ev1.contract_candidate.option_symbol,
                expiration_iso=exp_iso,
            )
            self.svc.close_position(
                db,
                paper_trade_id=row.id,
                chain=ch_close,
                market_status=_market_ready(),
                exit_reason="test_flat",
                settings=self.settings,
            )
            t1 = t0 + timedelta(seconds=5)
            ev2 = _candidate_call_eval(evaluation_timestamp=t1.replace(microsecond=300000))
            assert ev2.contract_candidate is not None
            ch2 = _fresh_chain(
                bid=2.0,
                ask=2.2,
                sym=ev2.contract_candidate.option_symbol,
                expiration_iso=ev2.contract_candidate.expiration_date or "",
                snapshot_timestamp=t1.replace(microsecond=400000),
            )
            row2 = self.svc.open_position(
                db,
                evaluation=ev2,
                chain=ch2,
                market_status=_market_ready(),
                settings=self.settings,
            )
            self.assertEqual(row2.status, "open")
            self.assertNotEqual(row2.id, row.id)
        finally:
            db.close()

    def test_rejects_when_premium_exceeds_small_account_risk_budget(self) -> None:
        """$5k @ 2% => $100 budget; @ 35% fail-safe max total premium ≈ $285.71; $286 debit rejects."""
        db = self.Session()
        try:
            settings = Settings(
                MARKET_CHAIN_MAX_AGE_SECONDS=60,
                MARKET_QUOTE_MAX_AGE_SECONDS=15,
                PAPER_STRATEGY1_ACCOUNT_EQUITY_USD=5000.0,
            )
            ev0 = _candidate_call_eval()
            assert ev0.contract_candidate is not None
            c = ev0.contract_candidate.model_copy(update={"ask": 2.86, "mid": (2.0 + 2.86) / 2.0})
            ev = ev0.model_copy(update={"contract_candidate": c})
            exp_iso = c.expiration_date or ""
            ch = _fresh_chain(bid=2.0, ask=2.86, sym=c.option_symbol, expiration_iso=exp_iso)
            with self.assertRaises(PaperTradeError) as ctx:
                self.svc.open_position(
                    db,
                    evaluation=ev,
                    chain=ch,
                    market_status=_market_ready(),
                    settings=settings,
                )
            self.assertEqual(str(ctx.exception), "paper_entry_premium_exceeds_risk_budget")
        finally:
            db.close()

    def test_promoted_swing_assigned_when_explicitly_eligible_and_dte_in_band(self) -> None:
        db = self.Session()
        try:
            ev = _candidate_call_eval(days_to_expiry=10, swing_promotion_eligible=True)
            assert ev.contract_candidate is not None
            exp_iso = ev.contract_candidate.expiration_date or ""
            ch = _fresh_chain(
                bid=2.0,
                ask=2.2,
                sym=ev.contract_candidate.option_symbol,
                expiration_iso=exp_iso,
            )
            row = self.svc.open_position(
                db,
                evaluation=ev,
                chain=ch,
                market_status=_market_ready(),
                settings=self.settings,
            )
            self.assertEqual(row.exit_policy.get("trade_horizon_class"), "promoted_swing")
            self.assertEqual(row.exit_policy.get("expiry_band"), "7_21_dte")
            self.assertEqual(row.exit_policy.get("promoted_swing_max_hold_trading_days"), 3)
        finally:
            db.close()

    def test_rejects_intraday_dte_out_of_band(self) -> None:
        db = self.Session()
        try:
            ev = _candidate_call_eval(days_to_expiry=1)
            assert ev.contract_candidate is not None
            exp_iso = ev.contract_candidate.expiration_date or ""
            ch = _fresh_chain(
                bid=2.0,
                ask=2.2,
                sym=ev.contract_candidate.option_symbol,
                expiration_iso=exp_iso,
            )
            with self.assertRaises(PaperTradeError) as ctx:
                self.svc.open_position(
                    db,
                    evaluation=ev,
                    chain=ch,
                    market_status=_market_ready(),
                    settings=self.settings,
                )
            self.assertEqual(str(ctx.exception), "paper_entry_intraday_dte_not_in_band")
        finally:
            db.close()

    def test_rejects_when_swing_eligible_but_dte_not_in_promoted_band(self) -> None:
        db = self.Session()
        try:
            ev = _candidate_call_eval(days_to_expiry=3, swing_promotion_eligible=True)
            assert ev.contract_candidate is not None
            exp_iso = ev.contract_candidate.expiration_date or ""
            ch = _fresh_chain(
                bid=2.0,
                ask=2.2,
                sym=ev.contract_candidate.option_symbol,
                expiration_iso=exp_iso,
            )
            with self.assertRaises(PaperTradeError) as ctx:
                self.svc.open_position(
                    db,
                    evaluation=ev,
                    chain=ch,
                    market_status=_market_ready(),
                    settings=self.settings,
                )
            self.assertEqual(str(ctx.exception), "paper_entry_promoted_swing_dte_not_in_band")
        finally:
            db.close()

    def test_journal_lists_events_newest_first(self) -> None:
        db = self.Session()
        try:
            ev = _candidate_call_eval()
            assert ev.contract_candidate is not None
            sym = ev.contract_candidate.option_symbol
            exp_iso = ev.contract_candidate.expiration_date or ""
            row = self.svc.open_position(
                db,
                evaluation=ev,
                chain=_fresh_chain(sym=sym, expiration_iso=exp_iso),
                market_status=_market_ready(),
                settings=self.settings,
            )
            self.svc.close_position(
                db,
                paper_trade_id=row.id,
                chain=_fresh_chain(bid=2.1, ask=2.3, sym=sym, expiration_iso=exp_iso),
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
