from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Literal

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
from app.services.paper.held_option_contract_resolution import (
    HeldOptionContractResolution,
    build_near_atm_contract_for_held_direct_quote,
)

logger = logging.getLogger(__name__)


@dataclass
class RefreshResult:
    """Refresh outcome flags for quote and chain."""

    quote_refreshed: bool
    chain_refreshed: bool
    source_status: str


@dataclass(frozen=True)
class SpyMarketEvaluationResolution:
    """Market readiness for one strategy evaluation pass (observable auto-refresh)."""

    final_status: MarketStatusResponse
    market_status_source: Literal["cached", "refreshed_for_evaluation"]
    auto_refresh_attempted: bool
    auto_refresh_trigger_reason: str | None
    post_refresh_market_ready: bool
    post_refresh_block_reason: str


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
        quote: UnderlyingQuoteNormalized | None = None
        chain: ChainSummaryNormalized | None = None
        quote_reason: str | None = None
        chain_reason: str | None = None
        quote_ok = False
        chain_ok = False

        try:
            quote = self._market_data.fetch_spy_quote()
            quote_ok = True
        except (BrokerAuthError, MarketDataError) as exc:
            quote_reason = str(exc)
            logger.warning("SPY quote refresh failed: reason=%s", quote_reason)

        reference_price = quote.mid if quote and quote.mid is not None else quote.last if quote else None
        try:
            chain = self._market_data.fetch_spy_option_chain(reference_price)
            chain_ok = chain.quote_data_available
            if not chain.quote_data_available:
                chain_reason = "chain_quotes_unavailable"
        except (BrokerAuthError, MarketDataError) as exc:
            chain_reason = str(exc)
            logger.warning("SPY chain refresh failed: reason=%s", chain_reason)

        now = datetime.now(timezone.utc)
        source_status = self._build_source_status(
            quote_ok=quote_ok,
            chain_ok=chain_ok,
            quote_reason=quote_reason,
            chain_reason=chain_reason,
        )

        quote_time = quote.quote_timestamp if quote_ok and quote else None
        chain_time = chain.snapshot_timestamp if chain_ok and chain else None
        quote_age = max((now - quote_time).total_seconds(), 0.0) if quote_time else None
        chain_age = max((now - chain_time).total_seconds(), 0.0) if chain_ok and chain_time else None

        snapshot = self._repo.upsert_latest_snapshot(
            symbol="SPY",
            snapshot_time=quote_time or now,
            chain_snapshot_time=chain_time,
            underlying_bid=quote.bid if quote_ok and quote else None,
            underlying_ask=quote.ask if quote_ok and quote else None,
            underlying_mid=quote.mid if quote_ok and quote else None,
            underlying_last=quote.last if quote_ok and quote else None,
            quote_age_seconds=quote_age,
            chain_age_seconds=chain_age,
            chain_contract_count=chain.total_contracts_seen if chain_ok and chain else None,
            expiration_dates_json=chain.expiration_dates_found if chain_ok and chain else None,
            nearest_expiration=chain.selected_expiration if chain_ok and chain else None,
            atm_reference_price=chain.underlying_reference_price if chain_ok and chain else None,
            near_atm_contracts_json=chain.near_atm_contracts if chain_ok and chain else None,
            is_data_fresh=False,
            data_source_status=source_status,
            raw_quote_available=quote_ok,
            raw_chain_available=chain_ok,
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

    def resolve_spy_market_for_evaluation(self) -> SpyMarketEvaluationResolution:
        """Resolve market readiness for strategy evaluation; refresh once if cache is stale.

        ``get_spy_status`` uses wall-clock age of the last persisted snapshot. Without a
        periodic refresh job, snapshots only update at startup or manual POST /refresh,
        so they can exceed MARKET_QUOTE_MAX_AGE_SECONDS even when the feed is healthy.

        After ``refresh_spy`` commits a new row, expire ORM state so the follow-up read
        does not reuse a stale ``MarketSnapshot`` instance from this session's identity map.
        """
        pre = self.get_spy_status()
        if pre.market_ready:
            return SpyMarketEvaluationResolution(
                final_status=pre,
                market_status_source="cached",
                auto_refresh_attempted=False,
                auto_refresh_trigger_reason=None,
                post_refresh_market_ready=pre.market_ready,
                post_refresh_block_reason=pre.block_reason,
            )
        if pre.block_reason in ("stale_quote", "stale_chain", "startup_not_initialized"):
            self.refresh_spy()
            self._db.expire_all()
            post = self.get_spy_status()
            return SpyMarketEvaluationResolution(
                final_status=post,
                market_status_source="refreshed_for_evaluation",
                auto_refresh_attempted=True,
                auto_refresh_trigger_reason=pre.block_reason,
                post_refresh_market_ready=post.market_ready,
                post_refresh_block_reason=post.block_reason,
            )
        return SpyMarketEvaluationResolution(
            final_status=pre,
            market_status_source="cached",
            auto_refresh_attempted=False,
            auto_refresh_trigger_reason=None,
            post_refresh_market_ready=pre.market_ready,
            post_refresh_block_reason=pre.block_reason,
        )

    def get_spy_status_for_evaluation(self) -> MarketStatusResponse:
        """Backward-compatible: final market row after optional evaluation-time refresh."""
        return self.resolve_spy_market_for_evaluation().final_status

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

    @staticmethod
    def _pick_option_quote_map_entry(
        requested: str, quote_map: dict[str, dict[str, float | str | None]]
    ) -> dict[str, float | str | None] | None:
        """Match DXLink ``eventSymbol`` keys to the requested OCC/streamer string (spacing may differ)."""
        return TastytradeMarketDataService.pick_quote_map_entry(requested, quote_map)

    def resolve_open_paper_option_contract(
        self,
        *,
        option_symbol: str,
        chain: ChainLatestResponse,
    ) -> HeldOptionContractResolution | None:
        """Resolve bid/ask for an open leg: prefer chain near-ATM row, else direct DXLink for exact symbol."""
        if chain.available and chain.option_quotes_available:
            for c in chain.near_atm_contracts:
                if c.option_symbol == option_symbol:
                    ts = chain.snapshot_timestamp or datetime.now(timezone.utc)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    return HeldOptionContractResolution(contract=c, quote_timestamp=ts, source="chain_near_atm")
        try:
            _, quote_map = self._market_data.fetch_direct_option_quotes([option_symbol])
            raw = self._pick_option_quote_map_entry(option_symbol, quote_map)
            if raw is None:
                return None
            bid = TastytradeMarketDataService._to_float(raw.get("bid"))
            ask = TastytradeMarketDataService._to_float(raw.get("ask"))
            c = build_near_atm_contract_for_held_direct_quote(option_symbol, bid=bid, ask=ask)
            ts = datetime.now(timezone.utc)
            return HeldOptionContractResolution(contract=c, quote_timestamp=ts, source="direct_dxlink")
        except (BrokerAuthError, MarketDataError, OSError, RuntimeError) as exc:
            logger.warning("Direct option quote fetch failed symbol=%s err=%s", option_symbol, exc)
            return None

    def get_latest_chain(self) -> ChainLatestResponse:
        """Return latest normalized chain summary or degraded unavailable response."""
        snapshot = self._repo.get_latest_snapshot("SPY")
        if snapshot is None or not snapshot.raw_chain_available:
            status = self.get_spy_status()
            return ChainLatestResponse(
                underlying_symbol="SPY",
                available=False,
                degraded_reason=status.block_reason,
                option_quotes_available=False,
                source_status=status.source_status,
            )

        contracts = snapshot.near_atm_contracts_json or []
        expirations = snapshot.expiration_dates_json or []
        return ChainLatestResponse(
            underlying_symbol=snapshot.symbol,
            available=True,
            snapshot_timestamp=snapshot.chain_snapshot_time,
            expiration_dates_found=expirations,
            selected_expiration=snapshot.nearest_expiration,
            underlying_reference_price=snapshot.atm_reference_price,
            total_contracts_seen=snapshot.chain_contract_count,
            option_quotes_available=True,
            near_atm_contracts=contracts,
            source_status=snapshot.data_source_status,
        )

    @staticmethod
    def _build_source_status(
        *,
        quote_ok: bool,
        chain_ok: bool,
        quote_reason: str | None,
        chain_reason: str | None,
    ) -> str:
        if quote_ok and chain_ok:
            return "ok"
        if quote_ok and not chain_ok:
            return f"quote_ok_chain_failed:{chain_reason or 'unknown'}"
        if chain_ok and not quote_ok:
            return f"quote_failed_chain_ok:{quote_reason or 'unknown'}"
        return f"quote_failed_chain_failed:{quote_reason or 'unknown'}|{chain_reason or 'unknown'}"

