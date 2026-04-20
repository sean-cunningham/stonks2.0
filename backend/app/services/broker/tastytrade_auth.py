from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


class BrokerAuthError(Exception):
    """Raised when Tastytrade authentication fails."""


@dataclass
class TastytradeToken:
    """Bearer token wrapper."""

    access_token: str
    token_type: str = "Bearer"


class TastytradeAuthService:
    """Handles Tastytrade OAuth refresh-token auth flow."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def has_credentials(self) -> bool:
        """Return whether minimum auth credentials are present."""
        return bool(
            self._settings.TASTYTRADE_OAUTH_CLIENT_ID
            and self._settings.TASTYTRADE_OAUTH_CLIENT_SECRET
            and self._settings.TASTYTRADE_REFRESH_TOKEN
            and self._settings.TASTYTRADE_API_BASE_URL
        )

    def get_access_token(self) -> TastytradeToken:
        """Fetch fresh bearer token from Tastytrade OAuth endpoint."""
        if not self.has_credentials():
            raise BrokerAuthError("missing_credentials")

        token_url = f"{self._settings.TASTYTRADE_API_BASE_URL.rstrip('/')}/oauth/token"
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._settings.TASTYTRADE_REFRESH_TOKEN,
            "client_id": self._settings.TASTYTRADE_OAUTH_CLIENT_ID,
            "client_secret": self._settings.TASTYTRADE_OAUTH_CLIENT_SECRET,
        }

        try:
            with httpx.Client(timeout=15.0) as client:
                response = client.post(token_url, data=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPError as exc:
            logger.warning("Tastytrade auth failed: %s", exc)
            raise BrokerAuthError("broker_error") from exc

        access_token = (
            body.get("access_token")
            or body.get("data", {}).get("access_token")
            or body.get("token")
            or body.get("session-token")
        )
        if not access_token:
            logger.warning("Tastytrade auth response missing access token")
            raise BrokerAuthError("broker_error")

        logger.info("Tastytrade auth success")
        return TastytradeToken(access_token=access_token, token_type="Bearer")

