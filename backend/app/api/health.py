from app.schemas.health import HealthResponse


def get_health() -> HealthResponse:
    """Return simple service liveness information."""
    return HealthResponse(status="alive")
