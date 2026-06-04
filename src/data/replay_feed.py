"""Replay feed that re-emits ticks from parquet files."""
from __future__ import annotations

import logging
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

from src.data.feed_base import MarketDataFeed, Tick, TickCallback

log = logging.getLogger("stock.data.replay")


class ReplayFeed(MarketDataFeed):
    def __init__(
        self,
        date: str,
        symbols: list[str] | None = None,
        base_dir: str = "data/ticks",
        speed_multiplier: float = 1.0,
    ) -> None:
        self._date = date
        self._symbols = list(symbols) if symbols is not None else []
        self._base_dir = Path(base_dir)
        self._speed_multiplier = speed_multiplier
        self._callback: TickCallback | None = None
        self._stop = False

    def subscribe(self, symbols: list[str]) -> None:
        self._symbols = list(symbols)

    def on_tick(self, callback: TickCallback) -> None:
        self._callback = callback

    def start(self) -> None:
        if self._callback is None:
            raise RuntimeError("on_tick callback not set")
        if self._speed_multiplier < 0:
            raise ValueError("speed_multiplier must be >= 0")

        self._stop = False
        date_dir = self._base_dir / self._date
        symbols = list(self._symbols)
        if not symbols:
            symbols = sorted(p.stem for p in date_dir.glob("*.parquet"))

        dfs: list[pd.DataFrame] = []
        for symbol in symbols:
            path = date_dir / f"{symbol}.parquet"
            if not path.exists():
                msg = f"Replay parquet not found: {path.resolve()}"
                log.error(msg)
                raise FileNotFoundError(msg)
            dfs.append(pd.read_parquet(path))

        if not dfs:
            return
        all_ticks = pd.concat(dfs, ignore_index=True).sort_values("ts_utc")

        prev_ts: datetime | None = None
        for row in all_ticks.itertuples(index=False):
            if self._stop:
                break

            ts = datetime.fromisoformat(row.ts_utc)
            if prev_ts is not None and self._speed_multiplier > 0:
                sleep_sec = max(0.0, (ts - prev_ts).total_seconds() / self._speed_multiplier)
                if sleep_sec > 0:
                    time.sleep(sleep_sec)

            tick = Tick(
                symbol=str(row.symbol),
                ts=ts,
                price=float(row.price),
                volume=int(row.volume),
                bid=float(row.bid),
                ask=float(row.ask),
            )
            self._callback(tick)
            prev_ts = ts

    def stop(self) -> None:
        self._stop = True
