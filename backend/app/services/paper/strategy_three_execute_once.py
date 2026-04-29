"""One automatic Strategy 3 paper cycle (0DTE micro impulse)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.schemas.paper_trade import PaperTradeResponse
from app.schemas.strategy_three_paper_execution import StrategyThreeExecuteOnceResponse
from app.services.market.context_service import ContextService
from app.services.market.market_store import MarketStoreService
from app.services.paper.paper_trade_service import PaperTradeError
from app.services.paper.strategy_one_execute_once import require_acceptable_exit_quote_for_execution
from app.services.paper.paper_valuation import compute_open_position_valuation
from app.services.paper.strategy_three_evaluation_bundle import build_strategy_three_evaluation_bundle
from app.services.paper.strategy_three_exit_evaluator import ExitEvaluationInput, evaluate_strategy_three_open_exit_readonly
from app.services.paper.strategy_three_paper_trade_service import StrategyThreePaperTradeService

AUTO_EXIT_REASON = "strategy_3_auto_exit_close_now"
EMERGENCY_EXIT_REASON = "strategy_3_emergency_manual_override"
_ET = ZoneInfo("America/New_York")
_MAX_TRADES_PER_DAY = 5
_COOLDOWN_AFTER_CLOSE_MIN = 3


def _fmt_num(v: object, places: int = 4) -> str | None:
    if not isinstance(v, (int, float)):
        return None
    return f"{float(v):.{places}f}"


def _build_no_trade_diagnostic_note(evaluation) -> str:
    """Compact no-trade summary for runtime cycle notes."""
    diag = getattr(evaluation, "diagnostics", None)
    near_miss = getattr(diag, "near_miss", {}) if diag is not None else {}
    contract_gate = getattr(diag, "contract_gate", {}) if diag is not None else {}
    primary = getattr(diag, "primary_failed_gate", None) if diag is not None else None
    blockers = getattr(evaluation, "blockers", None) or []
    parts: list[str] = ["no_trade", f"decision={getattr(evaluation, 'decision', 'no_trade')}"]
    if primary:
        parts.append(f"gate={primary}")
    if blockers:
        parts.append(f"blocker={str(blockers[0])}")
    trig = near_miss.get("nearest_trigger_name")
    if isinstance(trig, str) and trig:
        parts.append(f"trigger={trig}")
    dist = _fmt_num(near_miss.get("nearest_trigger_distance"), places=4)
    if dist is not None:
        parts.append(f"dist={dist}")
    band = _fmt_num(near_miss.get("proximity_band"), places=4)
    if band is not None:
        parts.append(f"band={band}")
    micro15 = _fmt_num(near_miss.get("micro_price_change_15s"), places=4)
    if micro15 is not None:
        parts.append(f"micro15={micro15}")
    micro30 = _fmt_num(near_miss.get("micro_price_change_30s"), places=4)
    if micro30 is not None:
        parts.append(f"micro30={micro30}")
    micro_atr30 = _fmt_num(near_miss.get("micro_atr_fraction_30s"), places=4)
    if micro_atr30 is not None:
        parts.append(f"microAtr30={micro_atr30}")
    setup = near_miss.get("setup_type")
    if isinstance(setup, str):
        parts.append(f"setup={setup}")
    if isinstance(contract_gate, dict):
        c = contract_gate.get("eligible_0dte_contracts_for_side")
        if isinstance(c, int):
            parts.append(f"contracts={c}")
    s = "|".join(parts)
    return s[:420]


def _append_affordability_details_note(notes: list[str], details: dict | None) -> None:
    if not details:
        return
    keys = [
        "attempted_option_symbol",
        "attempted_side",
        "attempted_expiration_date",
        "attempted_strike",
        "attempted_ask",
        "attempted_total_premium_usd",
        "account_equity_used",
        "max_position_cost_usd",
        "contract_cost_usd",
        "affordability_block_reason",
    ]
    parts = [f"{k}={details[k]}" for k in keys if k in details]
    if parts:
        notes.append("affordability_diag:" + ";".join(parts))


def _entry_limits_block_reason(
    *,
    now_utc: datetime,
    repo: PaperTradeRepository,
    strategy_id: str,
) -> str | None:
    closed_rows = repo.list_closed_chronological(strategy_id=strategy_id, limit=2000)
    open_rows = repo.list_open(strategy_id=strategy_id)
    today_et = now_utc.astimezone(_ET).date()

    entries_today = [r for r in closed_rows if r.entry_time and r.entry_time.astimezone(_ET).date() == today_et]
    entries_today.extend([r for r in open_rows if r.entry_time and r.entry_time.astimezone(_ET).date() == today_et])
    if len(entries_today) >= _MAX_TRADES_PER_DAY:
        return "risk_limit_max_trades_per_day_reached"

    latest_closed_exit = max((r.exit_time for r in closed_rows if r.exit_time is not None), default=None)
    if latest_closed_exit is not None:
        if (now_utc - latest_closed_exit).total_seconds() < timedelta(minutes=_COOLDOWN_AFTER_CLOSE_MIN).total_seconds():
            return "cooldown_after_close_active"
    return None


def run_strategy_three_paper_exit_once(
    db: Session,
    *,
    context: ContextService,
    market: MarketStoreService,
    settings: Settings,
    exit_enabled: bool = True,
) -> StrategyThreeExecuteOnceResponse:
    clock = datetime.now(timezone.utc)
    repo = PaperTradeRepository(db)
    svc = StrategyThreePaperTradeService()
    opens = repo.list_open(strategy_id=svc.STRATEGY_ID)
    notes: list[str] = []
    if not opens:
        notes.append("no_open_position_for_exit")
        return StrategyThreeExecuteOnceResponse(
            cycle_action="no_action",
            had_open_position_at_start=False,
            notes=notes,
            evaluation_timestamp=clock,
        )
    if not exit_enabled:
        notes.append("runtime_exit_disabled")
        return StrategyThreeExecuteOnceResponse(
            cycle_action="no_action",
            had_open_position_at_start=True,
            notes=notes,
            evaluation_timestamp=clock,
        )

    row = opens[0]
    st = context.get_status()
    summary = context.get_summary()
    resolution = market.resolve_spy_market_for_evaluation()
    mstatus = resolution.final_status
    chain = market.get_latest_chain()
    valuation = compute_open_position_valuation(row, chain, settings)
    exit_eval = evaluate_strategy_three_open_exit_readonly(
        ExitEvaluationInput(
            position=row,
            valuation=valuation,
            context_status=st,
            context_summary=summary,
            market_status=mstatus,
            clock_utc=clock,
        )
    )
    if exit_eval.action != "close_now":
        notes.append("exit_evaluator_did_not_request_close_now")
        return StrategyThreeExecuteOnceResponse(
            cycle_action="no_action",
            had_open_position_at_start=True,
            notes=notes,
            evaluation_timestamp=clock,
            exit_evaluation=exit_eval,
        )
    try:
        require_acceptable_exit_quote_for_execution(valuation)
    except PaperTradeError as exc:
        notes.append(f"auto_close_skipped:{exc}")
        return StrategyThreeExecuteOnceResponse(
            cycle_action="no_action",
            had_open_position_at_start=True,
            notes=notes,
            evaluation_timestamp=clock,
            exit_evaluation=exit_eval,
        )
    try:
        closed = svc.close_position(
            db,
            paper_trade_id=row.id,
            chain=chain,
            market_status=mstatus,
            exit_reason=AUTO_EXIT_REASON,
            settings=settings,
        )
    except PaperTradeError as exc:
        notes.append(f"auto_close_failed:{exc}")
        return StrategyThreeExecuteOnceResponse(
            cycle_action="no_action",
            had_open_position_at_start=True,
            notes=notes,
            evaluation_timestamp=clock,
            exit_evaluation=exit_eval,
        )
    return StrategyThreeExecuteOnceResponse(
        cycle_action="closed",
        had_open_position_at_start=True,
        notes=notes,
        evaluation_timestamp=clock,
        exit_evaluation=exit_eval,
        closed_paper_trade=PaperTradeResponse.model_validate(closed),
    )


def run_strategy_three_paper_entry_once(
    db: Session,
    *,
    context: ContextService,
    market: MarketStoreService,
    settings: Settings,
    entry_enabled: bool = True,
) -> StrategyThreeExecuteOnceResponse:
    clock = datetime.now(timezone.utc)
    repo = PaperTradeRepository(db)
    svc = StrategyThreePaperTradeService()
    opens = repo.list_open(strategy_id=svc.STRATEGY_ID)
    notes: list[str] = []
    if opens:
        notes.append("open_position_exists_entry_skipped")
        return StrategyThreeExecuteOnceResponse(
            cycle_action="no_action",
            had_open_position_at_start=True,
            notes=notes,
            evaluation_timestamp=clock,
        )
    if not entry_enabled:
        notes.append("runtime_entry_disabled")
        return StrategyThreeExecuteOnceResponse(
            cycle_action="no_action",
            had_open_position_at_start=False,
            notes=notes,
            evaluation_timestamp=clock,
        )
    entry_limits_blocked = _entry_limits_block_reason(now_utc=clock, repo=repo, strategy_id=svc.STRATEGY_ID)
    if entry_limits_blocked:
        notes.append(entry_limits_blocked)
        return StrategyThreeExecuteOnceResponse(
            cycle_action="no_action",
            had_open_position_at_start=False,
            notes=notes,
            evaluation_timestamp=clock,
        )

    evaluation, mstatus, chain = build_strategy_three_evaluation_bundle(context, market, settings)
    if evaluation.decision == "no_trade":
        notes.append("entry_evaluator_no_trade_candidate")
        notes.append(_build_no_trade_diagnostic_note(evaluation))
        return StrategyThreeExecuteOnceResponse(
            cycle_action="no_action",
            had_open_position_at_start=False,
            notes=notes,
            evaluation_timestamp=clock,
            entry_evaluation=evaluation,
        )
    try:
        opened = svc.open_position(
            db,
            evaluation=evaluation,
            chain=chain,
            market_status=mstatus,
            settings=settings,
        )
    except PaperTradeError as exc:
        notes.append(f"auto_open_failed:{exc}")
        if str(exc) == "paper_entry_exceeds_max_position_cost":
            _append_affordability_details_note(notes, getattr(exc, "details", None))
        return StrategyThreeExecuteOnceResponse(
            cycle_action="no_action",
            had_open_position_at_start=False,
            notes=notes,
            evaluation_timestamp=clock,
            entry_evaluation=evaluation,
        )
    return StrategyThreeExecuteOnceResponse(
        cycle_action="opened",
        had_open_position_at_start=False,
        notes=notes,
        evaluation_timestamp=clock,
        entry_evaluation=evaluation,
        opened_paper_trade=PaperTradeResponse.model_validate(opened),
    )


def run_strategy_three_paper_execute_once(
    db: Session,
    *,
    context: ContextService,
    market: MarketStoreService,
    settings: Settings,
    entry_enabled: bool = True,
    exit_enabled: bool = True,
) -> StrategyThreeExecuteOnceResponse:
    out = run_strategy_three_paper_exit_once(
        db,
        context=context,
        market=market,
        settings=settings,
        exit_enabled=exit_enabled,
    )
    if out.cycle_action == "closed":
        return out
    entry_out = run_strategy_three_paper_entry_once(
        db,
        context=context,
        market=market,
        settings=settings,
        entry_enabled=entry_enabled,
    )
    if entry_out.had_open_position_at_start:
        return entry_out.model_copy(update={"had_open_position_at_start": out.had_open_position_at_start})
    return entry_out


def run_emergency_close_open_paper_trade(
    db: Session,
    *,
    paper_trade_id: int,
    market: MarketStoreService,
    settings: Settings,
):
    svc = StrategyThreePaperTradeService()
    resolution = market.resolve_spy_market_for_evaluation()
    mstatus = resolution.final_status
    chain = market.get_latest_chain()
    repo = PaperTradeRepository(db)
    row = repo.get_trade(paper_trade_id)
    if row is None or row.strategy_id != svc.STRATEGY_ID or row.status != "open":
        raise PaperTradeError("paper_trade_not_open_for_emergency_close")
    valuation = compute_open_position_valuation(row, chain, settings)
    require_acceptable_exit_quote_for_execution(valuation)
    return svc.close_position(
        db,
        paper_trade_id=paper_trade_id,
        chain=chain,
        market_status=mstatus,
        exit_reason=EMERGENCY_EXIT_REASON,
        settings=settings,
    )
