import logging

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from app.api.health import get_health
from app.api.system import get_config, get_status, get_strategies
from app.core.config import get_settings
from app.core.database import Base, check_database_connectivity, engine, get_db
from app.core.logging import configure_logging
from app.schemas.health import HealthResponse
from app.schemas.system import ConfigResponse, StrategiesResponse, SystemStatusResponse

# Import models so SQLAlchemy metadata includes all tables on startup.
from app.models import journal, market, strategy, trade  # noqa: F401

settings = get_settings()
configure_logging(settings.LOG_LEVEL)
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.APP_NAME)


@app.on_event("startup")
def on_startup() -> None:
    """Initialize database and report startup status."""
    Base.metadata.create_all(bind=engine)
    db_ok = check_database_connectivity()
    logger.info("Starting %s", settings.APP_NAME)
    logger.info("Environment=%s mode=%s", settings.APP_ENV, settings.APP_MODE)
    logger.info("Database connectivity=%s", db_ok)
    logger.info(
        "Broker/data/strategy execution layers are not implemented yet; system is not ready for trading."
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness endpoint."""
    return get_health()


@app.get("/system/config", response_model=ConfigResponse)
def system_config(db: Session = Depends(get_db)) -> ConfigResponse:
    """Safe non-secret configuration endpoint."""
    _ = db
    return get_config()


@app.get("/system/status", response_model=SystemStatusResponse)
def system_status(db: Session = Depends(get_db)) -> SystemStatusResponse:
    """Current runtime status endpoint."""
    _ = db
    return get_status()


@app.get("/system/strategies", response_model=StrategiesResponse)
def system_strategies(db: Session = Depends(get_db)) -> StrategiesResponse:
    """Known strategy metadata endpoint."""
    _ = db
    return get_strategies()
