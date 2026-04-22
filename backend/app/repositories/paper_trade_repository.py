from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.trade import PaperTrade, PaperTradeEvent


class PaperTradeRepository:
    """Persistence for paper trades and journal events."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def create_trade(self, row: PaperTrade) -> PaperTrade:
        self._db.add(row)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            raise
        self._db.refresh(row)
        return row

    def append_event(self, event: PaperTradeEvent) -> PaperTradeEvent:
        self._db.add(event)
        self._db.commit()
        self._db.refresh(event)
        return event

    def get_trade(self, trade_id: int) -> PaperTrade | None:
        return self._db.get(PaperTrade, trade_id)

    def has_open_position_for_contract(
        self,
        *,
        strategy_id: str,
        option_symbol: str,
        side: str,
    ) -> bool:
        """True if a paper trade is already open for this strategy/contract/side (any fingerprint)."""
        stmt = (
            select(PaperTrade.id)
            .where(
                PaperTrade.strategy_id == strategy_id,
                PaperTrade.option_symbol == option_symbol,
                PaperTrade.side == side,
                PaperTrade.status == "open",
            )
            .limit(1)
        )
        return self._db.scalar(stmt) is not None

    def list_open(self, *, strategy_id: str) -> list[PaperTrade]:
        stmt = (
            select(PaperTrade)
            .where(PaperTrade.strategy_id == strategy_id, PaperTrade.status == "open")
            .order_by(PaperTrade.entry_time.desc())
        )
        return list(self._db.scalars(stmt).all())

    def list_closed(self, *, strategy_id: str, limit: int = 100) -> list[PaperTrade]:
        stmt = (
            select(PaperTrade)
            .where(PaperTrade.strategy_id == strategy_id, PaperTrade.status == "closed")
            .order_by(PaperTrade.exit_time.desc(), PaperTrade.id.desc())
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def list_closed_chronological(self, *, strategy_id: str, limit: int = 1000) -> list[PaperTrade]:
        stmt = (
            select(PaperTrade)
            .where(PaperTrade.strategy_id == strategy_id, PaperTrade.status == "closed")
            .order_by(PaperTrade.exit_time.asc(), PaperTrade.id.asc())
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def list_events_for_trade(self, paper_trade_id: int) -> list[PaperTradeEvent]:
        stmt = (
            select(PaperTradeEvent)
            .where(PaperTradeEvent.paper_trade_id == paper_trade_id)
            .order_by(PaperTradeEvent.event_time.asc())
        )
        return list(self._db.scalars(stmt).all())

    def list_journal(self, *, strategy_id: str, limit: int = 200) -> list[PaperTradeEvent]:
        stmt = (
            select(PaperTradeEvent)
            .join(PaperTrade, PaperTradeEvent.paper_trade_id == PaperTrade.id)
            .where(PaperTrade.strategy_id == strategy_id)
            .order_by(PaperTradeEvent.event_time.desc())
            .limit(limit)
        )
        return list(self._db.scalars(stmt).all())

    def update_trade(self, row: PaperTrade) -> PaperTrade:
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(timezone.utc)
