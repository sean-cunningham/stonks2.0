from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.services.paper.strategy_one_runtime_service import get_strategy_one_runtime_coordinator
from app.services.paper.strategy_three_runtime_service import get_strategy_three_runtime_coordinator
from app.services.paper.strategy_two_runtime_service import get_strategy_two_runtime_coordinator


class StrategyRuntimeIndependenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine, autocommit=False, autoflush=False)
        self.settings = Settings(APP_MODE="paper")

    def test_strategy_one_two_three_runtime_flags_are_independent(self) -> None:
        db = self.Session()
        try:
            s1 = get_strategy_one_runtime_coordinator()
            s2 = get_strategy_two_runtime_coordinator()
            s3 = get_strategy_three_runtime_coordinator()

            s1.set_paused(db, settings=self.settings, paused=False)
            s2.set_paused(db, settings=self.settings, paused=False)
            s3.set_paused(db, settings=self.settings, paused=False)
            s1.set_runtime_flags(db, settings=self.settings, entry_enabled=True, exit_enabled=True)
            s2.set_runtime_flags(db, settings=self.settings, entry_enabled=True, exit_enabled=True)
            s3.set_runtime_flags(db, settings=self.settings, entry_enabled=True, exit_enabled=True)

            s2.set_paused(db, settings=self.settings, paused=True)
            s2.set_runtime_flags(db, settings=self.settings, entry_enabled=False, exit_enabled=True)
            s3.set_paused(db, settings=self.settings, paused=False)
            s3.set_runtime_flags(db, settings=self.settings, entry_enabled=True, exit_enabled=False)

            s1_status = s1.get_status(db, settings=self.settings)
            s2_status = s2.get_status(db, settings=self.settings)
            s3_status = s3.get_status(db, settings=self.settings)

            self.assertFalse(s1_status.paused)
            self.assertTrue(s1_status.entry_enabled)
            self.assertTrue(s1_status.exit_enabled)

            self.assertTrue(s2_status.paused)
            self.assertFalse(s2_status.entry_enabled)
            self.assertTrue(s2_status.exit_enabled)

            self.assertFalse(s3_status.paused)
            self.assertTrue(s3_status.entry_enabled)
            self.assertFalse(s3_status.exit_enabled)
        finally:
            db.close()

