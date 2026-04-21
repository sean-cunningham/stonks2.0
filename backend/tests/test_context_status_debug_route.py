"""Integration check: GET /context/spy/status/debug is wired and returns staleness fields."""

from __future__ import annotations

import unittest
from collections.abc import Generator

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.context import router as context_router
from app.core.config import Settings, get_settings
from app.core.database import Base, get_db
import app.models.bars  # noqa: F401 — register IntradayBar on Base.metadata


class ContextStatusDebugRouteTests(unittest.TestCase):
    def test_status_debug_returns_required_fields(self) -> None:
        # StaticPool: default :memory: opens a new empty DB per connection; CREATE and SELECT must share one DB.
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

        def override_get_db() -> Generator:
            db = SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app = FastAPI()
        app.include_router(context_router)
        app.dependency_overrides[get_db] = override_get_db
        app.dependency_overrides[get_settings] = lambda: Settings()

        required = {
            "symbol",
            "latest_1m_bar_time",
            "latest_5m_bar_time",
            "expected_latest_completed_5m_start",
            "stale_5m_reference_time",
            "stale_5m_seconds",
            "stale_5m_boolean",
            "block_reason",
            "block_reason_analysis",
        }

        with TestClient(app) as client:
            response = client.get("/context/spy/status/debug")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertTrue(required.issubset(set(data.keys())), f"missing keys: {required - set(data.keys())}")
        self.assertIsInstance(data["block_reason"], str)
        self.assertIsInstance(data["block_reason_analysis"], str)
        self.assertIsInstance(data["stale_5m_boolean"], bool)


if __name__ == "__main__":
    unittest.main()
