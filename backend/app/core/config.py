from functools import lru_cache
from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_PATH = (BASE_DIR / "stonks2.db").as_posix()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    APP_NAME: str = "stonks2.0"
    APP_ENV: str = "development"
    APP_MODE: Literal["paper", "mock"] = "paper"
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000
    DATABASE_URL: str = f"sqlite:///{DEFAULT_SQLITE_PATH}"
    LOG_LEVEL: str = "INFO"

    # Tastytrade placeholders for future integration only.
    TASTYTRADE_OAUTH_CLIENT_ID: Optional[str] = Field(default=None)
    TASTYTRADE_OAUTH_CLIENT_SECRET: Optional[str] = Field(default=None)
    TASTYTRADE_REFRESH_TOKEN: Optional[str] = Field(default=None)
    TASTYTRADE_ACCOUNT_NUMBER: Optional[str] = Field(default=None)
    TASTYTRADE_API_BASE_URL: Optional[str] = Field(default=None)
    TASTYTRADE_DX_URL: Optional[str] = Field(default=None)
    MARKET_QUOTE_MAX_AGE_SECONDS: int = 15
    MARKET_CHAIN_MAX_AGE_SECONDS: int = 60
    MARKET_CHAIN_REFRESH_SECONDS: int = 30

    # SPY intraday context (1m from DXLink stream, 5m aggregated locally)
    OPENING_RANGE_MINUTES: int = 30
    CONTEXT_BAR_MAX_STALENESS_SECONDS_1M: int = 120
    CONTEXT_BAR_MAX_STALENESS_SECONDS_5M: int = 300
    CONTEXT_STARTUP_REFRESH: bool = False
    CONTEXT_MAX_BARS_PERSISTED_PER_TF: int = 600

    # Paper Strategy 1 — small-account profile for entry-time sizing (not broker equity).
    PAPER_STRATEGY1_ACCOUNT_EQUITY_USD: float = 5000.0
    STRATEGY1_PAPER_RUNTIME_ENABLED: bool = False
    STRATEGY1_PAPER_EXECUTE_OFFSET_SECONDS: int = 4

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    def safe_public_config(self) -> dict[str, str | int]:
        """Return non-secret config fields safe for API output."""
        return {
            "app_name": self.APP_NAME,
            "app_env": self.APP_ENV,
            "app_mode": self.APP_MODE,
            "api_host": self.API_HOST,
            "api_port": self.API_PORT,
            "database_url": self.DATABASE_URL,
            "log_level": self.LOG_LEVEL,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached application settings instance."""
    return Settings()
