"""US equity regular session (RTH) clock helpers for SPY context (weekday-only, no holiday calendar)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)


def _previous_weekday(d: date) -> date:
    prev = d - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    return prev


def is_us_equity_rth_open(now: datetime) -> bool:
    """
    True during Mon–Fri regular session 09:30–16:00 America/New_York.

    Weekends and US market holidays are not modeled; holidays are treated as
    open/closed according to wall-clock weekday only (narrow scope).
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    et = now.astimezone(ET)
    wd = et.weekday()
    if wd >= 5:
        return False
    t = et.time()
    return RTH_OPEN <= t < RTH_CLOSE


def expected_context_session_date_et(now: datetime) -> date:
    """
    ET session calendar date used to anchor "latest complete session" context.

    - Weekday during RTH: today (ET).
    - Weekday before open: previous business day.
    - After Friday close through Sunday: Friday's session date.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    et = now.astimezone(ET)
    d, t, wd = et.date(), et.time(), et.weekday()
    if wd == 5:
        return d - timedelta(days=1)
    if wd == 6:
        return d - timedelta(days=2)
    if t < RTH_OPEN:
        return _previous_weekday(d)
    return d
