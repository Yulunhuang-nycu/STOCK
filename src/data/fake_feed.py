"""Synthetic feed that emits random-walk ticks. Used only for skeleton testing."""
from __future__ import annotations

import datetime as dt
import logging
import random
import time

from src.core.clock import UTC
from src.data.feed_base import MarketDataFeed, Tick, TickCallback

log = logging.getLogger("stock.data.fake")


class FakeFeed(MarketDataFeed):
    def __init__(self, tick_interval_ms: int = 200, seed: int = 42, max_ticks: int = 200):
        self._interval = tick_interval_ms / 1000.0
        self._rng = random.Random(seed)
        self._symbols: list[str] = []
        self._callback: TickCallback | None = None
        self._stop = False
        self._max_ticks = max_ticks
        self._prices: dict[str, float] = {}
        self._cum_volumes: dict[str, int] = {}
        self._serial = 0

    def subscribe(self, symbols: list[str]) -> None:
        self._symbols = list(symbols)
        for s in symbols:
            self._prices[s] = self._rng.uniform(20.0, 600.0)
            self._cum_volumes[s] = 0

    def on_tick(self, callback: TickCallback) -> None:
        self._callback = callback

    def start(self) -> None:
        if self._callback is None:
            raise RuntimeError("on_tick callback not set")
        if not self._symbols:
            raise RuntimeError("no symbols subscribed")

        log.info("FakeFeed started for symbols=%s", self._symbols)
        emitted = 0
        while not self._stop and emitted < self._max_ticks:
            sym = self._rng.choice(self._symbols)
            self._prices[sym] *= 1 + self._rng.uniform(-0.003, 0.003)
            price = round(self._prices[sym], 2)
            volume = self._rng.randint(1, 50)
            size = volume * 1000
            self._cum_volumes[sym] += volume
            self._serial += 1
            tick = Tick(
                symbol=sym,
                ts=dt.datetime.now(tz=UTC),
                price=price,
                volume=volume,
                bid=round(price * 0.999, 2),
                ask=round(price * 1.001, 2),
                size=size,
                cum_volume=self._cum_volumes[sym],
                tick_type=self._rng.choice([-1, 1]),
                serial=self._serial,
            )
            self._callback(tick)
            emitted += 1
            time.sleep(self._interval)
        log.info("FakeFeed finished | emitted=%d", emitted)

    def stop(self) -> None:
        self._stop = True
