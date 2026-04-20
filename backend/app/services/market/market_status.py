from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.core.config import Settings
from app.models.market import MarketSnapshot


@dataclass
class MarketReadiness:
    """Computed market readiness state."""

    symbol: str
    market_ready: bool
    block_reason: str
    quote_available: bool
    chain_available: bool
    quote_age_seconds: float | None
    chain_age_seconds: float | None
    quote_is_fresh: bool
    chain_is_fresh: bool
    latest_quote_time: datetime | None
    latest_chain_time: datetime | None
    source_status: str


def compute_market_readiness(
    snapshot: MarketSnapshot | None,
    settings: Settings,
    now: datetime | None = None,
) -> MarketReadiness:
    """Compute fresh/degraded status from latest snapshot."""
    current = now or datetime.now(timezone.utc)
    if snapshot is None:
        return MarketReadiness(
            symbol="SPY",
            market_ready=False,
            block_reason="startup_not_initialized",
            quote_available=False,
            chain_available=False,
            quote_age_seconds=None,
            chain_age_seconds=None,
            quote_is_fresh=False,
            chain_is_fresh=False,
            latest_quote_time=None,
            latest_chain_time=None,
            source_status="not_ready",
        )

    quote_age = _age_seconds(snapshot.snapshot_time, current) if snapshot.raw_quote_available else None
    chain_age = (
        _age_seconds(snapshot.chain_snapshot_time, current)
        if snapshot.raw_chain_available and snapshot.chain_snapshot_time is not None
        else None
    )
    quote_fresh = quote_age is not None and quote_age <= settings.MARKET_QUOTE_MAX_AGE_SECONDS
    chain_fresh = chain_age is not None and chain_age <= settings.MARKET_CHAIN_MAX_AGE_SECONDS
    quote_available = bool(snapshot.raw_quote_available)
    chain_available = bool(snapshot.raw_chain_available)

    if snapshot.data_source_status == "missing_credentials":
        reason = "missing_credentials"
    elif not quote_available and not chain_available:
        reason = "broker_error" if snapshot.data_source_status == "broker_error" else "quote_unavailable"
    elif not quote_available:
        reason = "quote_unavailable"
    elif not chain_available:
        reason = "chain_unavailable"
    elif not quote_fresh:
        reason = "stale_quote"
    elif not chain_fresh:
        reason = "stale_chain"
    else:
        reason = "none"

    ready = quote_available and chain_available and quote_fresh and chain_fresh
    return MarketReadiness(
        symbol=snapshot.symbol,
        market_ready=ready,
        block_reason=reason,
        quote_available=quote_available,
        chain_available=chain_available,
        quote_age_seconds=quote_age,
        chain_age_seconds=chain_age,
        quote_is_fresh=quote_fresh,
        chain_is_fresh=chain_fresh,
        latest_quote_time=snapshot.snapshot_time,
        latest_chain_time=snapshot.chain_snapshot_time,
        source_status=snapshot.data_source_status,
    )


def _age_seconds(event_time: datetime | None, now: datetime) -> float | None:
    if event_time is None:
        return None
    timestamp = event_time if event_time.tzinfo else event_time.replace(tzinfo=timezone.utc)
    return max((now - timestamp).total_seconds(), 0.0)

