"""Long-lived Tastytrade DXLink WebSocket: SPY 1m Candle events → SQLite intraday bars."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import websockets

from app.core.config import Settings
from app.core.database import SessionLocal
from app.models.bars import IntradayBar
from app.repositories.bars_repository import BarsRepository
from app.services.broker.tastytrade_auth import BrokerAuthError, TastytradeAuthService
from app.services.market.bar_aggregate import (
    DXLINK_BAR_SOURCE,
    aggregate_1m_to_5m_bar,
    five_consecutive_1m_bars_for_bucket,
    five_minute_bucket_start_utc,
)

logger = logging.getLogger(__name__)

DXLINK_VERSION = "0.1-DXF-JS/0.3.0"
CANDLE_FEED_CHANNEL = 1
SPY_CANDLE_SYMBOL = "SPY{=1m,tho=true}"

# COMPACT field order for FEED_SETUP (camelCase per DXLink / tastytrade SDK).
CANDLE_ACCEPT_EVENT_FIELDS = [
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

CANDLE_FIELD_COUNT = len(CANDLE_ACCEPT_EVENT_FIELDS)

# dxfeed IndexedEvent flags (subset)
REMOVE_EVENT = 0x2
SNAPSHOT_END = 0x8
SNAPSHOT_SNIP = 0x10

# Debug / health: parser identifier for API clients
CANDLE_PARSER_MODE = "candle_compact_v1_18fields_sdk_order"

_spy_streamer_lock = threading.Lock()
_spy_streamer: DxLinkSpyCandleStreamer | None = None


@dataclass
class DxLinkHealthSnapshot:
    """Thread-safe copy of streamer health for APIs and context gating."""

    connected: bool
    subscribed: bool
    last_message_time: datetime | None
    last_candle_time: datetime | None
    quote_token_present: bool
    dxlink_url_present: bool
    reconnect_count: int
    source_status: str
    last_error: str | None
    subscribed_symbol: str
    event_type: str
    parser_mode: str
    latest_raw_period_time: datetime | None
    latest_raw_event_time: datetime | None
    latest_raw_close: float | None
    latest_persisted_1m_bar_time: datetime | None
    latest_persisted_1m_close: float | None


@dataclass
class _MinuteBuffer:
    """Latest OHLCV for one candle period (ms since epoch UTC)."""

    time_ms: int
    event_symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: float | None


@dataclass
class DxLinkSpyCandleStreamer:
    """Background reconnecting DXLink consumer for SPY 1m candles."""

    settings: Settings
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)
    _state_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _connected: bool = False
    _subscribed: bool = False
    _last_message_time: datetime | None = None
    _quote_token_present: bool = False
    _dxlink_url_present: bool = False
    _reconnect_count: int = 0
    _last_error: str | None = None
    _last_candle_period_ms_max: int = 0
    _last_persisted_1m_bar_time: datetime | None = None
    _last_persisted_1m_close: float | None = None
    # Latest candle rows keyed by period start (time ms); trimmed to recent keys only.
    _debug_by_period_ms: dict[int, dict[str, Any]] = field(default_factory=dict, repr=False)
    _debug_max_periods: int = 256

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._thread_main, name="dxlink-spy-candles", daemon=True)
        self._thread.start()
        logger.info("DXLink SPY candle streamer thread started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=8.0)
        logger.info("DXLink SPY candle streamer stopped")

    def health_snapshot(self) -> DxLinkHealthSnapshot:
        with self._state_lock:
            stream_latest = self._latest_raw_period_time_locked()
            persisted_t = self._last_persisted_1m_bar_time
            last_candle = stream_latest
            if persisted_t is not None and (last_candle is None or persisted_t > last_candle):
                last_candle = persisted_t
            latest_raw_period = stream_latest
            latest_raw_evt = self._latest_raw_event_time_locked()
            latest_raw_close = self._latest_raw_close_locked()
            return DxLinkHealthSnapshot(
                connected=self._connected,
                subscribed=self._subscribed,
                last_message_time=self._last_message_time,
                last_candle_time=last_candle,
                quote_token_present=self._quote_token_present,
                dxlink_url_present=self._dxlink_url_present,
                reconnect_count=self._reconnect_count,
                source_status=self._source_status_locked(),
                last_error=self._last_error,
                subscribed_symbol=SPY_CANDLE_SYMBOL,
                event_type="Candle",
                parser_mode=CANDLE_PARSER_MODE,
                latest_raw_period_time=latest_raw_period,
                latest_raw_event_time=latest_raw_evt,
                latest_raw_close=latest_raw_close,
                latest_persisted_1m_bar_time=persisted_t,
                latest_persisted_1m_close=self._last_persisted_1m_close,
            )

    def _latest_raw_event_time_locked(self) -> datetime | None:
        if not self._debug_by_period_ms:
            return None
        best: datetime | None = None
        for row in self._debug_by_period_ms.values():
            et = row.get("event_time_utc")
            if isinstance(et, datetime) and (best is None or et > best):
                best = et
        return best

    def _latest_raw_period_time_locked(self) -> datetime | None:
        if self._last_candle_period_ms_max <= 0:
            return None
        return datetime.fromtimestamp(self._last_candle_period_ms_max / 1000.0, tz=timezone.utc)

    def _latest_raw_close_locked(self) -> float | None:
        if not self._debug_by_period_ms:
            return None
        max_ms = max(self._debug_by_period_ms.keys())
        row = self._debug_by_period_ms.get(max_ms)
        if not row:
            return None
        c = row.get("close")
        return float(c) if c is not None else None

    def recent_decoded_candles(self, limit: int = 12) -> list[dict[str, Any]]:
        """Most recent candle periods by `time` (period start), newest last."""
        with self._state_lock:
            keys = sorted(self._debug_by_period_ms.keys())
            chosen = keys[-limit:] if limit else keys
            return [self._debug_by_period_ms[k] for k in chosen]

    def hydrate_from_persisted_db(self) -> None:
        """Align streamer watermarks with latest DXLink 1m row after process restart."""
        db = SessionLocal()
        try:
            repo = BarsRepository(db)
            b = repo.latest_spy_1m_dxlink()
            if b is None:
                return
            bt = b.bar_time if b.bar_time.tzinfo else b.bar_time.replace(tzinfo=timezone.utc)
            bt = bt.astimezone(timezone.utc)
            period_ms = int(bt.timestamp() * 1000)
            with self._state_lock:
                self._last_persisted_1m_bar_time = bt
                self._last_persisted_1m_close = float(b.close)
                self._last_candle_period_ms_max = max(self._last_candle_period_ms_max, period_ms)
        finally:
            db.close()

    def _source_status_locked(self) -> str:
        if self._connected and self._subscribed:
            return "ok"
        if self._last_error:
            return f"degraded:{self._last_error}"
        return "degraded:not_ready"

    def _set_error(self, msg: str) -> None:
        with self._state_lock:
            self._last_error = msg
            self._connected = False
            self._subscribed = False

    def _thread_main(self) -> None:
        while not self._stop.is_set():
            try:
                asyncio.run(self._run_session_until_disconnect())
            except BrokerAuthError as exc:
                self._set_error(f"auth:{exc}")
                logger.warning("DXLink candle stream auth failure: %s", exc)
            except Exception as exc:  # noqa: BLE001
                self._set_error(f"error:{exc}")
                logger.exception("DXLink candle stream fatal loop error")
            if self._stop.is_set():
                break
            with self._state_lock:
                self._reconnect_count += 1
            delay = min(60.0, 1.5 ** min(self._reconnect_count, 12))
            logger.info("DXLink candle stream reconnecting in %.1fs (count=%s)", delay, self._reconnect_count)
            self._stop.wait(delay)

    async def _run_session_until_disconnect(self) -> None:
        auth = TastytradeAuthService(self.settings)
        if not auth.has_credentials():
            self._set_error("missing_credentials")
            raise BrokerAuthError("missing_credentials")

        access = auth.get_access_token()
        quote = auth.get_quote_token(access.access_token)
        with self._state_lock:
            self._quote_token_present = bool(quote.token)
            self._dxlink_url_present = bool(quote.dxlink_url)
            self._last_error = None

        async with websockets.connect(quote.dxlink_url) as ws:
            await self._dxlink_handshake_and_subscribe(ws, quote.token)
            with self._state_lock:
                self._connected = True
                self._subscribed = True
            logger.info("DXLink SPY candle subscription active symbol=%s", SPY_CANDLE_SYMBOL)

            keepalive_task = asyncio.create_task(self._keepalive_loop(ws))
            try:
                await self._receive_loop(ws)
            finally:
                keepalive_task.cancel()
                try:
                    await keepalive_task
                except asyncio.CancelledError:
                    pass
                with self._state_lock:
                    self._connected = False
                    self._subscribed = False

    async def _keepalive_loop(self, ws: Any) -> None:
        while True:
            await asyncio.sleep(30.0)
            await ws.send(json.dumps({"type": "KEEPALIVE", "channel": 0}))

    async def _dxlink_handshake_and_subscribe(self, ws: Any, quote_token: str) -> None:
        await ws.send(
            json.dumps(
                {
                    "type": "SETUP",
                    "channel": 0,
                    "keepaliveTimeout": 60,
                    "acceptKeepaliveTimeout": 60,
                    "version": DXLINK_VERSION,
                }
            )
        )
        await self._recv_until(ws, lambda m: m.get("type") == "SETUP")

        await ws.send(json.dumps({"type": "AUTH", "channel": 0, "token": quote_token}))
        await self._recv_until(
            ws,
            lambda m: m.get("type") == "AUTH_STATE" and m.get("state") == "AUTHORIZED",
        )

        await ws.send(
            json.dumps(
                {
                    "type": "CHANNEL_REQUEST",
                    "channel": CANDLE_FEED_CHANNEL,
                    "service": "FEED",
                    "parameters": {"contract": "AUTO"},
                }
            )
        )
        await self._recv_until(
            ws,
            lambda m: m.get("type") == "CHANNEL_OPENED" and m.get("channel") == CANDLE_FEED_CHANNEL,
        )

        await ws.send(
            json.dumps(
                {
                    "type": "FEED_SETUP",
                    "channel": CANDLE_FEED_CHANNEL,
                    "acceptAggregationPeriod": 0.1,
                    "acceptDataFormat": "COMPACT",
                    "acceptEventFields": {"Candle": CANDLE_ACCEPT_EVENT_FIELDS},
                }
            )
        )

        from_time = int(1e9)
        await ws.send(
            json.dumps(
                {
                    "type": "FEED_SUBSCRIPTION",
                    "channel": CANDLE_FEED_CHANNEL,
                    "add": [
                        {
                            "type": "Candle",
                            "symbol": SPY_CANDLE_SYMBOL,
                            "fromTime": from_time,
                        }
                    ],
                }
            )
        )

    async def _recv_until(self, ws: Any, predicate: Any, timeout: float = 15.0) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            payload = await asyncio.wait_for(ws.recv(), timeout=max(deadline - loop.time(), 0.1))
            message = self._parse_json(payload)
            if message.get("type") == "KEEPALIVE":
                continue
            if predicate(message):
                return message
            if message.get("type") == "ERROR":
                raise RuntimeError(message.get("message", "broker_error"))
        raise TimeoutError("dxlink_handshake_timeout")

    async def _receive_loop(self, ws: Any) -> None:
        current: _MinuteBuffer | None = None
        with self._state_lock:
            self._last_candle_period_ms_max = 0
            self._debug_by_period_ms.clear()
        while not self._stop.is_set():
            try:
                payload = await asyncio.wait_for(ws.recv(), timeout=75.0)
            except TimeoutError:
                logger.warning("DXLink candle recv timeout; closing session for reconnect")
                await ws.close()
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("DXLink candle recv ended: %s", exc)
                return
            now = datetime.now(timezone.utc)
            msg = self._parse_json(payload)
            with self._state_lock:
                self._last_message_time = now
            mtype = msg.get("type")
            if mtype == "KEEPALIVE":
                continue
            if mtype == "ERROR":
                logger.warning("DXLink ERROR message: %s", msg)
                await ws.close()
                return
            if mtype != "FEED_DATA":
                continue
            raw = msg.get("data")
            if not isinstance(raw, list) or not raw:
                continue
            event_name: str | None = None
            body: list[Any] | None = None
            if isinstance(raw[0], str):
                event_name = raw[0]
                body = raw[1] if len(raw) > 1 else None
            elif isinstance(raw[0], list) and raw[0]:
                inner = raw[0]
                if isinstance(inner[0], str):
                    event_name = inner[0]
                    body = inner[1] if len(inner) > 1 else None
            if event_name != "Candle" or not isinstance(body, list):
                continue
            for candle in self._iter_compact_candles(body):
                try:
                    ev_flags = int(float(candle.get("eventFlags") or 0))
                except (TypeError, ValueError):
                    ev_flags = 0
                if ev_flags & REMOVE_EVENT:
                    continue
                time_ms = self._to_int(candle.get("time"))
                if time_ms is None:
                    continue
                o, h, low, c = (
                    self._to_float(candle.get("open")),
                    self._to_float(candle.get("high")),
                    self._to_float(candle.get("low")),
                    self._to_float(candle.get("close")),
                )
                if None in (o, h, low, c):
                    continue
                sym = str(candle.get("eventSymbol") or "")
                vol = self._to_float(candle.get("volume"))

                event_time_ms = self._to_int(candle.get("eventTime"))
                period_dt = datetime.fromtimestamp(time_ms / 1000.0, tz=timezone.utc)
                event_dt = (
                    datetime.fromtimestamp(event_time_ms / 1000.0, tz=timezone.utc)
                    if event_time_ms is not None
                    else None
                )
                self._merge_debug_candle(
                    time_ms=time_ms,
                    event_time_ms=event_time_ms,
                    event_flags=ev_flags,
                    event_symbol=sym,
                    period_utc=period_dt,
                    event_time_utc=event_dt,
                    open_=o,
                    high=h,
                    low=low,
                    close_=c,
                    volume=vol,
                )

                with self._state_lock:
                    self._last_candle_period_ms_max = max(self._last_candle_period_ms_max, time_ms)

                if current is None:
                    current = _MinuteBuffer(time_ms, sym, o, h, low, c, vol)
                elif time_ms != current.time_ms:
                    self._persist_completed_minute(current)
                    current = _MinuteBuffer(time_ms, sym, o, h, low, c, vol)
                else:
                    current.open = o if o is not None else current.open
                    current.high = max(current.high, h or current.high)
                    current.low = min(current.low, low or current.low)
                    current.close = c if c is not None else current.close
                    current.volume = vol

                if ev_flags & (SNAPSHOT_END | SNAPSHOT_SNIP):
                    self._trim_debug_stale()

    def _merge_debug_candle(
        self,
        *,
        time_ms: int,
        event_time_ms: int | None,
        event_flags: int,
        event_symbol: str,
        period_utc: datetime,
        event_time_utc: datetime | None,
        open_: float,
        high: float,
        low: float,
        close_: float,
        volume: float | None,
    ) -> None:
        row: dict[str, Any] = {
            "eventSymbol": event_symbol,
            "time_ms": time_ms,
            "period_time_utc": period_utc,
            "event_time_ms": event_time_ms,
            "event_time_utc": event_time_utc,
            "eventFlags": event_flags,
            "open": open_,
            "high": high,
            "low": low,
            "close": close_,
            "volume": volume,
            "parser_mode": CANDLE_PARSER_MODE,
        }
        with self._state_lock:
            self._debug_by_period_ms[time_ms] = row
            if len(self._debug_by_period_ms) > self._debug_max_periods:
                for k in sorted(self._debug_by_period_ms.keys())[: -self._debug_max_periods]:
                    del self._debug_by_period_ms[k]

    def _trim_debug_stale(self) -> None:
        """After snapshot end, drop very old period keys vs newest (replay noise)."""
        with self._state_lock:
            if not self._debug_by_period_ms:
                return
            hi = max(self._debug_by_period_ms.keys())
            cutoff = hi - 7 * 24 * 3600 * 1000
            for k in list(self._debug_by_period_ms.keys()):
                if k < cutoff:
                    del self._debug_by_period_ms[k]

    def _persist_completed_minute(self, buf: _MinuteBuffer) -> None:
        bar_time = datetime.fromtimestamp(buf.time_ms / 1000.0, tz=timezone.utc)
        bar = IntradayBar(
            symbol="SPY",
            timeframe="1m",
            bar_time=bar_time,
            open=buf.open,
            high=buf.high,
            low=buf.low,
            close=buf.close,
            volume=buf.volume,
            source_status=DXLINK_BAR_SOURCE,
        )
        db = SessionLocal()
        try:
            repo = BarsRepository(db)
            repo.upsert_bars([bar])
            bt_aware = bar_time if bar_time.tzinfo else bar_time.replace(tzinfo=timezone.utc)
            bt_aware = bt_aware.astimezone(timezone.utc)
            with self._state_lock:
                prev = self._last_persisted_1m_bar_time
                if prev is None or bt_aware >= prev.astimezone(timezone.utc):
                    self._last_persisted_1m_bar_time = bt_aware
                    self._last_persisted_1m_close = float(buf.close)
            bucket = five_minute_bucket_start_utc(bar_time)
            bucket_end = bucket + timedelta(minutes=5)
            one_m = repo.list_spy_1m_in_half_open_range(bucket_start=bucket, bucket_end=bucket_end)
            subset = five_consecutive_1m_bars_for_bucket(bucket, one_m)
            if subset is not None:
                five_bar = aggregate_1m_to_5m_bar(subset)
                if five_bar is not None:
                    repo.upsert_bars([five_bar])
        finally:
            db.close()

    @staticmethod
    def _iter_compact_candles(body: list[Any]) -> Any:
        if len(body) % CANDLE_FIELD_COUNT != 0:
            logger.warning(
                "DXLink Candle compact length %s not multiple of %s",
                len(body),
                CANDLE_FIELD_COUNT,
            )
            return
        for i in range(0, len(body) - CANDLE_FIELD_COUNT + 1, CANDLE_FIELD_COUNT):
            chunk = body[i : i + CANDLE_FIELD_COUNT]
            yield dict(zip(CANDLE_ACCEPT_EVENT_FIELDS, chunk, strict=True))

    @staticmethod
    def _parse_json(payload: str | bytes) -> dict[str, Any]:
        try:
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")
            decoded = json.loads(payload)
            return decoded if isinstance(decoded, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _to_float(value: Any) -> float | None:
        if value is None or value == "NaN":
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


def get_spy_candle_streamer(settings: Settings) -> DxLinkSpyCandleStreamer:
    global _spy_streamer
    with _spy_streamer_lock:
        if _spy_streamer is None:
            _spy_streamer = DxLinkSpyCandleStreamer(settings=settings)
        return _spy_streamer
