"""FeatureBuilder. Pure: no I/O, no network. Easy to call from both live & backtest."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque

from src.data.feed_base import Tick


@dataclass
class _SymbolState:
    prices: Deque[float] = field(default_factory=lambda: deque(maxlen=300))
    volumes: Deque[int] = field(default_factory=lambda: deque(maxlen=300))
    first_price: float | None = None


class FeatureBuilder:
    """Skeleton implementation: returns a few placeholder features.

    Real features (VWAP, volume ratio vs N-day avg, order-book imbalance, ...)
    will be added in Phase 2. Note: features must be symbol-agnostic so the
    same model can be applied across the whole universe.
    """

    MIN_TICKS = 5

    def __init__(self, vwap_window_min: int = 5, momentum_windows_min: list[int] | None = None):
        self._vwap_window_min = vwap_window_min
        self._momentum_windows = momentum_windows_min or [1, 3, 5]
        self._state: dict[str, _SymbolState] = defaultdict(_SymbolState)

    def update(self, tick: Tick) -> dict[str, float] | None:
        st = self._state[tick.symbol]
        if st.first_price is None:
            st.first_price = tick.price
        st.prices.append(tick.price)
        st.volumes.append(tick.volume)

        if len(st.prices) < self.MIN_TICKS:
            return None

        last = st.prices[-1]
        return {
            "last_price": last,
            "return_since_open_pct": 100.0 * (last - st.first_price) / st.first_price,
            "sma5": sum(list(st.prices)[-5:]) / 5,
            "vol_sum_recent": float(sum(list(st.volumes)[-5:])),
        }
