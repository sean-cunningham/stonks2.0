from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.trade import StrategyDashboardBaseline


class StrategyDashboardBaselineRepository:
    """Persistence for per-strategy dashboard reset baseline state."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_for_strategy(self, *, strategy_id: str) -> StrategyDashboardBaseline | None:
        stmt = select(StrategyDashboardBaseline).where(StrategyDashboardBaseline.strategy_id == strategy_id).limit(1)
        return self._db.scalar(stmt)

    def upsert_for_strategy(
        self,
        *,
        strategy_id: str,
        reset_at: datetime,
        baseline_cash: float,
    ) -> StrategyDashboardBaseline:
        row = self.get_for_strategy(strategy_id=strategy_id)
        if row is None:
            row = StrategyDashboardBaseline(
                strategy_id=strategy_id,
                reset_at=reset_at,
                baseline_cash=float(baseline_cash),
            )
        else:
            row.reset_at = reset_at
            row.baseline_cash = float(baseline_cash)
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row
