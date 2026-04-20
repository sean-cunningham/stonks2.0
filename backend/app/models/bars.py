"""Persisted intraday OHLCV bars for context (SPY)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class IntradayBar(Base):
    """One OHLCV bar for a symbol and timeframe (1m or 5m)."""

    __tablename__ = "intraday_bars"
    __table_args__ = (UniqueConstraint("symbol", "timeframe", "bar_time", name="uq_intraday_bar_symbol_tf_time"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    timeframe: Mapped[str] = mapped_column(String(8), index=True)  # "1m" | "5m"
    bar_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    open: Mapped[float] = mapped_column(Float)
    high: Mapped[float] = mapped_column(Float)
    low: Mapped[float] = mapped_column(Float)
    close: Mapped[float] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_status: Mapped[str] = mapped_column(String(64), default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
