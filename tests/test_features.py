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


def test_momentum_long_rule_below_min_conditions_returns_none():
    rule = MomentumLongRule(min_conditions_met=3)
    # Only 2 conditions met (ma_bullish + kd_golden_cross) -> below threshold.
    sig = rule.generate(
        "2330",
        {
            "vol_ratio_vs5": 1.0,        # < 1.5  -> fail
            "ma_bullish": 1.0,           # pass
            "kd_golden_cross": 1.0,      # pass
            "price_vs_ma20_pct": -5.0,   # <= -2.0 -> fail
            "momentum_3m": 0.0,          # <= 0.2  -> fail
        },
    )
    assert sig is None


def test_momentum_long_rule_emits_when_min_conditions_met():
    rule = MomentumLongRule(min_conditions_met=3)
    # Exactly 3 conditions met -> score = 0.6.
    sig = rule.generate(
        "2330",
        {
            "vol_ratio_vs5": 1.6,        # pass
            "ma_bullish": 1.0,           # pass
            "kd_golden_cross": 1.0,      # pass
            "price_vs_ma20_pct": -5.0,   # fail
            "momentum_3m": 0.0,          # fail
        },
    )
    assert sig is not None
    assert sig.side == "entry_long"
    assert sig.score == 0.6
    assert sig.model_version == "rule-momentum-long-0.1"


def test_momentum_long_rule_all_conditions_score_one():
    rule = MomentumLongRule(min_conditions_met=3)
    sig = rule.generate(
        "2330",
        {
            "vol_ratio_vs5": 2.0,        # pass
            "ma_bullish": 1.0,           # pass
            "kd_golden_cross": 1.0,      # pass
            "price_vs_ma20_pct": 1.0,    # pass
            "momentum_3m": 0.5,          # pass
        },
    )
    assert sig is not None
    assert sig.score == 1.0
