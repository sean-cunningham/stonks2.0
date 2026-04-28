"""Mark-to-market for open paper positions using chain snapshot and/or direct held-symbol quotes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings
from app.models.trade import PaperTrade
from app.schemas.market import ChainLatestResponse, NearAtmContract
from app.schemas.paper_trade import PaperOpenPositionValuationResponse
from app.services.paper.contract_constants import OPTION_CONTRACT_MULTIPLIER
from app.services.paper.held_option_contract_resolution import HeldOptionContractResolution


def _quote_age_seconds_from_ts(quote_ts: datetime | None, *, now: datetime) -> float | None:
    if quote_ts is None:
        return None
    ts = quote_ts if quote_ts.tzinfo else quote_ts.replace(tzinfo=timezone.utc)
    return max((now - ts).total_seconds(), 0.0)


def _quote_age_seconds(chain: ChainLatestResponse, *, now: datetime) -> float | None:
    if chain.snapshot_timestamp is None:
        return None
    ts = (
        chain.snapshot_timestamp
        if chain.snapshot_timestamp.tzinfo
        else chain.snapshot_timestamp.replace(tzinfo=timezone.utc)
    )
    return max((now - ts).total_seconds(), 0.0)


def _find_contract_optional(chain: ChainLatestResponse, option_symbol: str) -> NearAtmContract | None:
    for c in chain.near_atm_contracts:
        if c.option_symbol == option_symbol:
            return c
    return None


def _evaluation_reference(row: PaperTrade) -> dict[str, Any] | None:
    snap = row.evaluation_snapshot_json
    if not isinstance(snap, dict):
        return None
    ref: dict[str, Any] = {}
    if snap.get("symbol") is not None:
        ref["symbol"] = snap.get("symbol")
    if snap.get("decision") is not None:
        ref["decision"] = snap.get("decision")
    elif row.entry_decision:
        ref["decision"] = row.entry_decision
    if snap.get("evaluation_timestamp") is not None:
        ref["evaluation_timestamp"] = snap.get("evaluation_timestamp")
    return ref or None


def _underlying_ref(chain: ChainLatestResponse) -> float | None:
    if chain.available:
        return chain.underlying_reference_price
    return None


def compute_open_position_valuation(
    row: PaperTrade,
    chain: ChainLatestResponse,
    settings: Settings,
    *,
    now: datetime | None = None,
    held_resolution: HeldOptionContractResolution | None = None,
) -> PaperOpenPositionValuationResponse:
    """Value one open long position: chain near-ATM row, or direct quote for exact ``option_symbol``."""
    clock = now or datetime.now(timezone.utc)
    base_id = row.id if row.id is not None else 0
    sym = row.option_symbol
    qty = int(row.quantity)
    entry_px = float(row.entry_price)

    pol_exit = row.exit_policy if isinstance(getattr(row, "exit_policy", None), dict) else None
    pol_size = row.sizing_policy if isinstance(getattr(row, "sizing_policy", None), dict) else None

    def _empty(
        *,
        valuation_error: str | None,
        quote_ts: datetime | None = None,
        quote_age: float | None = None,
        fresh: bool = False,
        quote_resolution_source: str | None = None,
        quote_blocker_code: str | None = None,
    ) -> PaperOpenPositionValuationResponse:
        return PaperOpenPositionValuationResponse(
            paper_trade_id=base_id,
            option_symbol=sym,
            side=row.side,
            quantity=qty,
            entry_time=row.entry_time,
            entry_price=entry_px,
            current_bid=None,
            current_ask=None,
            current_mid=None,
            quote_timestamp_used=quote_ts,
            quote_age_seconds=quote_age,
            quote_is_fresh=fresh,
            exit_actionable=False,
            unrealized_pnl_bid_basis=None,
            unrealized_pnl_mid_basis=None,
            underlying_reference_price=_underlying_ref(chain),
            evaluation_snapshot_reference=_evaluation_reference(row),
            valuation_error=valuation_error,
            exit_policy=pol_exit,
            sizing_policy=pol_size,
            quote_resolution_source=quote_resolution_source,
            quote_blocker_code=quote_blocker_code,
        )

    def _from_contract(
        c: NearAtmContract,
        *,
        quote_ts: datetime | None,
        quote_age: float | None,
        quote_fresh: bool,
        resolution_src: str,
    ) -> PaperOpenPositionValuationResponse:
        bid = float(c.bid) if c.bid is not None else None
        ask = float(c.ask) if c.ask is not None else None
        mid: float | None = None
        if bid is not None and ask is not None and bid > 0 and ask > 0:
            mid = (bid + ask) / 2.0

        two_sided = bid is not None and ask is not None and bid > 0 and ask > 0
        exit_actionable = bool(quote_fresh and two_sided)
        blocker: str | None = None
        if not quote_fresh:
            blocker = "stale_option_quote_for_open_position"
        elif not two_sided:
            blocker = "invalid_bid_ask_for_open_position"

        u_pnl_bid: float | None = None
        if bid is not None:
            u_pnl_bid = (bid - entry_px) * OPTION_CONTRACT_MULTIPLIER * qty

        u_pnl_mid: float | None = None
        if mid is not None:
            u_pnl_mid = (mid - entry_px) * OPTION_CONTRACT_MULTIPLIER * qty

        return PaperOpenPositionValuationResponse(
            paper_trade_id=base_id,
            option_symbol=sym,
            side=row.side,
            quantity=qty,
            entry_time=row.entry_time,
            entry_price=entry_px,
            current_bid=bid,
            current_ask=ask,
            current_mid=mid,
            quote_timestamp_used=quote_ts,
            quote_age_seconds=quote_age,
            quote_is_fresh=quote_fresh,
            exit_actionable=exit_actionable,
            unrealized_pnl_bid_basis=u_pnl_bid,
            unrealized_pnl_mid_basis=u_pnl_mid,
            underlying_reference_price=_underlying_ref(chain),
            evaluation_snapshot_reference=_evaluation_reference(row),
            valuation_error=None,
            exit_policy=pol_exit,
            sizing_policy=pol_size,
            quote_resolution_source=resolution_src,
            quote_blocker_code=blocker,
        )

    if held_resolution is not None:
        qt = held_resolution.quote_timestamp
        if qt.tzinfo is None:
            qt = qt.replace(tzinfo=timezone.utc)
        age = _quote_age_seconds_from_ts(qt, now=clock)
        quote_fresh = age is not None and age <= settings.MARKET_CHAIN_MAX_AGE_SECONDS
        return _from_contract(
            held_resolution.contract,
            quote_ts=qt,
            quote_age=age,
            quote_fresh=quote_fresh,
            resolution_src=held_resolution.source,
        )

    if not chain.available or not chain.option_quotes_available:
        return _empty(
            valuation_error="option_chain_unavailable",
            quote_blocker_code="missing_option_quote_for_open_position",
        )

    quote_ts = chain.snapshot_timestamp
    age = _quote_age_seconds(chain, now=clock)
    quote_fresh = age is not None and age <= settings.MARKET_CHAIN_MAX_AGE_SECONDS

    c = _find_contract_optional(chain, sym)
    if c is None:
        return _empty(
            valuation_error="option_contract_not_in_chain_snapshot",
            quote_ts=quote_ts,
            quote_age=age,
            fresh=quote_fresh,
            quote_resolution_source=None,
            quote_blocker_code="option_contract_not_in_near_atm_chain_snapshot",
        )

    return _from_contract(
        c,
        quote_ts=quote_ts,
        quote_age=age,
        quote_fresh=quote_fresh,
        resolution_src="chain_near_atm",
    )
