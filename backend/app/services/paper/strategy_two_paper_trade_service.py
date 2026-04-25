"""Deterministic paper position open/close for Strategy 2 (0DTE sniper)."""

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
from app.services.paper.paper_trade_service import (
    PaperTradeError,
    _chain_age_seconds,
    _find_contract,
    _utc_iso_floor_second,
)
from app.services.paper.strategy_two_entry_policies import (
    EntryPolicyRejected,
    assign_exit_and_sizing_policies_v1,
)
from app.services.strategy.strategy_two_spy_0dte_vol_sniper import STRATEGY2_ID


def _validate_chain_for_paper_quote(chain: ChainLatestResponse, settings: Settings) -> None:
    if not chain.available or not chain.option_quotes_available:
        raise PaperTradeError("option_chain_unavailable")
    age = _chain_age_seconds(chain)
    if age is None:
        raise PaperTradeError("option_chain_timestamp_missing")
    if age > settings.MARKET_CHAIN_MAX_AGE_SECONDS:
        raise PaperTradeError("option_chain_quote_stale")


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


class StrategyTwoPaperTradeService:
    STRATEGY_ID = STRATEGY2_ID

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
        quote: NearAtmContract = _find_contract(chain, cand.option_symbol)
        if quote.ask is None or float(quote.ask) <= 0:
            raise PaperTradeError("option_ask_missing_for_entry")
        if quote.bid is None or float(quote.bid) <= 0:
            raise PaperTradeError("option_bid_missing_for_two_sided_quote")

        chain_ts = chain.snapshot_timestamp
        if chain_ts is None:
            raise PaperTradeError("option_chain_timestamp_missing")

        repo = PaperTradeRepository(db)
        if repo.has_open_position_for_contract(strategy_id=self.STRATEGY_ID, option_symbol=cand.option_symbol, side="long"):
            raise PaperTradeError("duplicate_open_position")

        now = repo.utc_now()
        try:
            exit_pol, sizing_pol = assign_exit_and_sizing_policies_v1(
                evaluation=evaluation,
                contract=cand,
                entry_ask_per_share=float(quote.ask),
                quantity=1,
                account_equity_usd=float(settings.PAPER_STRATEGY2_ACCOUNT_EQUITY_USD),
                entry_clock_utc=now,
            )
        except EntryPolicyRejected as exc:
            details = dict(exc.details or {})
            details.setdefault("attempted_option_symbol", cand.option_symbol)
            details.setdefault("attempted_side", "long")
            details.setdefault("attempted_expiration_date", cand.expiration_date)
            details.setdefault("attempted_strike", cand.strike)
            raise PaperTradeError(exc.code, details=details) from exc

        fingerprint = build_entry_evaluation_fingerprint(
            strategy_id=self.STRATEGY_ID,
            symbol=evaluation.symbol,
            option_symbol=cand.option_symbol,
            side="long",
            decision=evaluation.decision,
            evaluation_timestamp=evaluation.evaluation_timestamp,
            chain_snapshot_timestamp=chain_ts,
        )
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
            evaluation_snapshot_json=evaluation.model_dump(mode="json"),
            entry_reference_basis="option_ask",
            exit_reference_basis=None,
            exit_reason=None,
            entry_evaluation_fingerprint=fingerprint,
            exit_policy=exit_pol.as_dict(),
            sizing_policy=sizing_pol.as_dict(),
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
                    "strategy_id": self.STRATEGY_ID,
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
        row.exit_reason = exit_reason.strip()
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
                    "exit_reason": row.exit_reason,
                    "realized_pnl": realized,
                    "strategy_id": self.STRATEGY_ID,
                },
            )
        )
        return row
