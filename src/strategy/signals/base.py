"""Signal abstraction. Same interface for rule-based and ML-based generators."""
from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from src.core.clock import UTC


@dataclass(frozen=True)
class Signal:
    symbol: str
    side: str                    # "entry_long" | "entry_short" | "exit"
    score: float
    reason: str
    features: dict = field(default_factory=dict)
    ts: dt.datetime = field(default_factory=lambda: dt.datetime.now(tz=UTC))
    model_version: str = "none"


class SignalGenerator(ABC):
    model_version: str = "none"

    @abstractmethod
    def generate(self, symbol: str, features: dict) -> Signal | None: ...
