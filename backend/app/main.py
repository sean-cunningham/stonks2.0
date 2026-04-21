import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from app.api.context import router as context_router
from app.api.debug_dxlink import router as debug_dxlink_router
from app.api.health import get_health
from app.api.market import router as market_router
from app.api.paper_strategy_one import router as paper_strategy_one_router
from app.api.strategy_one import router as strategy_one_router
from app.api.system import get_config, get_status, get_strategies
from app.core.config import get_settings
from app.core.database import (
    Base,
    check_database_connectivity,
    delete_legacy_spy_intraday_bars,
    engine,
    ensure_market_snapshot_schema,
    ensure_paper_trade_schema,
    get_db,
)
from app.core.logging import configure_logging
from app.jobs.context_refresh import run_startup_context_refresh
from app.jobs.market_refresh import run_startup_market_refresh
from app.schemas.health import HealthResponse
from app.schemas.system import ConfigResponse, StrategiesResponse, SystemStatusResponse
from app.services.broker.dxlink_spy_candle_streamer import get_spy_candle_streamer

# Import models so SQLAlchemy metadata includes all tables on startup.
from app.models import bars, journal, market, strategy, trade  # noqa: F401 — trade registers PaperTradeEvent

settings = get_settings()
configure_logging(settings.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Database init, legacy bar cleanup, market snapshot refresh, DXLink streamer."""
    s = get_settings()
    Base.metadata.create_all(bind=engine)
    ensure_market_snapshot_schema()
    ensure_paper_trade_schema()
    removed = delete_legacy_spy_intraday_bars()
    logger.info("Legacy SPY intraday bar cleanup removed_rows=%s", removed)
    db_ok = check_database_connectivity()
    logger.info("Starting %s", s.APP_NAME)
    logger.info("Environment=%s mode=%s", s.APP_ENV, s.APP_MODE)
    logger.info("Database connectivity=%s", db_ok)
    run_startup_market_refresh(s)
    streamer = get_spy_candle_streamer(s)
    streamer.hydrate_from_persisted_db()
    streamer.start()
    run_startup_context_refresh(s)
    logger.info("Strategy 1 evaluation and narrow paper-trade persistence are available; live order routing is not implemented.")
    yield
    streamer.stop()


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
app.include_router(market_router)
app.include_router(context_router)
app.include_router(debug_dxlink_router)
app.include_router(strategy_one_router)
app.include_router(paper_strategy_one_router)


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
