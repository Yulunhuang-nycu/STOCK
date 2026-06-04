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
    kd_k_prev: float = 50.0
    kd_d_prev: float = 50.0
    ema12_prev: float | None = None
    ema26_prev: float | None = None
    macd_signal_prev: float | None = None
    macd_hist_prev: float | None = None


class FeatureBuilder:
    """Skeleton implementation: returns a few placeholder features.

    Real features (VWAP, volume ratio vs N-day avg, order-book imbalance, ...)
    will be added in Phase 2. Note: features must be symbol-agnostic so the
    same model can be applied across the whole universe.
    """

    MIN_TICKS = 30

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

        prices = list(st.prices)
        volumes = list(st.volumes)
        last = float(prices[-1])

        ma5 = self._sma(prices, 5)
        ma20 = self._sma(prices, 20)
        ma60 = self._sma(prices, 60)
        ma_bullish = 1.0 if (ma5 > ma20 and ma20 > ma60) else 0.0
        price_vs_ma20_pct = 0.0 if ma20 == 0 else 100.0 * (last - ma20) / ma20

        k_prev = st.kd_k_prev
        d_prev = st.kd_d_prev
        kd_window = prices[-9:]
        highest = max(kd_window)
        lowest = min(kd_window)
        if highest == lowest:
            rsv = 50.0
        else:
            rsv = 100.0 * (last - lowest) / (highest - lowest)
        kd_k = (2.0 / 3.0) * k_prev + (1.0 / 3.0) * rsv
        kd_d = (2.0 / 3.0) * d_prev + (1.0 / 3.0) * kd_k
        kd_golden_cross = 1.0 if (k_prev <= d_prev and kd_k > kd_d) else 0.0
        kd_dead_cross = 1.0 if (k_prev >= d_prev and kd_k < kd_d) else 0.0
        st.kd_k_prev = kd_k
        st.kd_d_prev = kd_d

        ema12 = self._ema(last, st.ema12_prev, 12)
        ema26 = self._ema(last, st.ema26_prev, 26)
        st.ema12_prev = ema12
        st.ema26_prev = ema26
        macd_dif = ema12 - ema26
        macd_signal = self._ema(macd_dif, st.macd_signal_prev, 9)
        macd_hist = macd_dif - macd_signal
        macd_bullish = (
            1.0
            if (macd_hist > 0 and st.macd_hist_prev is not None and macd_hist > st.macd_hist_prev)
            else 0.0
        )
        st.macd_signal_prev = macd_signal
        st.macd_hist_prev = macd_hist

        vol_ma5 = self._sma(volumes, 5)
        vol_ratio_vs5 = 0.0 if vol_ma5 == 0 else float(tick.volume) / vol_ma5

        mom_1m = self._momentum_pct(prices, 1)
        mom_3m = self._momentum_pct(prices, 3)
        mom_5m = self._momentum_pct(prices, 5)

        if len(st.prices) < self.MIN_TICKS:
            return None

        return_since_open_pct = 0.0 if st.first_price == 0 else 100.0 * (last - st.first_price) / st.first_price
        return {
            "last_price": last,
            "return_since_open_pct": float(return_since_open_pct),
            "sma5": float(self._sma(prices, 5)),
            "vol_sum_recent": float(sum(volumes[-5:])),
            "ma5": float(ma5),
            "ma20": float(ma20),
            "ma60": float(ma60),
            "ma_bullish": float(ma_bullish),
            "price_vs_ma20_pct": float(price_vs_ma20_pct),
            "kd_k": float(kd_k),
            "kd_d": float(kd_d),
            "kd_golden_cross": float(kd_golden_cross),
            "kd_dead_cross": float(kd_dead_cross),
            "vol_ratio_vs5": float(vol_ratio_vs5),
            "vol_ma5": float(vol_ma5),
            "momentum_1m": float(mom_1m),
            "momentum_3m": float(mom_3m),
            "momentum_5m": float(mom_5m),
            "macd_dif": float(macd_dif),
            "macd_signal": float(macd_signal),
            "macd_hist": float(macd_hist),
            "macd_bullish": float(macd_bullish),
        }

    @staticmethod
    def _sma(values: list[float] | list[int], period: int) -> float:
        if not values:
            return 0.0
        window = values[-period:] if len(values) >= period else values
        return float(sum(window)) / float(len(window))

    @staticmethod
    def _momentum_pct(prices: list[float], lookback: int) -> float:
        if len(prices) <= lookback:
            return 0.0
        base = prices[-(lookback + 1)]
        if base == 0:
            return 0.0
        return 100.0 * (prices[-1] - base) / base

    @staticmethod
    def _ema(value: float, prev: float | None, period: int) -> float:
        if prev is None:
            return value
        alpha = 2.0 / (period + 1.0)
        return alpha * value + (1.0 - alpha) * prev
