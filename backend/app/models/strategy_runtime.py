from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class StrategyRuntimeState(Base):
    """Single-row runtime controls and latest cycle status for one strategy."""

    __tablename__ = "strategy_runtime_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    strategy_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    entry_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    exit_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_cycle_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_cycle_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_cycle_result: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class StrategyRuntimeCycleLog(Base):
    """Append-only, narrow cycle history for observability and audit."""

    __tablename__ = "strategy_runtime_cycle_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    strategy_id: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[str] = mapped_column(String(64), index=True)
    cycle_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    had_open_position_at_start: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    notes_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
