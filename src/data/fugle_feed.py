"""Fugle live market data feed implementation."""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime

from fugle_marketdata import WebSocketClient

from src.core.clock import UTC
from src.data.feed_base import MarketDataFeed, Tick, TickCallback

log = logging.getLogger("stock.data.fugle")

FUGLE_TICK_INNER = 1  # 內盤(賣方主動)
FUGLE_TICK_OUTER = 2  # 外盤(買方主動)
TICK_TYPE_SELL = -1
TICK_TYPE_BUY = 1
TICK_TYPE_UNKNOWN = 0


class FugleFeed(MarketDataFeed):
    def __init__(self, api_key: str, reconnect_delay_sec: float = 5.0) -> None:
        self._api_key = api_key
        self._reconnect_delay_sec = reconnect_delay_sec
        self._symbols: list[str] = []
        self._callback: TickCallback | None = None
        self._client: WebSocketClient | None = None
        self._stock = None
        self._stop_event = threading.Event()
        self._reconnect_timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self._prev_cum_vol: dict[str, int] = {}  # per-symbol last cum_volume for diff

    def subscribe(self, symbols: list[str]) -> None:
        self._symbols = list(symbols)

    def on_tick(self, callback: TickCallback) -> None:
        self._callback = callback

    def start(self) -> None:
        if self._callback is None:
            raise RuntimeError("on_tick callback not set")
        if not self._symbols:
            raise RuntimeError("no symbols subscribed")

        self._stop_event.clear()
        self._connect_and_subscribe()
        self._stop_event.wait()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            if self._reconnect_timer is not None:
                self._reconnect_timer.cancel()
                self._reconnect_timer = None
            stock = self._stock
        if stock is not None:
            try:
                stock.disconnect()
            except Exception as exc:
                log.warning("Fugle disconnect failed: %s", exc)

    def _connect_and_subscribe(self) -> None:
        if self._stop_event.is_set():
            return
        try:
            client = WebSocketClient(api_key=self._api_key)
            stock = client.stock
            stock.on("connect", self._handle_connect)
            stock.on("message", self._handle_message)
            stock.on("disconnect", self._handle_disconnect)
            stock.on("error", self._handle_error)
            stock.connect()
            for sym in self._symbols:
                stock.subscribe({"channel": "trades", "symbol": sym})
            with self._lock:
                self._client = client
                self._stock = stock
        except Exception as exc:
            log.warning("Fugle connect failed: %s", exc)
            self._schedule_reconnect()

    def _schedule_reconnect(self) -> None:
        if self._stop_event.is_set():
            return
        with self._lock:
            if self._reconnect_timer is not None:
                self._reconnect_timer.cancel()
            self._reconnect_timer = threading.Timer(self._reconnect_delay_sec, self._connect_and_subscribe)
            self._reconnect_timer.daemon = True
            self._reconnect_timer.start()

    def _handle_connect(self) -> None:
        log.info("Fugle websocket connected")

    def _handle_disconnect(self, code: int | None = None, message: str | None = None) -> None:
        log.warning("Fugle websocket disconnected code=%s message=%s", code, message)
        if not self._stop_event.is_set():
            self._schedule_reconnect()

    def _handle_error(self, error: object) -> None:
        log.warning("Fugle websocket error: %s", error)

    def _handle_message(self, message: dict | str) -> None:
        if self._callback is None:
            return
        try:
            payload = json.loads(message) if isinstance(message, str) else message
            if not isinstance(payload, dict):
                log.warning("Fugle message is not dict: %r", payload)
                return
            event = payload.get("event")
            channel = payload.get("channel")
            if event != "data" or channel != "trades":
                log.info("Fugle skip event=%s channel=%s", event, channel)
                return

            data = payload["data"]
            ts = datetime.fromtimestamp(data["time"] / 1_000_000, tz=UTC)
            tick_raw = data.get("tick")
            if tick_raw == FUGLE_TICK_INNER:
                tick_type = TICK_TYPE_SELL
            elif tick_raw == FUGLE_TICK_OUTER:
                tick_type = TICK_TYPE_BUY
            else:
                tick_type = TICK_TYPE_UNKNOWN

            symbol = str(data["symbol"])
            cum_vol = int(data.get("volume", 0) or 0)
            prev_cum = self._prev_cum_vol.get(symbol, 0)
            if cum_vol > 0:
                inc_vol = max(0, cum_vol - prev_cum)
                self._prev_cum_vol[symbol] = cum_vol
            else:
                inc_vol = 0  # quote-only tick: no trade volume, don't reset tracker

            tick = Tick(
                symbol=symbol,
                ts=ts,
                price=float(data["price"]),
                volume=inc_vol,
                bid=float(data.get("bid", 0.0) or 0.0),
                ask=float(data.get("ask", 0.0) or 0.0),
                size=int(data.get("size", 0) or 0),
                cum_volume=cum_vol,
                tick_type=tick_type,
                serial=int(data.get("serial", 0) or 0),
            )
            self._callback(tick)
        except Exception as exc:
            log.warning("Fugle bad message skipped: %s", exc)
