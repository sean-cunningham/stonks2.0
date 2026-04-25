from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.schemas.market import ChainLatestResponse, MarketStatusResponse, NearAtmContract
from app.schemas.strategy import StrategyOneContextSnapshot, StrategyOneEvaluationResponse
from app.services.paper.paper_trade_service import PaperTradeError, PaperTradeService
from app.services.paper.strategy_two_paper_trade_service import StrategyTwoPaperTradeService


def _ensure_open_contract_unique_index(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_paper_trades_open_contract "
                "ON paper_trades (strategy_id, option_symbol, side) WHERE status = 'open'"
            )
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


def _chain_for(option_symbol: str, expiration_iso: str, *, bid: float = 2.0, ask: float = 2.2) -> ChainLatestResponse:
    c = NearAtmContract(
        option_symbol=option_symbol,
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
        snapshot_timestamp=datetime.now(timezone.utc),
        expiration_dates_found=[expiration_iso],
        selected_expiration=expiration_iso,
        underlying_reference_price=500.0,
        total_contracts_seen=1,
        option_quotes_available=True,
        near_atm_contracts=[c],
        source_status="ok",
    )


def _eval_for(option_symbol: str, expiration_iso: str) -> StrategyOneEvaluationResponse:
    candidate = NearAtmContract(
        option_symbol=option_symbol,
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
    context = StrategyOneContextSnapshot(
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
        chain_selected_expiration=expiration_iso,
        underlying_reference_price=500.0,
    )
    return StrategyOneEvaluationResponse(
        decision="candidate_call",
        blockers=[],
        reasons=["ok"],
        context_snapshot_used=context,
        contract_candidate=candidate,
        evaluation_timestamp=datetime.now(timezone.utc),
    )


class PaperTradeIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        _ensure_open_contract_unique_index(self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.settings = Settings(
            MARKET_CHAIN_MAX_AGE_SECONDS=60,
            MARKET_QUOTE_MAX_AGE_SECONDS=15,
            PAPER_STRATEGY1_ACCOUNT_EQUITY_USD=5000.0,
            PAPER_STRATEGY2_ACCOUNT_EQUITY_USD=5000.0,
        )

    def test_open_rows_and_journal_are_scoped_by_strategy_id(self) -> None:
        db = self.Session()
        try:
            strategy_one = PaperTradeService()
            strategy_two = StrategyTwoPaperTradeService()
            expiration_iso_strategy_two = datetime.now(timezone.utc).date().isoformat()
            expiration_iso_strategy_one = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
            row_one = strategy_one.open_position(
                db,
                evaluation=_eval_for("SPY  260428C00500000", expiration_iso_strategy_one),
                chain=_chain_for("SPY  260428C00500000", expiration_iso_strategy_one),
                market_status=_market_ready(),
                settings=self.settings,
            )
            row_two = strategy_two.open_position(
                db,
                evaluation=_eval_for("SPY  260425C00501000", expiration_iso_strategy_two),
                chain=_chain_for("SPY  260425C00501000", expiration_iso_strategy_two, bid=0.45, ask=0.50),
                market_status=_market_ready(),
                settings=self.settings,
            )
            repo = PaperTradeRepository(db)
            open_one = repo.list_open(strategy_id=strategy_one.STRATEGY_ID)
            open_two = repo.list_open(strategy_id=strategy_two.STRATEGY_ID)
            self.assertEqual([r.id for r in open_one], [row_one.id])
            self.assertEqual([r.id for r in open_two], [row_two.id])
            journal_one = repo.list_journal(strategy_id=strategy_one.STRATEGY_ID, limit=20)
            journal_two = repo.list_journal(strategy_id=strategy_two.STRATEGY_ID, limit=20)
            self.assertEqual(len(journal_one), 1)
            self.assertEqual(len(journal_two), 1)
        finally:
            db.close()

    def test_close_rejects_cross_strategy_trade_id(self) -> None:
        db = self.Session()
        try:
            strategy_one = PaperTradeService()
            strategy_two = StrategyTwoPaperTradeService()
            expiration_iso_strategy_one = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
            row_one = strategy_one.open_position(
                db,
                evaluation=_eval_for("SPY  260428C00502000", expiration_iso_strategy_one),
                chain=_chain_for("SPY  260428C00502000", expiration_iso_strategy_one),
                market_status=_market_ready(),
                settings=self.settings,
            )
            with self.assertRaises(PaperTradeError) as ctx:
                strategy_two.close_position(
                    db,
                    paper_trade_id=row_one.id,
                    chain=_chain_for("SPY  260428C00502000", expiration_iso_strategy_one),
                    market_status=_market_ready(),
                    exit_reason="cross_strategy_test",
                    settings=self.settings,
                )
            self.assertEqual(str(ctx.exception), "paper_trade_strategy_mismatch")
        finally:
            db.close()

