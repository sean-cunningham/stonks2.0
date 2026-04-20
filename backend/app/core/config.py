from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    APP_NAME: str = "stonks2.0"
    APP_ENV: str = "development"
    APP_MODE: Literal["paper", "mock"] = "paper"
    API_HOST: str = "127.0.0.1"
    API_PORT: int = 8000
    DATABASE_URL: str = "sqlite:///./stonks2.db"
    LOG_LEVEL: str = "INFO"

    # Tastytrade placeholders for future integration only.
    TASTYTRADE_OAUTH_CLIENT_ID: Optional[str] = Field(default=None)
    TASTYTRADE_OAUTH_CLIENT_SECRET: Optional[str] = Field(default=None)
    TASTYTRADE_REFRESH_TOKEN: Optional[str] = Field(default=None)
    TASTYTRADE_ACCOUNT_NUMBER: Optional[str] = Field(default=None)
    TASTYTRADE_API_BASE_URL: Optional[str] = Field(default=None)
    TASTYTRADE_DX_URL: Optional[str] = Field(default=None)

    model_config = SettingsConfigDict(
        env_file=".env",
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
