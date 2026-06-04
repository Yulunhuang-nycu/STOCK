"""Abstract market data feed. All feeds produce Tick events with UTC timestamps."""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Tick:
    symbol: str
    ts: dt.datetime          # MUST be timezone-aware UTC
    price: float
    volume: int
    bid: float = 0.0
    ask: float = 0.0


TickCallback = Callable[[Tick], None]


class MarketDataFeed(ABC):
    @abstractmethod
    def subscribe(self, symbols: list[str]) -> None: ...

    @abstractmethod
    def on_tick(self, callback: TickCallback) -> None: ...

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...
