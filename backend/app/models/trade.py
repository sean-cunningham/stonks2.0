from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PaperTrade(Base):
    """Paper option position (single contract, BTO/STC references; no broker).

    Startup DDL (SQLite/PostgreSQL) adds a partial unique index on
    (strategy_id, option_symbol, side) WHERE status = 'open' so only one open row
    per contract is possible at the DB level; see ``ensure_paper_trade_open_contract_unique_index``.
    """

    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    strategy_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    option_symbol: Mapped[str] = mapped_column(String(64), index=True)
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[int] = mapped_column(Integer)
    entry_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    # Per-share premium at entry (ask for long BTO) and exit (bid for long STC).
    entry_price: Mapped[float] = mapped_column(Float)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="open")
    entry_decision: Mapped[str] = mapped_column(String(16), default="")
    evaluation_snapshot_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    entry_reference_basis: Mapped[str] = mapped_column(String(32), default="option_ask")
    exit_reference_basis: Mapped[str | None] = mapped_column(String(32), nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    entry_evaluation_fingerprint: Mapped[str] = mapped_column(String(256), default="", index=True)
    exit_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sizing_policy: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    active_stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_unrealized_pnl_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    profit_lock_stage: Mapped[str | None] = mapped_column(String(32), nullable=True, default="none")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class PaperTradeEvent(Base):
    """Append-only paper trade lifecycle events for journal export."""

    __tablename__ = "paper_trade_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    paper_trade_id: Mapped[int] = mapped_column(Integer, ForeignKey("paper_trades.id"), index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_type: Mapped[str] = mapped_column(String(16), index=True)
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StrategyDashboardBaseline(Base):
    """Per-strategy dashboard reset anchor for stats/charts while preserving full trade history."""

    __tablename__ = "strategy_dashboard_baselines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    strategy_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    reset_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    baseline_cash: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
