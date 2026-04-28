from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import threading
from typing import Any

import httpx
import websockets

from app.core.config import Settings
from app.services.broker.tastytrade_auth import BrokerAuthError, TastytradeAuthService
from app.services.paper.strategy_one_entry_policies import (
    SWING_DTE_MAX,
    calendar_dte_to_expiration_us_eastern,
)

logger = logging.getLogger(__name__)

# Near-ATM quote pool: calendar DTE (US/Eastern vs expiration date) for Strategy 1 entry bands
# and future swing coverage. Evaluator still restricts *selection* to intraday 2–5 DTE.
_CHAIN_ENTRY_POOL_DTE_MIN = 0
_CHAIN_ENTRY_POOL_DTE_MAX = SWING_DTE_MAX


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
class OptionContractNormalized:
    """Normalized option contract with optional quote fields."""

    option_symbol: str
    streamer_symbol: str
    strike: float
    option_type: str
    expiration_date: str
    bid: float | None
    ask: float | None
    mid: float | None
    delta: float | None
    spread_dollars: float | None
    spread_percent: float | None
    is_call: bool
    is_put: bool


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
    quote_data_available: bool
    source_status: str


class TastytradeMarketDataService:
    """Fetches real SPY quote and option chain data from Tastytrade."""

    def __init__(self, settings: Settings, auth_service: TastytradeAuthService) -> None:
        self._settings = settings
        self._auth_service = auth_service

    def fetch_spy_quote(self) -> UnderlyingQuoteNormalized:
        """Fetch and normalize current SPY quote via DXLink."""
        access = self._auth_service.get_access_token()
        quote_token = self._auth_service.get_quote_token(access.access_token)
        quote_map = self._fetch_quotes_via_dxlink(quote_token.dxlink_url, quote_token.token, ["SPY"])
        quote = quote_map.get("SPY")
        if not quote:
            raise MarketDataError("quote_unavailable")
        bid = self._to_float(quote.get("bid"))
        ask = self._to_float(quote.get("ask"))
        if bid is None and ask is None:
            raise MarketDataError("quote_unavailable")
        mid = self._calc_mid(bid, ask)
        logger.info("SPY quote refresh success via DXLink")
        return UnderlyingQuoteNormalized(
            symbol="SPY",
            bid=bid,
            ask=ask,
            mid=mid,
            last=mid,
            quote_timestamp=datetime.now(timezone.utc),
            source_status="ok",
        )

    @staticmethod
    def pick_quote_map_entry(
        requested: str, quote_map: dict[str, dict[str, float | str | None]]
    ) -> dict[str, float | str | None] | None:
        """Match DXLink ``eventSymbol`` keys to the requested OCC/streamer string (spacing may differ)."""
        if requested in quote_map:
            return quote_map[requested]
        norm_req = " ".join(requested.split())
        for k, v in quote_map.items():
            if " ".join(str(k).split()) == norm_req:
                return v
        compact_req = requested.replace(" ", "")
        for k, v in quote_map.items():
            if str(k).replace(" ", "") == compact_req:
                return v
        return None

    @staticmethod
    def _compact_option_symbol_key(symbol: str) -> str:
        return "".join(str(symbol).split()).upper()

    def _fetch_spy_chain_contract_items(self, access_token: str) -> list[dict[str, Any]]:
        """Raw option contract dicts from the SPY chain endpoint (flat or nested)."""
        chain_data, _ = self._request_first_success(
            base_url=self._settings.TASTYTRADE_API_BASE_URL,
            paths=[
                "/option-chains/SPY",
                "/option-chains/SPY/nested",
            ],
            token=access_token,
        )
        payload = chain_data.get("data") if isinstance(chain_data.get("data"), dict) else chain_data
        contracts = payload.get("items")
        if not isinstance(contracts, list) or not contracts:
            nested_items = payload.get("items")
            if isinstance(nested_items, list) and nested_items and isinstance(nested_items[0], dict):
                contracts = self._extract_contracts_from_nested_items(nested_items)
        if not isinstance(contracts, list):
            return []
        return contracts

    def _occ_to_streamer_map(self, contracts: list[dict[str, Any]]) -> dict[str, str]:
        """Map compact OCC ``symbol`` -> ``streamer-symbol`` for DXLink FEED subscription."""
        out: dict[str, str] = {}
        for contract in contracts:
            if not isinstance(contract, dict):
                continue
            occ = str(contract.get("symbol") or "").strip()
            if not occ:
                continue
            streamer = str(
                contract.get("streamer-symbol") or contract.get("streamer_symbol") or contract.get("streamerSymbol") or ""
            ).strip()
            if not streamer:
                continue
            key = self._compact_option_symbol_key(occ)
            out.setdefault(key, streamer)
        return out

    @staticmethod
    def _subscription_symbol_likely_streamer(symbol: str) -> bool:
        s = str(symbol).strip()
        return s.startswith(".")

    def fetch_direct_option_quotes(
        self, option_symbols: list[str]
    ) -> tuple[datetime, dict[str, dict[str, float | str | None]]]:
        """Live DXLink quotes for explicit option symbols (OCC or streamer).

        OCC-style symbols (e.g. ``SPY  260429C00714000``) are mapped via the SPY chain instrument
        list to the broker ``streamer-symbol`` before subscribing — DXLink expects the streamer id.
        """
        if not option_symbols:
            return datetime.now(timezone.utc), {}
        access = self._auth_service.get_access_token()
        quote_token = self._auth_service.get_quote_token(access.access_token)
        seen: set[str] = set()
        uniq: list[str] = []
        for s in option_symbols:
            if s and s not in seen:
                seen.add(s)
                uniq.append(s)

        needs_occ_map = any(not self._subscription_symbol_likely_streamer(s) for s in uniq)
        occ_to_streamer: dict[str, str] = {}
        if needs_occ_map:
            items = self._fetch_spy_chain_contract_items(access.access_token)
            occ_to_streamer = self._occ_to_streamer_map(items)

        streamers_to_sub: list[str] = []
        streamer_seen: set[str] = set()
        request_to_streamer: dict[str, str] = {}
        for req in uniq:
            if self._subscription_symbol_likely_streamer(req):
                st = req.strip()
            else:
                key = self._compact_option_symbol_key(req)
                st = occ_to_streamer.get(key)
                if not st:
                    logger.warning(
                        "Option symbol not found in SPY chain for DXLink subscription: %r (compact=%r)",
                        req,
                        key,
                    )
                    raise MarketDataError("option_symbol_not_in_chain_for_direct_quote")
            request_to_streamer[req] = st
            if st not in streamer_seen:
                streamer_seen.add(st)
                streamers_to_sub.append(st)

        quote_map_raw = self._fetch_quotes_via_dxlink(quote_token.dxlink_url, quote_token.token, streamers_to_sub)
        as_of = datetime.now(timezone.utc)
        out: dict[str, dict[str, float | str | None]] = {}
        for req in uniq:
            st = request_to_streamer[req]
            row = self.pick_quote_map_entry(st, quote_map_raw) or self.pick_quote_map_entry(req, quote_map_raw)
            if row is not None:
                out[req] = row
        return as_of, out

    def fetch_spy_option_chain(self, underlying_price: float | None) -> ChainSummaryNormalized:
        """Fetch and normalize current SPY option chain snapshot with quote enrichment."""
        if underlying_price is None:
            raise MarketDataError("quote_unavailable")

        access = self._auth_service.get_access_token()
        chain_data, used_path = self._request_first_success(
            base_url=self._settings.TASTYTRADE_API_BASE_URL,
            paths=[
                "/option-chains/SPY",
                "/option-chains/SPY/nested",
            ],
            token=access.access_token,
        )
        logger.info("SPY chain endpoint success path=%s", used_path)
        logger.info(
            "SPY chain payload shape top_keys=%s data_keys=%s",
            list(chain_data.keys())[:8],
            list(chain_data.get("data", {}).keys())[:8] if isinstance(chain_data.get("data"), dict) else [],
        )
        normalized = self._normalize_chain_payload(
            chain_data=chain_data,
            symbol="SPY",
            underlying_price=underlying_price,
            access_token=access.access_token,
        )
        logger.info("SPY chain refresh success (quote_data_available=%s)", normalized.quote_data_available)
        return normalized

    def _request_first_success(
        self,
        base_url: str | None,
        paths: list[str],
        token: str,
    ) -> tuple[dict[str, Any], str]:
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
                        return payload, path
                except httpx.HTTPError as exc:
                    errors.append(f"{path}:{exc}")
        logger.warning("Broker market-data request failed across endpoints: %s", "; ".join(errors))
        raise MarketDataError("broker_error")

    def _normalize_chain_payload(
        self,
        chain_data: dict[str, Any],
        symbol: str,
        underlying_price: float | None,
        access_token: str,
    ) -> ChainSummaryNormalized:
        payload = chain_data.get("data") if isinstance(chain_data.get("data"), dict) else chain_data
        contracts = payload.get("items")
        if not isinstance(contracts, list) or not contracts:
            nested_items = payload.get("items")
            if isinstance(nested_items, list) and nested_items and isinstance(nested_items[0], dict):
                contracts = self._extract_contracts_from_nested_items(nested_items)
        if not contracts:
            raise MarketDataError("chain_unavailable")

        expiration_dates_found = self._extract_expiration_dates_from_items(contracts)
        as_of_utc = datetime.now(timezone.utc)
        near_contracts = self._build_near_atm_contracts_entry_pool(
            contracts,
            underlying_price,
            expiration_dates_found,
            as_of_utc=as_of_utc,
        )
        if not near_contracts:
            raise MarketDataError("chain_unavailable")

        quote_symbols = [contract.streamer_symbol for contract in near_contracts]
        quote_token = self._auth_service.get_quote_token(access_token)
        option_quotes = self._fetch_quotes_via_dxlink(quote_token.dxlink_url, quote_token.token, quote_symbols)
        near_atm = self._merge_option_quotes(near_contracts, option_quotes)

        if not near_atm:
            raise MarketDataError("chain_unavailable")

        snapshot_ts = datetime.now(timezone.utc)
        quote_data_available = any(c.get("mid") is not None or c.get("bid") is not None for c in near_atm)
        source_status = "ok" if quote_data_available else "chain_quotes_unavailable"

        return ChainSummaryNormalized(
            underlying_symbol=symbol,
            snapshot_timestamp=snapshot_ts,
            expiration_dates_found=expiration_dates_found,
            # Multi-expiry near-ATM pool; do not use a single expiry for downstream filtering.
            selected_expiration=None,
            underlying_reference_price=underlying_price,
            total_contracts_seen=len(contracts),
            near_atm_contracts=near_atm,
            quote_data_available=quote_data_available,
            source_status=source_status,
        )

    def _build_near_atm_contracts_entry_pool(
        self,
        contracts: list[dict[str, Any]],
        underlying_price: float | None,
        expiration_dates_found: list[str],
        *,
        as_of_utc: datetime,
    ) -> list[OptionContractNormalized]:
        """Collect near-ATM rows across expirations in a bounded DTE window (calendar US/Eastern)."""
        if underlying_price is None:
            return []
        eligible: set[str] = set()
        for exp in expiration_dates_found:
            try:
                dte = calendar_dte_to_expiration_us_eastern(expiration_date_str=exp, as_of_utc=as_of_utc)
            except (TypeError, ValueError):
                continue
            if _CHAIN_ENTRY_POOL_DTE_MIN <= dte <= _CHAIN_ENTRY_POOL_DTE_MAX:
                eligible.add(exp)

        parsed: list[tuple[float, OptionContractNormalized]] = []
        for contract in contracts:
            if not isinstance(contract, dict):
                continue
            expiration = (
                contract.get("expiration-date")
                or contract.get("expiration_date")
                or contract.get("expires-at")
                or contract.get("expiration")
            )
            exp_s = str(expiration) if expiration else ""
            if exp_s not in eligible:
                continue
            strike = self._to_float(contract.get("strike-price") or contract.get("strike"))
            if strike is None:
                continue
            option_type = str(contract.get("option-type") or contract.get("option_type") or "unknown").lower()
            symbol = str(contract.get("symbol") or "")
            streamer_symbol = str(contract.get("streamer-symbol") or symbol)
            if not symbol:
                continue
            normalized = OptionContractNormalized(
                option_symbol=symbol,
                streamer_symbol=streamer_symbol,
                strike=strike,
                option_type="call" if option_type.startswith("c") else "put" if option_type.startswith("p") else "unknown",
                expiration_date=exp_s,
                bid=None,
                ask=None,
                mid=None,
                delta=None,
                spread_dollars=None,
                spread_percent=None,
                is_call=option_type.startswith("c"),
                is_put=option_type.startswith("p"),
            )
            distance = abs(strike - float(underlying_price))
            parsed.append((distance, normalized))

        parsed.sort(key=lambda item: item[0])
        near = [item[1] for item in parsed[:36]]
        calls = [c for c in near if c.is_call][:9]
        puts = [c for c in near if c.is_put][:9]
        return calls + puts

    def _merge_option_quotes(
        self,
        contracts: list[OptionContractNormalized],
        quote_map: dict[str, dict[str, float | str | None]],
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        for contract in contracts:
            quote = quote_map.get(contract.streamer_symbol) or quote_map.get(contract.option_symbol) or {}
            bid = self._to_float(quote.get("bid"))
            ask = self._to_float(quote.get("ask"))
            mid = self._calc_mid(bid, ask)
            spread = self._calc_spread(bid, ask)
            spread_pct = (spread / mid) if (spread is not None and mid and mid > 0) else None
            merged.append(
                {
                    "option_symbol": contract.option_symbol,
                    "strike": contract.strike,
                    "option_type": contract.option_type,
                    "expiration_date": contract.expiration_date,
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "delta": contract.delta,
                    "spread_dollars": spread,
                    "spread_percent": spread_pct,
                    "is_call": contract.is_call,
                    "is_put": contract.is_put,
                }
            )
        return merged

    def _fetch_quotes_via_dxlink(
        self,
        dxlink_url: str,
        quote_token: str,
        symbols: list[str],
    ) -> dict[str, dict[str, float | str | None]]:
        coroutine = self._fetch_quotes_via_dxlink_async(dxlink_url, quote_token, symbols)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coroutine)
        return self._run_coroutine_in_thread(coroutine)

    @staticmethod
    def _run_coroutine_in_thread(coroutine: Any) -> dict[str, dict[str, float | str | None]]:
        result: dict[str, dict[str, float | str | None]] = {}
        error: Exception | None = None

        def _runner() -> None:
            nonlocal result, error
            try:
                result = asyncio.run(coroutine)
            except Exception as exc:  # noqa: BLE001
                error = exc

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        thread.join()
        if error is not None:
            raise error
        return result

    async def _fetch_quotes_via_dxlink_async(
        self,
        dxlink_url: str,
        quote_token: str,
        symbols: list[str],
    ) -> dict[str, dict[str, float | str | None]]:
        if not symbols:
            return {}
        results: dict[str, dict[str, float | str | None]] = {}
        async with websockets.connect(dxlink_url) as ws:
            await ws.send(
                self._json_message(
                    {
                        "type": "SETUP",
                        "channel": 0,
                        "keepaliveTimeout": 60,
                        "acceptKeepaliveTimeout": 60,
                        "version": "0.1-js/1.0.0",
                    }
                )
            )
            await self._recv_until(ws, lambda m: m.get("type") == "SETUP")

            await ws.send(self._json_message({"type": "AUTH", "channel": 0, "token": quote_token}))
            await self._recv_until(
                ws,
                lambda m: m.get("type") == "AUTH_STATE" and m.get("state") == "AUTHORIZED",
            )

            await ws.send(
                self._json_message(
                    {"type": "CHANNEL_REQUEST", "channel": 1, "service": "FEED", "parameters": {"contract": "AUTO"}}
                )
            )
            await self._recv_until(
                ws,
                lambda m: m.get("type") == "CHANNEL_OPENED" and m.get("channel") == 1,
            )

            await ws.send(
                self._json_message(
                    {
                        "type": "FEED_SETUP",
                        "channel": 1,
                        "acceptAggregationPeriod": 1,
                        "acceptDataFormat": "COMPACT",
                        "acceptEventFields": {"Quote": ["eventSymbol", "bidPrice", "askPrice", "bidTime", "askTime"]},
                    }
                )
            )
            await ws.send(
                self._json_message(
                    {
                        "type": "FEED_SUBSCRIPTION",
                        "channel": 1,
                        "add": [{"type": "Quote", "symbol": symbol} for symbol in symbols],
                    }
                )
            )

            deadline = asyncio.get_running_loop().time() + 7.0
            while asyncio.get_running_loop().time() < deadline and len(results) < len(symbols):
                try:
                    payload = await asyncio.wait_for(ws.recv(), timeout=1.5)
                except TimeoutError:
                    continue
                message = self._parse_json_message(payload)
                if message.get("type") != "FEED_DATA":
                    continue
                data = message.get("data")
                if not isinstance(data, list) or len(data) < 2 or data[0] != "Quote":
                    continue
                compact_values = data[1]
                if not isinstance(compact_values, list):
                    continue
                for idx in range(0, len(compact_values), 5):
                    chunk = compact_values[idx : idx + 5]
                    if len(chunk) < 3:
                        continue
                    event_symbol = str(chunk[0])
                    results[event_symbol] = {
                        "bid": self._to_float(chunk[1]),
                        "ask": self._to_float(chunk[2]),
                    }
        return results

    async def _recv_until(self, ws: Any, predicate: Any, timeout: float = 10.0) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            payload = await asyncio.wait_for(ws.recv(), timeout=max(deadline - loop.time(), 0.1))
            message = self._parse_json_message(payload)
            if message.get("type") == "KEEPALIVE":
                continue
            if predicate(message):
                return message
            if message.get("type") == "ERROR":
                raise MarketDataError("broker_error")
        raise MarketDataError("broker_error")

    @staticmethod
    def _parse_json_message(payload: str) -> dict[str, Any]:
        try:
            decoded = json.loads(payload)
            return decoded if isinstance(decoded, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _json_message(payload: dict[str, Any]) -> str:
        return json.dumps(payload)

    @staticmethod
    def _extract_expiration_dates_from_items(items: list[dict[str, Any]]) -> list[str]:
        dates: list[str] = []
        for item in items:
            date_value = item.get("expiration-date") or item.get("expiration_date")
            if date_value:
                dates.append(str(date_value))
        return sorted(set(dates))

    @staticmethod
    def _extract_contracts_from_nested_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        contracts: list[dict[str, Any]] = []
        for item in items:
            expirations = item.get("expirations")
            if not isinstance(expirations, list):
                continue
            for exp in expirations:
                if not isinstance(exp, dict):
                    continue
                exp_date = exp.get("expiration-date") or exp.get("expiration_date")
                strikes = exp.get("strikes") if isinstance(exp, dict) else None
                if isinstance(strikes, list):
                    for strike in strikes:
                        if not isinstance(strike, dict):
                            continue
                        merged = dict(strike)
                        if exp_date:
                            merged.setdefault("expiration-date", str(exp_date))
                            merged.setdefault("expiration_date", str(exp_date))
                        contracts.append(merged)
        return contracts

    @staticmethod
    def _select_expiration(expiration_dates: list[str]) -> str | None:
        if not expiration_dates:
            return None
        today = datetime.now(timezone.utc).date()
        parsed: list[tuple[datetime.date, str]] = []
        for value in expiration_dates:
            try:
                parsed_date = datetime.strptime(value, "%Y-%m-%d").date()
                parsed.append((parsed_date, value))
            except ValueError:
                continue
        if not parsed:
            return None
        future = [item for item in parsed if item[0] >= today]
        target = min(future, key=lambda item: item[0]) if future else min(parsed, key=lambda item: item[0])
        return target[1]

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
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

