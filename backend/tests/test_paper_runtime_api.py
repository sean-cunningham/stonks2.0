from __future__ import annotations

import unittest
from collections.abc import Generator
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.paper_runtime import router as runtime_router
from app.core.config import Settings
from app.core.database import Base, get_db
import app.models.strategy_runtime  # noqa: F401


class PaperRuntimeApiTests(unittest.TestCase):
    def test_pause_all_and_resume_all(self) -> None:
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
        app.include_router(runtime_router)
        app.dependency_overrides[get_db] = override_get_db

        with (
            patch("app.api.paper_runtime.get_settings", return_value=Settings(APP_MODE="paper")),
            TestClient(app) as client,
        ):
            paused = client.post("/paper/runtime/pause-all")
            self.assertEqual(paused.status_code, 200, paused.text)
            pb = paused.json()
            self.assertEqual(pb["action"], "pause_all")
            self.assertEqual(len(pb["strategies"]), 2)
            self.assertTrue(all(s["paused"] for s in pb["strategies"]))

            resumed = client.post("/paper/runtime/resume-all")
            self.assertEqual(resumed.status_code, 200, resumed.text)
            rb = resumed.json()
            self.assertEqual(rb["action"], "resume_all")
            self.assertEqual(len(rb["strategies"]), 2)
            self.assertTrue(all(not s["paused"] for s in rb["strategies"]))

