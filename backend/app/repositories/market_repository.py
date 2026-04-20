from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.market import MarketSnapshot


class MarketRepository:
    """Persistence helpers for SPY market snapshots."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def get_latest_snapshot(self, symbol: str = "SPY") -> MarketSnapshot | None:
        """Return the latest market snapshot for a symbol."""
        stmt = (
            select(MarketSnapshot)
            .where(MarketSnapshot.symbol == symbol)
            .order_by(MarketSnapshot.snapshot_time.desc(), MarketSnapshot.id.desc())
            .limit(1)
        )
        return self._db.scalar(stmt)

    def upsert_latest_snapshot(
        self,
        *,
        symbol: str,
        snapshot_time: datetime,
        chain_snapshot_time: datetime | None,
        underlying_bid: float | None,
        underlying_ask: float | None,
        underlying_mid: float | None,
        underlying_last: float | None,
        quote_age_seconds: float | None,
        chain_age_seconds: float | None,
        chain_contract_count: int | None,
        nearest_expiration: str | None,
        atm_reference_price: float | None,
        near_atm_contracts_json: list[dict] | None,
        is_data_fresh: bool,
        data_source_status: str,
        raw_quote_available: bool,
        raw_chain_available: bool,
    ) -> MarketSnapshot:
        """Create a new immutable snapshot row."""
        snapshot = MarketSnapshot(
            symbol=symbol,
            snapshot_time=snapshot_time,
            chain_snapshot_time=chain_snapshot_time,
            underlying_bid=underlying_bid,
            underlying_ask=underlying_ask,
            underlying_mid=underlying_mid,
            underlying_last=underlying_last,
            quote_age_seconds=quote_age_seconds,
            chain_age_seconds=chain_age_seconds,
            chain_contract_count=chain_contract_count,
            nearest_expiration=nearest_expiration,
            atm_reference_price=atm_reference_price,
            near_atm_contracts_json=near_atm_contracts_json,
            is_data_fresh=is_data_fresh,
            data_source_status=data_source_status,
            raw_quote_available=raw_quote_available,
            raw_chain_available=raw_chain_available,
        )
        self._db.add(snapshot)
        self._db.commit()
        self._db.refresh(snapshot)
        return snapshot

