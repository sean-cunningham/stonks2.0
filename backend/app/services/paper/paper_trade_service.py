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
from app.services.paper.contract_constants import OPTION_CONTRACT_MULTIPLIER
from app.services.paper.strategy_one_entry_policies import (
    EntryPolicyRejected,
    assign_exit_and_sizing_policies_v1,
)


class PaperTradeError(Exception):
    """Fail-closed paper action (caller maps to HTTP 400)."""


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
            strategy_id=self.STRATEGY_ID,
            symbol=evaluation.symbol,
            option_symbol=cand.option_symbol,
            side="long",
            decision=evaluation.decision,
            evaluation_timestamp=evaluation.evaluation_timestamp,
            chain_snapshot_timestamp=chain_ts,
        )

        repo = PaperTradeRepository(db)
        if repo.has_open_position_for_contract(
            strategy_id=self.STRATEGY_ID,
            option_symbol=cand.option_symbol,
            side="long",
        ):
            raise PaperTradeError("duplicate_open_position")

        now = repo.utc_now()
        try:
            exit_pol, sizing_pol = assign_exit_and_sizing_policies_v1(
                evaluation=evaluation,
                contract=cand,
                entry_ask_per_share=float(quote.ask),
                quantity=1,
                account_equity_usd=float(settings.PAPER_STRATEGY1_ACCOUNT_EQUITY_USD),
                entry_clock_utc=now,
            )
        except EntryPolicyRejected as exc:
            raise PaperTradeError(exc.code) from exc

        snap = evaluation.model_dump(mode="json")
        row = PaperTrade(
            strategy_id=self.STRATEGY_ID,
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
    ) -> PaperTrade:
        if not exit_reason or not exit_reason.strip():
            raise PaperTradeError("exit_reason_required")
        exit_reason = exit_reason.strip()
        if not market_status.market_ready:
            raise PaperTradeError("market_not_ready_for_paper_exit")

        repo = PaperTradeRepository(db)
        row = repo.get_trade(paper_trade_id)
        if row is None:
            raise PaperTradeError("paper_trade_not_found")
        if row.strategy_id != self.STRATEGY_ID:
            raise PaperTradeError("paper_trade_strategy_mismatch")
        if row.status != "open":
            raise PaperTradeError("paper_trade_not_open")

        _validate_chain_for_paper_quote(chain, settings)
        quote = _find_contract(chain, row.option_symbol)
        if quote.bid is None or float(quote.bid) <= 0:
            raise PaperTradeError("option_bid_missing_for_exit")

        now = repo.utc_now()
        exit_bid = float(quote.bid)
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
                    "chain_snapshot_time": chain.snapshot_timestamp.isoformat()
                    if chain.snapshot_timestamp
                    else None,
                },
            )
        )
        return row
