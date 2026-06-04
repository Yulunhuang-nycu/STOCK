"""TickParquetWriter — persists live ticks to partitioned parquet files.

Layout: {base_dir}/YYYY-MM-DD/{symbol}.parquet  (date in Asia/Taipei)
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from pathlib import Path

import pandas as pd

from src.core.clock import TAIPEI
from src.data.feed_base import Tick

log = logging.getLogger("stock.storage.parquet")


class TickParquetWriter:
    """Buffers ticks in memory and flushes to parquet on a count or time threshold."""

    def __init__(
        self,
        base_dir: str = "data/ticks",
        flush_every: int = 100,
        flush_interval_sec: float = 60.0,
    ) -> None:
        self._base_dir = Path(base_dir)
        self._flush_every = flush_every
        self._flush_interval_sec = flush_interval_sec

        # key: (date_str_taipei, symbol) -> list of dicts
        self._buffers: dict[tuple[str, str], list[dict]] = defaultdict(list)
        # key: (date_str_taipei, symbol) -> last flush time (monotonic clock)
        self._last_flush: dict[tuple[str, str], float] = defaultdict(time.monotonic)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(self, tick: Tick) -> None:
        taipei_dt = tick.ts.astimezone(TAIPEI)
        date_str = taipei_dt.date().isoformat()
        key = (date_str, tick.symbol)

        row = {
            "symbol": tick.symbol,
            "ts_utc": tick.ts.isoformat(),
            "ts_taipei": taipei_dt.isoformat(),
            "price": float(tick.price),
            "volume": int(tick.volume),
            "bid": float(tick.bid),
            "ask": float(tick.ask),
            "size": int(tick.size),
            "cum_volume": int(tick.cum_volume),
            "tick_type": int(tick.tick_type),
            "serial": int(tick.serial),
        }
        self._buffers[key].append(row)

        now = time.monotonic()
        elapsed = now - self._last_flush[key]
        if len(self._buffers[key]) >= self._flush_every or elapsed >= self._flush_interval_sec:
            self._flush(key)

    def flush_all(self) -> None:
        for key in list(self._buffers.keys()):
            if self._buffers[key]:
                self._flush(key)

    def close(self) -> None:
        self.flush_all()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _flush(self, key: tuple[str, str]) -> None:
        date_str, symbol = key
        rows = self._buffers[key]
        if not rows:
            return

        out_path = self._base_dir / date_str / f"{symbol}.parquet"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        new_df = pd.DataFrame(
            rows,
            columns=[
                "symbol",
                "ts_utc",
                "ts_taipei",
                "price",
                "volume",
                "bid",
                "ask",
                "size",
                "cum_volume",
                "tick_type",
                "serial",
            ],
        )

        if out_path.exists():
            try:
                existing_df = pd.read_parquet(out_path)
                combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            except Exception as exc:
                log.warning("TickParquetWriter: could not read existing file %s: %s", out_path, exc)
                combined_df = new_df
        else:
            combined_df = new_df

        combined_df.to_parquet(out_path, index=False, engine="pyarrow")
        log.debug("TickParquetWriter: flushed %d rows → %s", len(rows), out_path)

        self._buffers[key] = []
        self._last_flush[key] = time.monotonic()
