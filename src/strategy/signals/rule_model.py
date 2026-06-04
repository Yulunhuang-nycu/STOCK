"""Rule-based momentum long entry model.

NOTE: This rule exists to *generate training data*, not to be the final
trading strategy. The conditions are intentionally loose so that we collect a
rich, varied set of labelled signals in ``signals.sqlite``.

A signal is emitted when at least ``min_conditions_met`` of the following five
conditions hold:

    1. vol_ratio_vs5      >= vol_ratio_threshold      (default 1.5)
    2. ma_bullish         == 1
    3. kd_golden_cross    == 1
    4. price_vs_ma20_pct  >  price_vs_ma20_min        (default -2.0)
    5. momentum_3m        >  momentum_3m_threshold    (default 0.2)

The ``score`` is the *fraction* of conditions met, i.e. ``met / 5``:
    - 3 conditions met -> score = 0.6
    - 5 conditions met -> score = 1.0

This lets the ``score`` column in ``signals.sqlite`` act as a proxy for how
strongly each signal fired, which is useful later when training the model.
"""
from __future__ import annotations

from src.strategy.signals.base import Signal, SignalGenerator

_TOTAL_CONDITIONS = 5


class MomentumLongRule(SignalGenerator):
    model_version = "rule-momentum-long-0.1"

    def __init__(
        self,
        min_conditions_met: int = 3,
        vol_ratio_threshold: float = 1.5,
        momentum_3m_threshold: float = 0.2,
        price_vs_ma20_min: float = -2.0,
    ):
        self._min_conditions_met = int(min_conditions_met)
        self._vol_ratio_threshold = float(vol_ratio_threshold)
        self._momentum_3m_threshold = float(momentum_3m_threshold)
        self._price_vs_ma20_min = float(price_vs_ma20_min)

    def generate(self, symbol: str, features: dict) -> Signal | None:
        vol_ratio = float(features.get("vol_ratio_vs5", 0.0))
        ma_bullish = float(features.get("ma_bullish", 0.0))
        kd_golden = float(features.get("kd_golden_cross", 0.0))
        price_vs_ma20_pct = float(features.get("price_vs_ma20_pct", 0.0))
        momentum_3m = float(features.get("momentum_3m", 0.0))

        conditions = {
            "vol_ratio": vol_ratio >= self._vol_ratio_threshold,
            "ma_bullish": ma_bullish >= 1.0,
            "kd_golden_cross": kd_golden >= 1.0,
            "price_vs_ma20": price_vs_ma20_pct > self._price_vs_ma20_min,
            "momentum_3m": momentum_3m > self._momentum_3m_threshold,
        }
        met = sum(1 for ok in conditions.values() if ok)
        score = met / float(_TOTAL_CONDITIONS)

        if met < self._min_conditions_met:
            return None

        passed = [name for name, ok in conditions.items() if ok]
        reason = (
            f"met={met}/{_TOTAL_CONDITIONS} [{','.join(passed)}] | "
            f"vol_ratio={vol_ratio:.2f},ma_bullish={ma_bullish:.0f},"
            f"kd_golden={kd_golden:.0f},price_vs_ma20_pct={price_vs_ma20_pct:.2f},"
            f"momentum_3m={momentum_3m:.2f}"
        )

        return Signal(
            symbol=symbol,
            side="entry_long",
            score=score,
            reason=reason,
            features=dict(features),
            model_version=self.model_version,
        )
