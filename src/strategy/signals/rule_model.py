"""Trivial rule-based signal — replace with anything once features are richer."""
from __future__ import annotations

from src.strategy.signals.base import Signal, SignalGenerator


class DummyRuleModel(SignalGenerator):
    model_version = "rule-dummy-0.1"

    def __init__(self, min_return_pct: float = 0.3):
        self._min_return_pct = min_return_pct

    def generate(self, symbol: str, features: dict) -> Signal | None:
        ret = features.get("return_since_open_pct", 0.0)
        if ret >= self._min_return_pct:
            return Signal(
                symbol=symbol,
                side="entry_short",
                score=1.0,
                reason=f"return_since_open_pct={ret:.2f}>={self._min_return_pct}",
                features=dict(features),
                model_version=self.model_version,
            )
        return None
