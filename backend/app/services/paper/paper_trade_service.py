"""Deterministic paper position open/close for Strategy 1 (no broker, no fake mids)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.trade import PaperTrade, PaperTradeEvent
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.schemas.market import ChainLatestResponse, MarketStatusResponse, NearAtmContract
from app.schemas.strategy import StrategyOneEvaluationResponse
from app.services.market.market_store import MarketStoreService
from app.services.paper.contract_constants import OPTION_CONTRACT_MULTIPLIER
from app.services.paper.held_option_contract_resolution import HeldOptionContractResolution
from app.services.paper.paper_valuation import compute_open_position_valuation
from app.services.paper.strategy_one_entry_policies import (
    EntryPolicyRejected,
    assign_exit_and_sizing_policies_v1,
)


class PaperTradeError(Exception):
    """Fail-closed paper action (caller maps to HTTP 400)."""

    def __init__(self, code: str, *, details: dict | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}

    # Backward-compatible: some call sites use str(exc) only.
    def __str__(self) -> str:  # type: ignore[override]
        return self.code


def _chain_age_seconds(chain: ChainLatestResponse) -> float | None:
    if chain.snapshot_timestamp is None:
        return None
    ts = (
        chain.snapshot_timestamp
        if chain.snapshot_timestamp.tzinfo
        else chain.snapshot_timestamp.replace(tzinfo=timezone.utc)
    )
    return max((datetime.now(timezone.utc) - ts).total_seconds(), 0.0)


def _validate_chain_for_paper_quote(chain: ChainLatestResponse, settings: Settings) -> None:
    if not chain.available or not chain.option_quotes_available:
        raise PaperTradeError("option_chain_unavailable")
    age = _chain_age_seconds(chain)
    if age is None:
        raise PaperTradeError("option_chain_timestamp_missing")
    if age > settings.MARKET_CHAIN_MAX_AGE_SECONDS:
        raise PaperTradeError("option_chain_quote_stale")


def _held_quote_age_seconds(*, quote_timestamp: datetime, clock: datetime) -> float:
    ts = quote_timestamp if quote_timestamp.tzinfo else quote_timestamp.replace(tzinfo=timezone.utc)
    return max((clock - ts).total_seconds(), 0.0)


def _validate_held_quote_fresh_for_close(
    held: HeldOptionContractResolution,
    settings: Settings,
    *,
    clock: datetime,
) -> None:
    age = _held_quote_age_seconds(quote_timestamp=held.quote_timestamp, clock=clock)
    if age > settings.MARKET_CHAIN_MAX_AGE_SECONDS:
        raise PaperTradeError("stale_option_quote_for_open_position", details={"age_seconds": age})


MANUAL_EMERGENCY_CLOSE_AT_MARKET_BID = "manual_emergency_close_at_market_bid"
MANUAL_EMERGENCY_CLOSE_UNQUOTED = "manual_emergency_close_unquoted"
EXIT_REFERENCE_PAPER_EMERGENCY_UNQUOTED = "paper_emergency_unquoted"


def _find_contract(chain: ChainLatestResponse, option_symbol: str) -> NearAtmContract:
    for c in chain.near_atm_contracts:
        if c.option_symbol == option_symbol:
            return c
    raise PaperTradeError("option_contract_not_in_chain_snapshot")


def _utc_iso_floor_second(dt: datetime) -> str:
    """UTC ISO-8601 with microsecond stripped (deterministic dedupe bucket)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0).isoformat()


def build_entry_evaluation_fingerprint(
    *,
    strategy_id: str,
    symbol: str,
    option_symbol: str,
    side: str,
    decision: str,
    evaluation_timestamp: datetime,
    chain_snapshot_timestamp: datetime,
) -> str:
    """Audit/replay fingerprint (strategy + contract + side + decision + UTC second buckets).

    Duplicate-open prevention uses ``has_open_position_for_contract`` (any open row for the
    same strategy/option/side), not this string.
    """
    return "|".join(
        [
            strategy_id,
            symbol,
            option_symbol,
            side,
            decision,
            _utc_iso_floor_second(evaluation_timestamp),
            _utc_iso_floor_second(chain_snapshot_timestamp),
        ]
    )


class PaperTradeService:
    """Single-contract SPY paper positions for Strategy 1."""

    STRATEGY_ID = "strategy_1_spy"

    def __init__(
        self,
        *,
        strategy_id: str | None = None,
        account_equity_usd: float | None = None,
    ) -> None:
        self.strategy_id = strategy_id or self.STRATEGY_ID
        self.account_equity_usd = account_equity_usd

    def open_position(
        self,
        db: Session,
        *,
        evaluation: StrategyOneEvaluationResponse,
        chain: ChainLatestResponse,
        market_status: MarketStatusResponse,
        settings: Settings,
    ) -> PaperTrade:
        if not market_status.market_ready:
            raise PaperTradeError("market_not_ready_for_paper_entry")
        if evaluation.decision not in ("candidate_call", "candidate_put"):
            raise PaperTradeError("evaluation_not_a_candidate_decision")
        cand = evaluation.contract_candidate
        if cand is None:
            raise PaperTradeError("missing_contract_candidate")

        _validate_chain_for_paper_quote(chain, settings)
        quote = _find_contract(chain, cand.option_symbol)
        if quote.ask is None or float(quote.ask) <= 0:
            raise PaperTradeError("option_ask_missing_for_entry")
        if quote.bid is None or float(quote.bid) <= 0:
            raise PaperTradeError("option_bid_missing_for_two_sided_quote")

        chain_ts = chain.snapshot_timestamp
        if chain_ts is None:
            raise PaperTradeError("option_chain_timestamp_missing")
        fingerprint = build_entry_evaluation_fingerprint(
            strategy_id=self.strategy_id,
            symbol=evaluation.symbol,
            option_symbol=cand.option_symbol,
            side="long",
            decision=evaluation.decision,
            evaluation_timestamp=evaluation.evaluation_timestamp,
            chain_snapshot_timestamp=chain_ts,
        )

        repo = PaperTradeRepository(db)
        if repo.has_open_position_for_contract(
            strategy_id=self.strategy_id,
            option_symbol=cand.option_symbol,
            side="long",
        ):
            raise PaperTradeError("duplicate_open_position")

        now = repo.utc_now()
        account_equity_usd = (
            float(self.account_equity_usd)
            if self.account_equity_usd is not None
            else float(settings.PAPER_STRATEGY1_ACCOUNT_EQUITY_USD)
        )
        try:
            exit_pol, sizing_pol = assign_exit_and_sizing_policies_v1(
                evaluation=evaluation,
                contract=cand,
                entry_ask_per_share=float(quote.ask),
                quantity=1,
                account_equity_usd=account_equity_usd,
                entry_clock_utc=now,
            )
        except EntryPolicyRejected as exc:
            raise PaperTradeError(exc.code, details=exc.details) from exc

        snap = evaluation.model_dump(mode="json")
        row = PaperTrade(
            strategy_id=self.strategy_id,
            symbol=evaluation.symbol,
            option_symbol=cand.option_symbol,
            side="long",
            quantity=1,
            entry_time=now,
            entry_price=float(quote.ask),
            exit_time=None,
            exit_price=None,
            realized_pnl=None,
            status="open",
            entry_decision=evaluation.decision,
            evaluation_snapshot_json=snap,
            entry_reference_basis="option_ask",
            exit_reference_basis=None,
            exit_reason=None,
            entry_evaluation_fingerprint=fingerprint,
            exit_policy=exit_pol.model_dump(mode="json"),
            sizing_policy=sizing_pol.model_dump(mode="json"),
        )
        try:
            row = repo.create_trade(row)
        except IntegrityError as exc:
            raise PaperTradeError("duplicate_open_position") from exc
        repo.append_event(
            PaperTradeEvent(
                paper_trade_id=row.id,
                event_time=now,
                event_type="open",
                details_json={
                    "entry_reference_basis": "option_ask",
                    "entry_price_per_share": row.entry_price,
                    "entry_evaluation_fingerprint": fingerprint,
                    "exit_policy_version": exit_pol.policy_version,
                    "trade_horizon_class": exit_pol.trade_horizon_class,
                    "sizing_profile": sizing_pol.sizing_profile,
                    "risk_budget_usd": sizing_pol.risk_budget_usd,
                    "max_affordable_premium_usd": sizing_pol.max_affordable_premium_usd,
                    "chain_snapshot_time": chain.snapshot_timestamp.isoformat()
                    if chain.snapshot_timestamp
                    else None,
                    "evaluation_timestamp": evaluation.evaluation_timestamp.isoformat(),
                },
            )
        )
        return row

    def close_position(
        self,
        db: Session,
        *,
        paper_trade_id: int,
        chain: ChainLatestResponse,
        market_status: MarketStatusResponse,
        exit_reason: str,
        settings: Settings,
        held_contract_resolution: HeldOptionContractResolution | None = None,
        bypass_market_ready_guard: bool = False,
    ) -> PaperTrade:
        if not exit_reason or not exit_reason.strip():
            raise PaperTradeError("exit_reason_required")
        exit_reason = exit_reason.strip()
        if not bypass_market_ready_guard and not market_status.market_ready:
            raise PaperTradeError("market_not_ready_for_paper_exit")

        repo = PaperTradeRepository(db)
        row = repo.get_trade(paper_trade_id)
        if row is None:
            raise PaperTradeError("paper_trade_not_found")
        if row.strategy_id != self.strategy_id:
            raise PaperTradeError("paper_trade_strategy_mismatch")
        if row.status != "open":
            raise PaperTradeError("paper_trade_not_open")

        now = repo.utc_now()
        quote_snapshot_iso: str | None = None
        quote_resolution: str | None = None

        if held_contract_resolution is not None:
            _validate_held_quote_fresh_for_close(held_contract_resolution, settings, clock=now)
            quote = held_contract_resolution.contract
            quote_resolution = held_contract_resolution.source
            quote_snapshot_iso = held_contract_resolution.quote_timestamp.isoformat()
        else:
            try:
                _validate_chain_for_paper_quote(chain, settings)
            except PaperTradeError as exc:
                code = str(exc)
                if code == "option_chain_quote_stale":
                    raise PaperTradeError(
                        "stale_option_quote_for_open_position",
                        details={"option_symbol": row.option_symbol},
                    ) from exc
                raise
            try:
                quote = _find_contract(chain, row.option_symbol)
            except PaperTradeError as exc:
                if str(exc) == "option_contract_not_in_chain_snapshot":
                    raise PaperTradeError(
                        "missing_option_quote_for_open_position",
                        details={"option_symbol": row.option_symbol},
                    ) from exc
                raise
            quote_resolution = "chain_near_atm"
            quote_snapshot_iso = chain.snapshot_timestamp.isoformat() if chain.snapshot_timestamp else None

        bid = float(quote.bid) if quote.bid is not None else None
        ask = float(quote.ask) if quote.ask is not None else None
        if bid is None or bid <= 0:
            raise PaperTradeError(
                "missing_option_quote_for_open_position",
                details={"leg": "bid", "option_symbol": row.option_symbol},
            )
        if ask is not None and bid is not None and ask < bid:
            raise PaperTradeError("invalid_bid_ask_for_open_position", details={"option_symbol": row.option_symbol})

        exit_bid = bid
        realized = (exit_bid - float(row.entry_price)) * OPTION_CONTRACT_MULTIPLIER * int(row.quantity)

        row.exit_time = now
        row.exit_price = exit_bid
        row.exit_reference_basis = "option_bid"
        row.exit_reason = exit_reason
        row.realized_pnl = realized
        row.status = "closed"
        row = repo.update_trade(row)

        repo.append_event(
            PaperTradeEvent(
                paper_trade_id=row.id,
                event_time=now,
                event_type="close",
                details_json={
                    "exit_reference_basis": "option_bid",
                    "exit_price_per_share": exit_bid,
                    "exit_reason": exit_reason,
                    "realized_pnl": realized,
                    "chain_snapshot_time": quote_snapshot_iso,
                    "quote_resolution_source": quote_resolution,
                },
            )
        )
        return row

    def emergency_close_unquoted_paper_position(
        self,
        db: Session,
        *,
        paper_trade_id: int,
        market: MarketStoreService,
        settings: Settings,
    ) -> PaperTrade:
        """Paper emergency: prefer close at live **option bid** (chain or direct quote); else $0 synthetic exit.

        The UI label may say \"unquoted\"; the server always attempts a real mark first so closed-trade
        sale notional matches the best available quote at request time.
        """
        repo = PaperTradeRepository(db)
        row = repo.get_trade(paper_trade_id)
        if row is None:
            raise PaperTradeError("paper_trade_not_found")
        if row.strategy_id != self.strategy_id:
            raise PaperTradeError("paper_trade_strategy_mismatch")
        if row.status != "open":
            raise PaperTradeError("paper_trade_not_open")

        resolution = market.resolve_spy_market_for_evaluation()
        mstatus = resolution.final_status
        chain = market.get_latest_chain()
        held = market.resolve_open_paper_option_contract(option_symbol=row.option_symbol, chain=chain)
        now = repo.utc_now()
        valuation = compute_open_position_valuation(row, chain, settings, now=now, held_resolution=held)
        quote_ok = (
            not valuation.valuation_error
            and valuation.quote_is_fresh
            and valuation.exit_actionable
        )
        if quote_ok:
            bypass = not mstatus.market_ready
            return self.close_position(
                db,
                paper_trade_id=paper_trade_id,
                chain=chain,
                market_status=mstatus,
                exit_reason=MANUAL_EMERGENCY_CLOSE_AT_MARKET_BID,
                settings=settings,
                held_contract_resolution=held,
                bypass_market_ready_guard=bypass,
            )

        exit_px = 0.0
        realized = (exit_px - float(row.entry_price)) * OPTION_CONTRACT_MULTIPLIER * int(row.quantity)
        row.exit_time = now
        row.exit_price = exit_px
        row.exit_reference_basis = EXIT_REFERENCE_PAPER_EMERGENCY_UNQUOTED
        row.exit_reason = MANUAL_EMERGENCY_CLOSE_UNQUOTED
        row.realized_pnl = realized
        row.status = "closed"
        row = repo.update_trade(row)
        repo.append_event(
            PaperTradeEvent(
                paper_trade_id=row.id,
                event_time=now,
                event_type="close",
                details_json={
                    "exit_reference_basis": EXIT_REFERENCE_PAPER_EMERGENCY_UNQUOTED,
                    "exit_price_per_share": exit_px,
                    "exit_reason": MANUAL_EMERGENCY_CLOSE_UNQUOTED,
                    "realized_pnl": realized,
                    "paper_emergency_unquoted": True,
                    "paper_emergency_quote_attempt_failed": True,
                },
            )
        )
        return row
