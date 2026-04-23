"""Strategy 1 scheduler execution window in US/Eastern (NYSE regular session, v1)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

_ET = ZoneInfo("America/New_York")

# Weekday Mon–Fri; regular hours 9:30 AM–4:00 PM ET, half-open [09:30, 16:00) on the ET calendar date.
_OPEN_MINUTES = 9 * 60 + 30
_CLOSE_MINUTES = 16 * 60


def is_within_spy_rth_et(*, clock_utc: datetime) -> bool:
    """True when ``clock_utc`` falls on a weekday during 09:30–16:00 America/New_York (16:00 exclusive)."""
    if clock_utc.tzinfo is None:
        raise ValueError("clock_utc must be timezone-aware")
    t = clock_utc.astimezone(_ET)
    if t.weekday() >= 5:
        return False
    minutes = t.hour * 60 + t.minute
    return _OPEN_MINUTES <= minutes < _CLOSE_MINUTES
