from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """Return UTC timestamp in ISO-8601 format."""
    return utc_now().isoformat()
