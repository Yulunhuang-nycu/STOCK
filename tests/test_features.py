from datetime import datetime, timedelta, timezone

from src.data.feed_base import Tick
from src.strategy.features import FeatureBuilder
from src.strategy.signals.rule_model import MomentumLongRule


def _tick(price: float, symbol: str = "2330") -> Tick:
    return Tick(symbol=symbol, ts=datetime.now(tz=timezone.utc), price=price, volume=1)


def test_features_need_warmup():
    fb = FeatureBuilder()
    for p in range(100, 100 + FeatureBuilder.MIN_TICKS - 1):
        assert fb.update(_tick(p)) is None
    feats = fb.update(_tick(100 + FeatureBuilder.MIN_TICKS - 1))
    assert feats is not None
    assert feats["last_price"] == float(100 + FeatureBuilder.MIN_TICKS - 1)
    assert feats["return_since_open_pct"] > 0


def test_kd_golden_cross_flags_only_on_cross_tick():
    fb = FeatureBuilder()
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    prices = [100 - i * 0.3 for i in range(30)] + [91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102]
    golden_hits = []
    feature_count = 0

    for i, p in enumerate(prices):
        feats = fb.update(Tick(symbol="2330", ts=start + timedelta(minutes=i), price=float(p), volume=10))
        if feats is None:
            continue
        feature_count += 1
        if feats["kd_golden_cross"] == 1.0:
            golden_hits.append(feature_count)
        else:
            assert feats["kd_golden_cross"] == 0.0

    assert golden_hits == [3]


def test_ma_bullish_on_monotonic_rise():
    fb = FeatureBuilder()
    feats = None
    for p in range(1, 70):
        feats = fb.update(_tick(float(p)))
    assert feats is not None
    assert feats["ma_bullish"] == 1.0


def test_all_feature_values_are_float():
    fb = FeatureBuilder()
    feats = None
    for p in range(100, 100 + FeatureBuilder.MIN_TICKS):
        feats = fb.update(_tick(float(p)))
    assert feats is not None
    assert all(isinstance(v, float) for v in feats.values())


def test_momentum_long_rule_requires_all_enabled_conditions():
    rule = MomentumLongRule(min_vol_ratio=1.5, min_price_vs_ma20_pct=-2.0)
    assert rule.generate("2330", {"kd_golden_cross": 1.0, "ma_bullish": 1.0, "vol_ratio_vs5": 1.2, "macd_hist": 0.1, "price_vs_ma20_pct": 0.0}) is None
    sig = rule.generate("2330", {"kd_golden_cross": 1.0, "ma_bullish": 1.0, "vol_ratio_vs5": 1.6, "macd_hist": 0.1, "price_vs_ma20_pct": 0.0})
    assert sig is not None
    assert sig.side == "entry_long"
