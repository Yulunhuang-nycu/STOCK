"""Multi-key Fugle live feed with queue fan-in for single-threaded consumers."""
from __future__ import annotations

import logging
import math
import queue
import threading

from src.data.feed_base import MarketDataFeed, Tick, TickCallback
from src.data.fugle_feed import FugleFeed

log = logging.getLogger("stock.data.multi_fugle")


class MultiFugleFeed(MarketDataFeed):
    def __init__(
        self,
        api_keys: list[str],
        symbols_per_key: int = 5,
        reconnect_delay_sec: float = 5.0,
    ) -> None:
        if symbols_per_key <= 0:
            raise ValueError("symbols_per_key must be > 0")
        self._api_keys = list(api_keys)
        self._symbols_per_key = symbols_per_key
        self._reconnect_delay_sec = reconnect_delay_sec
        self._callback: TickCallback | None = None
        self._key_symbol_groups: list[tuple[str, list[str]]] = []

        self._queue: queue.Queue[Tick | object] = queue.Queue()
        self._sentinel = object()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._feeds: list[FugleFeed] = []
        self._threads: list[threading.Thread] = []

    def subscribe(self, symbols: list[str]) -> None:
        all_symbols = list(symbols)
        capacity = len(self._api_keys) * self._symbols_per_key
        if len(all_symbols) > capacity:
            required_keys = math.ceil(len(all_symbols) / self._symbols_per_key)
            raise ValueError(
                f"需要更多 key：需要 {required_keys} 把 key 才能訂閱 {len(all_symbols)} 檔,目前只有 {len(self._api_keys)} 把"
            )

        groups: list[tuple[str, list[str]]] = []
        for i in range(0, len(all_symbols), self._symbols_per_key):
            chunk = all_symbols[i:i + self._symbols_per_key]
            if chunk:
                key = self._api_keys[i // self._symbols_per_key]
                groups.append((key, chunk))
        self._key_symbol_groups = groups

    def on_tick(self, callback: TickCallback) -> None:
        self._callback = callback

    def start(self) -> None:
        if self._callback is None:
            raise RuntimeError("on_tick callback not set")
        if not self._key_symbol_groups:
            raise RuntimeError("no symbols subscribed")

        self._stop_event.clear()
        self._queue = queue.Queue()

        feeds: list[FugleFeed] = []
        threads: list[threading.Thread] = []
        for idx, (api_key, symbols) in enumerate(self._key_symbol_groups):
            shard_label = f"key#{idx + 1}({self._mask_key(api_key)})"
            log.info("MultiFugleFeed start shard %s symbols=%s", shard_label, symbols)
            feed = FugleFeed(api_key=api_key, reconnect_delay_sec=self._reconnect_delay_sec)
            feed.subscribe(symbols)
            feed.on_tick(self._queue.put)
            thread = threading.Thread(
                target=self._run_shard,
                args=(feed, shard_label),
                daemon=True,
                name=f"multi-fugle-{idx + 1}",
            )
            feeds.append(feed)
            threads.append(thread)

        with self._lock:
            self._feeds = feeds
            self._threads = threads

        for thread in threads:
            thread.start()

        try:
            while True:
                item = self._queue.get()
                if item is self._sentinel:
                    break
                self._callback(item)
        finally:
            self.stop()

    def stop(self) -> None:
        self._stop_event.set()
        self._queue.put(self._sentinel)

        with self._lock:
            feeds = list(self._feeds)
            self._feeds = []
            self._threads = []

        for feed in feeds:
            try:
                feed.stop()
            except Exception as exc:
                log.warning("MultiFugleFeed shard stop failed: %s", exc)

    def _run_shard(self, feed: FugleFeed, shard_label: str) -> None:
        try:
            feed.start()
        except Exception as exc:
            log.warning("MultiFugleFeed shard %s failed: %s", shard_label, exc)
            if not self._stop_event.is_set():
                self.stop()

    @staticmethod
    def _mask_key(api_key: str) -> str:
        if not api_key:
            return "****"
        return f"{api_key[:4]}…"
