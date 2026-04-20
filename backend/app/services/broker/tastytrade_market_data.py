from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.services.broker.tastytrade_auth import TastytradeAuthService, BrokerAuthError

logger = logging.getLogger(__name__)


class MarketDataError(Exception):
    """Raised when market data cannot be retrieved or normalized."""


@dataclass
class UnderlyingQuoteNormalized:
    """Normalized underlying quote payload."""

    symbol: str
    bid: float | None
    ask: float | None
    mid: float | None
    last: float | None
    quote_timestamp: datetime
    source_status: str


@dataclass
class ChainSummaryNormalized:
    """Normalized chain summary payload."""

    underlying_symbol: str
    snapshot_timestamp: datetime
    expiration_dates_found: list[str]
    selected_expiration: str | None
    underlying_reference_price: float | None
    total_contracts_seen: int
    near_atm_contracts: list[dict[str, Any]]
    source_status: str


class TastytradeMarketDataService:
    """Fetches real SPY quote and option chain data from Tastytrade."""

    def __init__(self, settings: Settings, auth_service: TastytradeAuthService) -> None:
        self._settings = settings
        self._auth_service = auth_service

    def fetch_spy_quote(self) -> UnderlyingQuoteNormalized:
        """Fetch and normalize current SPY quote from Tastytrade."""
        token = self._auth_service.get_access_token()
        quote_data = self._request_first_success(
            base_url=self._settings.TASTYTRADE_API_BASE_URL,
            paths=[
                "/market-data/quotes/SPY",
                "/market-data/quotes?symbols=SPY",
                "/instruments/equities/SPY/quote",
            ],
            token=token.access_token,
        )
        normalized = self._normalize_quote_payload(quote_data, symbol="SPY")
        logger.info("SPY quote refresh success")
        return normalized

    def fetch_spy_option_chain(self, underlying_price: float | None) -> ChainSummaryNormalized:
        """Fetch and normalize current SPY option chain snapshot from Tastytrade."""
        token = self._auth_service.get_access_token()
        chain_data = self._request_first_success(
            base_url=self._settings.TASTYTRADE_API_BASE_URL,
            paths=[
                "/option-chains/SPY",
                "/option-chains/SPY/nested",
                "/market-data/option-chains/SPY",
            ],
            token=token.access_token,
        )
        normalized = self._normalize_chain_payload(
            chain_data=chain_data,
            symbol="SPY",
            underlying_price=underlying_price,
        )
        logger.info("SPY chain refresh success")
        return normalized

    def _request_first_success(self, base_url: str | None, paths: list[str], token: str) -> dict[str, Any]:
        if not base_url:
            raise MarketDataError("missing_credentials")
        headers = {"Authorization": f"Bearer {token}"}
        errors: list[str] = []
        with httpx.Client(timeout=20.0, headers=headers) as client:
            for path in paths:
                url = f"{base_url.rstrip('/')}{path}"
                try:
                    response = client.get(url)
                    response.raise_for_status()
                    payload = response.json()
                    if isinstance(payload, dict):
                        return payload
                except httpx.HTTPError as exc:
                    errors.append(f"{path}:{exc}")
        logger.warning("Broker market-data request failed across endpoints: %s", "; ".join(errors))
        raise MarketDataError("broker_error")

    def _normalize_quote_payload(self, payload: dict[str, Any], symbol: str) -> UnderlyingQuoteNormalized:
        quote_obj = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        if isinstance(quote_obj, dict) and "items" in quote_obj and isinstance(quote_obj["items"], list):
            first = quote_obj["items"][0] if quote_obj["items"] else {}
            if isinstance(first, dict):
                quote_obj = first

        bid = self._to_float(quote_obj.get("bid") or quote_obj.get("bid_price"))
        ask = self._to_float(quote_obj.get("ask") or quote_obj.get("ask_price"))
        last = self._to_float(quote_obj.get("last") or quote_obj.get("last_price"))
        mid = self._calc_mid(bid, ask)
        ts = self._to_datetime(
            quote_obj.get("quote-time")
            or quote_obj.get("quote_time")
            or quote_obj.get("updated_at")
            or quote_obj.get("timestamp")
        )
        if bid is None and ask is None and last is None:
            raise MarketDataError("quote_unavailable")
        return UnderlyingQuoteNormalized(
            symbol=symbol,
            bid=bid,
            ask=ask,
            mid=mid,
            last=last,
            quote_timestamp=ts or datetime.now(timezone.utc),
            source_status="ok",
        )

    def _normalize_chain_payload(
        self,
        chain_data: dict[str, Any],
        symbol: str,
        underlying_price: float | None,
    ) -> ChainSummaryNormalized:
        payload = chain_data.get("data") if isinstance(chain_data.get("data"), dict) else chain_data
        expirations = payload.get("expirations") or payload.get("expiration_dates") or []
        expiration_dates_found = self._extract_expiration_dates(expirations)

        contracts = payload.get("items")
        if not isinstance(contracts, list):
            contracts = self._extract_contracts_from_expirations(expirations)
        if not contracts:
            raise MarketDataError("chain_unavailable")

        selected_exp = expiration_dates_found[0] if expiration_dates_found else None
        near_atm = self._build_near_atm_contracts(contracts, underlying_price)

        if not near_atm:
            raise MarketDataError("chain_unavailable")

        snapshot_ts = datetime.now(timezone.utc)
        reference = underlying_price
        if reference is None and near_atm:
            reference = near_atm[0].get("strike")

        return ChainSummaryNormalized(
            underlying_symbol=symbol,
            snapshot_timestamp=snapshot_ts,
            expiration_dates_found=expiration_dates_found,
            selected_expiration=selected_exp,
            underlying_reference_price=reference,
            total_contracts_seen=len(contracts),
            near_atm_contracts=near_atm,
            source_status="ok",
        )

    def _build_near_atm_contracts(
        self,
        contracts: list[dict[str, Any]],
        underlying_price: float | None,
    ) -> list[dict[str, Any]]:
        parsed: list[tuple[float, dict[str, Any]]] = []
        for contract in contracts:
            if not isinstance(contract, dict):
                continue
            strike = self._to_float(contract.get("strike-price") or contract.get("strike"))
            if strike is None:
                continue
            option_type = str(contract.get("option-type") or contract.get("option_type") or "unknown").lower()
            symbol = str(contract.get("symbol") or contract.get("streamer-symbol") or "")
            if not symbol:
                continue
            bid = self._to_float(contract.get("bid") or contract.get("bid_price"))
            ask = self._to_float(contract.get("ask") or contract.get("ask_price"))
            mid = self._calc_mid(bid, ask)
            delta = self._to_float(contract.get("delta"))
            spread = self._calc_spread(bid, ask)
            spread_pct = (spread / mid) if (spread is not None and mid and mid > 0) else None
            expiration = (
                contract.get("expiration-date")
                or contract.get("expiration_date")
                or contract.get("expires-at")
                or contract.get("expiration")
            )
            normalized = {
                "option_symbol": symbol,
                "strike": strike,
                "option_type": "call" if option_type.startswith("c") else "put" if option_type.startswith("p") else "unknown",
                "expiration_date": str(expiration) if expiration else None,
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "delta": delta,
                "spread_dollars": spread,
                "spread_percent": spread_pct,
                "is_call": option_type.startswith("c"),
                "is_put": option_type.startswith("p"),
            }
            distance = abs(strike - underlying_price) if underlying_price is not None else strike
            parsed.append((distance, normalized))

        parsed.sort(key=lambda item: item[0])
        return [item[1] for item in parsed[:10]]

    @staticmethod
    def _extract_expiration_dates(expirations: Any) -> list[str]:
        if not isinstance(expirations, list):
            return []
        dates: list[str] = []
        for exp in expirations:
            if isinstance(exp, str):
                dates.append(exp)
            elif isinstance(exp, dict):
                date_value = exp.get("expiration-date") or exp.get("expiration_date") or exp.get("date")
                if date_value:
                    dates.append(str(date_value))
        return dates

    @staticmethod
    def _extract_contracts_from_expirations(expirations: Any) -> list[dict[str, Any]]:
        contracts: list[dict[str, Any]] = []
        if not isinstance(expirations, list):
            return contracts
        for exp in expirations:
            if not isinstance(exp, dict):
                continue
            exp_contracts = exp.get("strikes") or exp.get("items") or []
            if isinstance(exp_contracts, list):
                contracts.extend([item for item in exp_contracts if isinstance(item, dict)])
        return contracts

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_datetime(value: Any) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str):
            candidate = value.replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(candidate)
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                return None
        return None

    @staticmethod
    def _calc_mid(bid: float | None, ask: float | None) -> float | None:
        if bid is not None and ask is not None:
            return (bid + ask) / 2
        return None

    @staticmethod
    def _calc_spread(bid: float | None, ask: float | None) -> float | None:
        if bid is not None and ask is not None:
            return max(ask - bid, 0.0)
        return None

