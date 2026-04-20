"""Persistence for intraday bars."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.bars import IntradayBar


class BarsRepository:
    """CRUD helpers for IntradayBar rows."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def list_recent_bars(
        self,
        *,
        symbol: str,
        timeframe: str,
        limit: int = 120,
    ) -> list[IntradayBar]:
        """Return most recent bars for symbol/timeframe, oldest first within the window."""
        stmt = (
            select(IntradayBar)
            .where(IntradayBar.symbol == symbol, IntradayBar.timeframe == timeframe)
            .order_by(IntradayBar.bar_time.desc())
            .limit(limit)
        )
        rows = list(self._db.scalars(stmt).all())
        rows.reverse()
        return rows

    def upsert_bars(self, bars: list[IntradayBar]) -> int:
        """Insert or update bars by (symbol, timeframe, bar_time)."""
        count = 0
        for bar in bars:
            existing = self._db.scalar(
                select(IntradayBar).where(
                    IntradayBar.symbol == bar.symbol,
                    IntradayBar.timeframe == bar.timeframe,
                    IntradayBar.bar_time == bar.bar_time,
                )
            )
            if existing is None:
                self._db.add(
                    IntradayBar(
                        symbol=bar.symbol,
                        timeframe=bar.timeframe,
                        bar_time=bar.bar_time,
                        open=bar.open,
                        high=bar.high,
                        low=bar.low,
                        close=bar.close,
                        volume=bar.volume,
                        source_status=bar.source_status,
                    )
                )
            else:
                existing.open = bar.open
                existing.high = bar.high
                existing.low = bar.low
                existing.close = bar.close
                existing.volume = bar.volume
                existing.source_status = bar.source_status
            count += 1
        self._db.commit()
        return count
