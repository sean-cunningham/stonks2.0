from app.core.config import get_settings
from app.core.database import check_database_connectivity
from app.core.time import utc_now_iso
from app.schemas.system import ConfigResponse, StrategiesResponse, StrategyMeta, SystemStatusResponse


def get_strategy_catalog() -> list[StrategyMeta]:
    """Return currently supported strategy metadata."""
    return [
        StrategyMeta(
            id="strategy_1_spy_continuation",
            name="SPY Trend Continuation",
            paper_only=True,
            live_order_routing=False,
            ai_enabled=False,
            options_scope="long_calls_and_puts_only",
            universe=["SPY"],
            status="paper_runtime_available",
        ),
        StrategyMeta(
            id="strategy_2_spy_0dte_vol_sniper",
            name="SPY Fast Move Sniper (0DTE)",
            paper_only=True,
            live_order_routing=False,
            ai_enabled=False,
            options_scope="long_calls_and_puts_only",
            universe=["SPY"],
            status="paper_runtime_available",
        ),
    ]


def get_config() -> ConfigResponse:
    """Return safe non-secret app configuration."""
    settings = get_settings()
    safe = settings.safe_public_config()
    return ConfigResponse(**safe, database_connected=check_database_connectivity())


def get_status() -> SystemStatusResponse:
    """Return current system readiness status."""
    settings = get_settings()
    return SystemStatusResponse(
        app_name=settings.APP_NAME,
        environment=settings.APP_ENV,
        mode=settings.APP_MODE,
        database_connected=check_database_connectivity(),
        current_utc_time=utc_now_iso(),
        supported_strategies=[
            "strategy_1_spy_continuation",
            "strategy_2_spy_0dte_vol_sniper",
        ],
        note=(
            "Real SPY market data integration is enabled. Strategy evaluation and "
            "paper execution are available in paper mode; live order routing remains disabled."
        ),
    )


def get_strategies() -> StrategiesResponse:
    """Return metadata for known strategies."""
    return StrategiesResponse(strategies=get_strategy_catalog())
