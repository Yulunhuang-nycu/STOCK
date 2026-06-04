from datetime import datetime, timezone

from src.data.feed_base import Tick
from src.strategy.features import FeatureBuilder


def _tick(price: float, symbol: str = "2330") -> Tick:
    return Tick(symbol=symbol, ts=datetime.now(tz=timezone.utc), price=price, volume=1)


def test_features_need_warmup():
    fb = FeatureBuilder()
    for p in [100, 101, 102, 103]:
        assert fb.update(_tick(p)) is None
    feats = fb.update(_tick(104))
    assert feats is not None
    assert feats["last_price"] == 104
    assert feats["return_since_open_pct"] > 0


def test_dummy_rule_fires_on_positive_return():
    from src.strategy.signals.rule_model import DummyRuleModel

    rule = DummyRuleModel(min_return_pct=0.5)
    assert rule.generate("2330", {"return_since_open_pct": 0.2}) is None
    sig = rule.generate("2330", {"return_since_open_pct": 1.0})
    assert sig is not None and sig.symbol == "2330"
