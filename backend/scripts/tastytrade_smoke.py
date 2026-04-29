from __future__ import annotations

from datetime import datetime, timezone
import asyncio
import json
from zoneinfo import ZoneInfo

import websockets

from app.core.config import get_settings
from app.services.broker.tastytrade_auth import TastytradeAuthService
from app.services.broker.tastytrade_market_data import MarketDataError, TastytradeMarketDataService


def _today_et_iso() -> str:
    return datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York")).date().isoformat()


async def _verify_candle_subscribe(dxlink_url: str, token: str) -> None:
    async with websockets.connect(dxlink_url) as ws:
        await ws.send(
            json.dumps(
                {
                    "type": "SETUP",
                    "channel": 0,
                    "keepaliveTimeout": 60,
                    "acceptKeepaliveTimeout": 60,
                    "version": "0.1-DXF-JS/0.3.0",
                }
            )
        )
        await asyncio.wait_for(ws.recv(), timeout=10)
        await ws.send(json.dumps({"type": "AUTH", "channel": 0, "token": token}))
        # AUTH_STATE can transition; wait briefly for AUTHORIZED before failing.
        auth_msg: dict[str, object] | None = None
        auth_deadline = asyncio.get_running_loop().time() + 10.0
        while asyncio.get_running_loop().time() < auth_deadline:
            auth_msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.5))
            if auth_msg.get("type") == "AUTH_STATE" and auth_msg.get("state") == "AUTHORIZED":
                break
            if auth_msg.get("type") == "ERROR":
                raise RuntimeError(f"dxlink_candle_auth_failed:{auth_msg}")
        else:
            raise RuntimeError(f"dxlink_candle_auth_failed:{auth_msg}")
        await ws.send(
            json.dumps(
                {
                    "type": "CHANNEL_REQUEST",
                    "channel": 1,
                    "service": "FEED",
                    "parameters": {"contract": "AUTO"},
                }
            )
        )
        chan_msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        if chan_msg.get("type") != "CHANNEL_OPENED":
            raise RuntimeError(f"dxlink_candle_channel_failed:{chan_msg}")
        await ws.send(
            json.dumps(
                {
                    "type": "FEED_SETUP",
                    "channel": 1,
                    "acceptAggregationPeriod": 0.1,
                    "acceptDataFormat": "COMPACT",
                    "acceptEventFields": {
                        "Candle": [
                            "eventSymbol",
                            "eventTime",
                            "eventFlags",
                            "index",
                            "time",
                            "sequence",
                            "count",
                            "volume",
                            "vwap",
                            "bidVolume",
                            "askVolume",
                            "impVolatility",
                            "openInterest",
                            "open",
                            "high",
                            "low",
                            "close",
                        ]
                    },
                }
            )
        )
        await ws.send(
            json.dumps(
                {
                    "type": "FEED_SUBSCRIPTION",
                    "channel": 1,
                    "add": [{"type": "Candle", "symbol": "SPY{=1m,tho=true}", "fromTime": int(1e9)}],
                }
            )
        )


def main() -> None:
    settings = get_settings()
    auth = TastytradeAuthService(settings)
    market = TastytradeMarketDataService(settings, auth)

    print("[1/5] OAuth refresh token flow...")
    access = auth.get_access_token()
    print("  ok: access token received")

    print("[2/5] api-quote-tokens...")
    quote_token = auth.get_quote_token(access.access_token)
    print(f"  ok: quote token + dxlink url ({quote_token.dxlink_url})")

    print("[3/6] DXLink candle auth/subscription handshake...")
    asyncio.run(_verify_candle_subscribe(quote_token.dxlink_url, quote_token.token))
    print("  ok: candle auth + channel + subscription")

    print("[4/6] SPY equity quote...")
    quote = market.fetch_spy_quote()
    print(f"  ok: bid={quote.bid} ask={quote.ask} mid={quote.mid}")

    print("[5/6] SPY option chain...")
    chain = market.fetch_spy_option_chain(quote.mid or quote.last)
    print(
        f"  ok: contracts_seen={chain.total_contracts_seen} near_atm={len(chain.near_atm_contracts)} "
        f"quote_data_available={chain.quote_data_available}"
    )

    print("[6/6] 0DTE option quotes from chain sample...")
    today = _today_et_iso()
    sample = [c for c in chain.near_atm_contracts if c.get("expiration_date") == today][:5]
    if not sample:
        print("  skipped: no 0DTE contracts in near-atm sample")
        return
    as_of, quote_map = market.fetch_direct_option_quotes([str(c["option_symbol"]) for c in sample])
    print(f"  ok: quoted={len(quote_map)}/{len(sample)} as_of={as_of.isoformat()}")


if __name__ == "__main__":
    try:
        main()
    except (MarketDataError, Exception) as exc:  # noqa: BLE001
        print(f"smoke_failed: {exc}")
        raise

