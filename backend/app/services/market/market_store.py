from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.repositories.market_repository import MarketRepository
from app.schemas.market import ChainLatestResponse, MarketStatusResponse, QuoteLatestResponse, RefreshResponse
from app.services.broker.tastytrade_auth import BrokerAuthError, TastytradeAuthService
from app.services.broker.tastytrade_market_data import (
    ChainSummaryNormalized,
    MarketDataError,
    TastytradeMarketDataService,
    UnderlyingQuoteNormalized,
)
from app.services.market.market_status import compute_market_readiness

logger = logging.getLogger(__name__)


@dataclass
class RefreshResult:
    """Refresh outcome flags for quote and chain."""

    quote_refreshed: bool
    chain_refreshed: bool
    source_status: str


class MarketStoreService:
    """Coordinates fetch, normalize, persist, and status output for SPY market data."""

    def __init__(self, db: Session, settings: Settings) -> None:
        self._db = db
        self._settings = settings
        self._repo = MarketRepository(db)
        self._auth = TastytradeAuthService(settings)
        self._market_data = TastytradeMarketDataService(settings, self._auth)

    def refresh_spy(self) -> RefreshResponse:
        """Refresh quote and chain from broker and return status response."""
        latest = self._repo.get_latest_snapshot("SPY")
        quote: UnderlyingQuoteNormalized | None = None
        chain: ChainSummaryNormalized | None = None
        source_status = "ok"
        quote_ok = False
        chain_ok = False

        try:
            quote = self._market_data.fetch_spy_quote()
            quote_ok = True
        except (BrokerAuthError, MarketDataError) as exc:
            source_status = str(exc)
            logger.warning("SPY quote refresh failed: %s", source_status)

        reference_price = quote.mid if quote and quote.mid is not None else quote.last if quote else None
        try:
            chain = self._market_data.fetch_spy_option_chain(reference_price)
            chain_ok = True
        except (BrokerAuthError, MarketDataError) as exc:
            source_status = str(exc)
            logger.warning("SPY chain refresh failed: %s", source_status)

        if latest is None:
            base_snapshot_time = datetime.now(timezone.utc)
        else:
            base_snapshot_time = latest.snapshot_time

        quote_time = quote.quote_timestamp if quote else base_snapshot_time
        chain_time = chain.snapshot_timestamp if chain else latest.chain_snapshot_time if latest else None

        now = datetime.now(timezone.utc)
        quote_age = max((now - quote_time).total_seconds(), 0.0) if quote_ok else None
        chain_age = max((now - chain_time).total_seconds(), 0.0) if chain_ok and chain_time else None

        snapshot = self._repo.upsert_latest_snapshot(
            symbol="SPY",
            snapshot_time=quote_time,
            chain_snapshot_time=chain_time,
            underlying_bid=quote.bid if quote else latest.underlying_bid if latest else None,
            underlying_ask=quote.ask if quote else latest.underlying_ask if latest else None,
            underlying_mid=quote.mid if quote else latest.underlying_mid if latest else None,
            underlying_last=quote.last if quote else latest.underlying_last if latest else None,
            quote_age_seconds=quote_age,
            chain_age_seconds=chain_age,
            chain_contract_count=(
                chain.total_contracts_seen if chain else latest.chain_contract_count if latest else None
            ),
            nearest_expiration=(
                chain.selected_expiration if chain else latest.nearest_expiration if latest else None
            ),
            atm_reference_price=(
                chain.underlying_reference_price if chain else latest.atm_reference_price if latest else None
            ),
            near_atm_contracts_json=(
                chain.near_atm_contracts if chain else latest.near_atm_contracts_json if latest else None
            ),
            is_data_fresh=False,
            data_source_status="ok" if quote_ok and chain_ok else source_status,
            raw_quote_available=quote_ok or bool(latest.raw_quote_available if latest else False),
            raw_chain_available=chain_ok or bool(latest.raw_chain_available if latest else False),
        )

        readiness = compute_market_readiness(snapshot, self._settings, now)
        snapshot.is_data_fresh = readiness.market_ready
        self._db.add(snapshot)
        self._db.commit()
        return RefreshResponse(
            refreshed=quote_ok or chain_ok,
            quote_refreshed=quote_ok,
            chain_refreshed=chain_ok,
            status=MarketStatusResponse(**readiness.__dict__),
        )

    def get_spy_status(self) -> MarketStatusResponse:
        """Return current computed market readiness for SPY."""
        snapshot = self._repo.get_latest_snapshot("SPY")
        readiness = compute_market_readiness(snapshot, self._settings)
        return MarketStatusResponse(**readiness.__dict__)

    def get_latest_quote(self) -> QuoteLatestResponse:
        """Return latest normalized quote or degraded unavailable response."""
        snapshot = self._repo.get_latest_snapshot("SPY")
        if snapshot is None or not snapshot.raw_quote_available:
            status = self.get_spy_status()
            return QuoteLatestResponse(
                symbol="SPY",
                available=False,
                degraded_reason=status.block_reason,
                source_status=status.source_status,
            )
        return QuoteLatestResponse(
            symbol=snapshot.symbol,
            available=True,
            bid=snapshot.underlying_bid,
            ask=snapshot.underlying_ask,
            mid=snapshot.underlying_mid,
            last=snapshot.underlying_last,
            quote_timestamp=snapshot.snapshot_time,
            source_status=snapshot.data_source_status,
        )

    def get_latest_chain(self) -> ChainLatestResponse:
        """Return latest normalized chain summary or degraded unavailable response."""
        snapshot = self._repo.get_latest_snapshot("SPY")
        if snapshot is None or not snapshot.raw_chain_available:
            status = self.get_spy_status()
            return ChainLatestResponse(
                underlying_symbol="SPY",
                available=False,
                degraded_reason=status.block_reason,
                source_status=status.source_status,
            )

        contracts = snapshot.near_atm_contracts_json or []
        expirations = [snapshot.nearest_expiration] if snapshot.nearest_expiration else []
        return ChainLatestResponse(
            underlying_symbol=snapshot.symbol,
            available=True,
            snapshot_timestamp=snapshot.chain_snapshot_time,
            expiration_dates_found=expirations,
            selected_expiration=snapshot.nearest_expiration,
            underlying_reference_price=snapshot.atm_reference_price,
            total_contracts_seen=snapshot.chain_contract_count,
            near_atm_contracts=contracts,
            source_status=snapshot.data_source_status,
        )

