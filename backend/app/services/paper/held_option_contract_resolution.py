"""Resolve quotes for an open paper option leg (exact symbol), not only near-ATM pool rows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.schemas.market import NearAtmContract


@dataclass(frozen=True)
class HeldOptionContractResolution:
    """Bid/ask for the stored paper ``option_symbol``, from chain snapshot or a direct quote fetch."""

    contract: NearAtmContract
    quote_timestamp: datetime
    source: Literal["chain_near_atm", "direct_dxlink"]


def _parse_occ_tail(option_symbol: str) -> tuple[str | None, float | None, bool, bool]:
    """Parse YYMMDD + C/P + strike*1000 from Tasty-style OCC symbol (e.g. ``SPY  260429C00714000``)."""
    s = option_symbol.strip().replace(" ", "")
    m = re.search(r"(\d{6})([CP])(\d{8})$", s, flags=re.IGNORECASE)
    if not m:
        return None, None, False, False
    yymmdd, cp, strike_raw = m.group(1), m.group(2).upper(), m.group(3)
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    year = 2000 + yy
    exp = f"{year:04d}-{mm:02d}-{dd:02d}"
    strike = int(strike_raw) / 1000.0
    is_call = cp == "C"
    is_put = cp == "P"
    return exp, strike, is_call, is_put


def build_near_atm_contract_for_held_direct_quote(
    option_symbol: str,
    *,
    bid: float | None,
    ask: float | None,
) -> NearAtmContract:
    """Build a ``NearAtmContract`` for valuation/exit when quotes came from a direct DXLink fetch."""
    exp, strike, is_call, is_put = _parse_occ_tail(option_symbol)
    mid: float | None = None
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / 2.0
    spread_d: float | None = None
    spread_pct: float | None = None
    if bid is not None and ask is not None:
        spread_d = max(ask - bid, 0.0)
        if mid is not None and mid > 0:
            spread_pct = spread_d / mid * 100.0
    otype: Literal["call", "put", "unknown"] = "call" if is_call else "put" if is_put else "unknown"
    return NearAtmContract(
        option_symbol=option_symbol.strip(),
        strike=float(strike or 0.0),
        option_type=otype,
        expiration_date=exp,
        bid=bid,
        ask=ask,
        mid=mid,
        delta=None,
        spread_dollars=spread_d,
        spread_percent=spread_pct,
        is_call=is_call,
        is_put=is_put,
    )
