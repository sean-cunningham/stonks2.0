from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.strategy_runtime import StrategyRuntimeCycleLog, StrategyRuntimeState


class StrategyRuntimeRepository:
    """Persistence adapter for strategy runtime state and cycle logs."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_or_create_state(self, *, strategy_id: str) -> StrategyRuntimeState:
        stmt = select(StrategyRuntimeState).where(StrategyRuntimeState.strategy_id == strategy_id).limit(1)
        row = self._db.scalar(stmt)
        if row is not None:
            return row
        row = StrategyRuntimeState(strategy_id=strategy_id)
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def save_state(self, row: StrategyRuntimeState) -> StrategyRuntimeState:
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def append_cycle_log(self, row: StrategyRuntimeCycleLog) -> StrategyRuntimeCycleLog:
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def list_cycle_logs(self, *, strategy_id: str, limit: int = 50) -> list[StrategyRuntimeCycleLog]:
        stmt = (
            select(StrategyRuntimeCycleLog)
            .where(StrategyRuntimeCycleLog.strategy_id == strategy_id)
            .order_by(StrategyRuntimeCycleLog.started_at.desc(), StrategyRuntimeCycleLog.id.desc())
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())
