from __future__ import annotations

import unittest
from collections.abc import Generator
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.paper_strategy_one import router as paper_router
from app.core.config import Settings
from app.core.database import Base, get_db
import app.models.strategy_runtime  # noqa: F401


class StrategyOneRuntimeApiTests(unittest.TestCase):
    def test_pause_resume_and_status(self) -> None:
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

        with (
            patch("app.api.paper_strategy_one.get_settings", return_value=Settings(APP_MODE="paper")),
            TestClient(app) as client,
        ):
            status_before = client.get("/paper/strategy/spy/strategy-1/runtime/status")
            self.assertEqual(status_before.status_code, 200, status_before.text)
            body = status_before.json()
            self.assertFalse(body["paused"])
            self.assertIn("scheduler_enabled", body)
            self.assertIn("market_window_open", body)
            self.assertIn("runtime_sleep_reason", body)

            paused = client.post("/paper/strategy/spy/strategy-1/runtime/pause")
            self.assertEqual(paused.status_code, 200, paused.text)
            self.assertTrue(paused.json()["paused"])

            entry_disabled = client.post("/paper/strategy/spy/strategy-1/runtime/entry-disable")
            self.assertEqual(entry_disabled.status_code, 200, entry_disabled.text)
            self.assertFalse(entry_disabled.json()["entry_enabled"])

            exit_disabled = client.post("/paper/strategy/spy/strategy-1/runtime/exit-disable")
            self.assertEqual(exit_disabled.status_code, 200, exit_disabled.text)
            self.assertFalse(exit_disabled.json()["exit_enabled"])

            entry_enabled = client.post("/paper/strategy/spy/strategy-1/runtime/entry-enable")
            self.assertEqual(entry_enabled.status_code, 200, entry_enabled.text)
            self.assertTrue(entry_enabled.json()["entry_enabled"])

            exit_enabled = client.post("/paper/strategy/spy/strategy-1/runtime/exit-enable")
            self.assertEqual(exit_enabled.status_code, 200, exit_enabled.text)
            self.assertTrue(exit_enabled.json()["exit_enabled"])

            resumed = client.post("/paper/strategy/spy/strategy-1/runtime/resume")
            self.assertEqual(resumed.status_code, 200, resumed.text)
            self.assertFalse(resumed.json()["paused"])
