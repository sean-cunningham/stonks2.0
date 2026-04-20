from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MarketSnapshot(Base):
    """Latest market and chain freshness summary for a symbol."""

    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    snapshot_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    chain_snapshot_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    underlying_bid: Mapped[float | None] = mapped_column(Float, nullable=True)
    underlying_ask: Mapped[float | None] = mapped_column(Float, nullable=True)
    underlying_mid: Mapped[float | None] = mapped_column(Float, nullable=True)
    underlying_last: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote_age_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    chain_age_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    chain_contract_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expiration_dates_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    nearest_expiration: Mapped[str | None] = mapped_column(String(16), nullable=True)
    atm_reference_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    near_atm_contracts_json: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    is_data_fresh: Mapped[bool] = mapped_column(Boolean, default=False)
    data_source_status: Mapped[str] = mapped_column(String(64), default="not_ready")
    raw_quote_available: Mapped[bool] = mapped_column(Boolean, default=False)
    raw_chain_available: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
