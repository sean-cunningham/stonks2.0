"""Restate exit_price / realized_pnl for a closed Strategy 1 paper trade using a live option bid.

Uses DXLink via Tastytrade (same path as held-leg quotes). This is the bid at *script run time*,
not a historical bid at the original exit_time — use only to replace clearly wrong synthetic
exits (e.g. emergency unquoted $0) when a current quote is acceptable as an approximation.

Run from ``backend`` with ``PYTHONPATH=.``::

    python scripts/restate_closed_paper_trade_exit.py --paper-trade-id 2
    python scripts/restate_closed_paper_trade_exit.py --paper-trade-id 2 --dry-run
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.trade import PaperTradeEvent
from app.repositories.paper_trade_repository import PaperTradeRepository
from app.services.broker.tastytrade_auth import BrokerAuthError, TastytradeAuthService
from app.services.broker.tastytrade_market_data import MarketDataError, TastytradeMarketDataService
from app.services.paper.contract_constants import OPTION_CONTRACT_MULTIPLIER
from app.services.paper.paper_trade_service import (
    MANUAL_EMERGENCY_CLOSE_AT_MARKET_BID,
    MANUAL_EMERGENCY_CLOSE_UNQUOTED,
    PaperTradeService,
)


def _parse_bid(
    option_symbol: str, quote_map: dict[str, dict[str, float | str | None]]
) -> tuple[float, float | None]:
    raw = TastytradeMarketDataService.pick_quote_map_entry(option_symbol, quote_map)
    if raw is None:
        raise RuntimeError(f"No quote map entry for {option_symbol!r}; keys={list(quote_map)[:12]!r}")
    bid = TastytradeMarketDataService._to_float(raw.get("bid"))
    ask = TastytradeMarketDataService._to_float(raw.get("ask"))
    if bid is None or bid <= 0:
        raise RuntimeError(f"Missing or non-positive bid for {option_symbol!r}: bid={bid!r}")
    if ask is not None and bid is not None and ask < bid:
        raise RuntimeError(f"Invalid bid/ask for {option_symbol!r}: bid={bid} ask={ask}")
    return bid, ask


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paper-trade-id", type=int, default=2)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch quote and print proposed update without committing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow restating even if exit was not unquoted / non-zero (use with care).",
    )
    args = parser.parse_args()

    settings = get_settings()
    svc = PaperTradeService()
    db = SessionLocal()
    try:
        repo = PaperTradeRepository(db)
        row = repo.get_trade(args.paper_trade_id)
        if row is None:
            print(f"paper_trade id={args.paper_trade_id} not found", file=sys.stderr)
            return 1
        if row.strategy_id != svc.strategy_id:
            print(f"Expected strategy_id={svc.strategy_id!r}, got {row.strategy_id!r}", file=sys.stderr)
            return 1
        if row.status != "closed":
            print(f"Trade is not closed (status={row.status!r})", file=sys.stderr)
            return 1

        is_unquoted = (row.exit_reason or "").strip() == MANUAL_EMERGENCY_CLOSE_UNQUOTED
        zero_exit = row.exit_price is not None and float(row.exit_price) <= 0.0
        if not args.force and not (is_unquoted or zero_exit):
            print(
                "Refusing: exit does not look like synthetic emergency "
                f"(exit_reason={row.exit_reason!r}, exit_price={row.exit_price!r}). "
                "Pass --force to override.",
                file=sys.stderr,
            )
            return 1

        auth = TastytradeAuthService(settings)
        md = TastytradeMarketDataService(settings, auth)
        try:
            quote_ts, quote_map = md.fetch_direct_option_quotes([row.option_symbol])
        except (BrokerAuthError, MarketDataError, OSError, RuntimeError) as exc:
            print(f"Quote fetch failed: {exc}", file=sys.stderr)
            return 1

        bid, _ask = _parse_bid(row.option_symbol, quote_map)
        old_exit = float(row.exit_price) if row.exit_price is not None else None
        old_reason = row.exit_reason
        old_pnl = float(row.realized_pnl) if row.realized_pnl is not None else None
        entry = float(row.entry_price)
        qty = int(row.quantity)
        realized = (bid - entry) * OPTION_CONTRACT_MULTIPLIER * qty

        print("--- Restatement preview (live bid at fetch time, not historical exit) ---")
        print(f"paper_trade_id={row.id} option_symbol={row.option_symbol!r}")
        print(f"quote_fetch_utc={quote_ts.isoformat()} bid_per_share={bid}")
        print(f"entry_price_per_share={entry} quantity={qty}")
        print(f"old: exit_price={old_exit!r} exit_reason={old_reason!r} realized_pnl={old_pnl!r}")
        print(f"new: exit_price={bid} exit_reason={MANUAL_EMERGENCY_CLOSE_AT_MARKET_BID!r} realized_pnl={realized}")

        if args.dry_run:
            print("(dry-run: no DB writes)")
            return 0

        row.exit_price = bid
        row.exit_reference_basis = "option_bid"
        row.exit_reason = MANUAL_EMERGENCY_CLOSE_AT_MARKET_BID
        row.realized_pnl = realized
        repo.update_trade(row)
        repo.append_event(
            PaperTradeEvent(
                paper_trade_id=row.id,
                event_time=datetime.now(timezone.utc),
                event_type="correction",
                details_json={
                    "note": "restatement_from_live_dxlink_bid_after_synthetic_exit",
                    "prior_exit_price_per_share": old_exit,
                    "prior_exit_reason": old_reason,
                    "prior_realized_pnl": old_pnl,
                    "new_exit_price_per_share": bid,
                    "new_exit_reason": MANUAL_EMERGENCY_CLOSE_AT_MARKET_BID,
                    "new_realized_pnl": realized,
                    "quote_fetch_utc": quote_ts.isoformat(),
                    "exit_reference_basis": "option_bid",
                },
            )
        )
        print("Committed (paper_trades + paper_trade_events).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
