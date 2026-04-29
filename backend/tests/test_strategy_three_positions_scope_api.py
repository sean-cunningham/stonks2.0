from __future__ import annotations

import unittest
from collections.abc import Generator
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.paper_strategy_three import router as paper_router
from app.core.database import Base, get_db
from app.services.paper.strategy_three_paper_trade_service import StrategyThreePaperTradeService


class StrategyThreePositionsScopeApiTests(unittest.TestCase):
    def test_positions_and_journal_endpoints_are_strategy_scoped(self) -> None:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=engine)
        session_local = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        def override_get_db() -> Generator:
            db = session_local()
            try:
                yield db
            finally:
                db.close()

        app = FastAPI()
        app.include_router(paper_router)
        app.dependency_overrides[get_db] = override_get_db

        repo = MagicMock()
        repo.list_open.return_value = []
        repo.list_closed.return_value = []
        repo.list_journal.return_value = []

        with (
            patch("app.api.paper_strategy_three.PaperTradeRepository", return_value=repo),
            TestClient(app) as client,
        ):
            r1 = client.get("/paper/strategy/spy/strategy-3/positions/open")
            r2 = client.get("/paper/strategy/spy/strategy-3/positions/closed")
            r3 = client.get("/paper/strategy/spy/strategy-3/journal")

        self.assertEqual(r1.status_code, 200, r1.text)
        self.assertEqual(r2.status_code, 200, r2.text)
        self.assertEqual(r3.status_code, 200, r3.text)
        repo.list_open.assert_called_once_with(strategy_id=StrategyThreePaperTradeService.STRATEGY_ID)
        repo.list_closed.assert_called_once()
        self.assertEqual(repo.list_closed.call_args.kwargs.get("strategy_id"), StrategyThreePaperTradeService.STRATEGY_ID)
        repo.list_journal.assert_called_once()
        self.assertEqual(repo.list_journal.call_args.kwargs.get("strategy_id"), StrategyThreePaperTradeService.STRATEGY_ID)
