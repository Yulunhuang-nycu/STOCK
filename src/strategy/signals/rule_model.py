"""Rule-based momentum long entry model."""
from __future__ import annotations

from src.strategy.signals.base import Signal, SignalGenerator


class MomentumLongRule(SignalGenerator):
    model_version = "rule-momentum-long-0.1"

    def __init__(
        self,
        require_ma_bullish: bool = True,
        min_kd_golden_cross: bool = True,
        min_vol_ratio: float = 1.5,
        require_macd_positive: bool = True,
        min_price_vs_ma20_pct: float = -2.0,
    ):
        self._require_ma_bullish = require_ma_bullish
        self._min_kd_golden_cross = min_kd_golden_cross
        self._min_vol_ratio = min_vol_ratio
        self._require_macd_positive = require_macd_positive
        self._min_price_vs_ma20_pct = min_price_vs_ma20_pct

    def generate(self, symbol: str, features: dict) -> Signal | None:
        kd_golden = float(features.get("kd_golden_cross", 0.0))
        ma_bullish = float(features.get("ma_bullish", 0.0))
        vol_ratio = float(features.get("vol_ratio_vs5", 0.0))
        macd_hist = float(features.get("macd_hist", 0.0))
        price_vs_ma20_pct = float(features.get("price_vs_ma20_pct", 0.0))

        if self._min_kd_golden_cross and kd_golden < 1.0:
            return None
        if self._require_ma_bullish and ma_bullish < 1.0:
            return None
        if vol_ratio < self._min_vol_ratio:
            return None
        if self._require_macd_positive and macd_hist <= 0.0:
            return None
        if price_vs_ma20_pct <= self._min_price_vs_ma20_pct:
            return None

        return Signal(
            symbol=symbol,
            side="entry_long",
            score=1.0,
            reason=(
                f"kd_golden={kd_golden:.0f},ma_bullish={ma_bullish:.0f},"
                f"vol_ratio={vol_ratio:.2f},macd_hist={macd_hist:.4f},"
                f"price_vs_ma20_pct={price_vs_ma20_pct:.2f}"
            ),
            features=dict(features),
            model_version=self.model_version,
        )
