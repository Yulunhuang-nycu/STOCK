from src.strategy.risk import RiskManager
from src.strategy.signals.base import Signal


def test_risk_rejects_when_already_holding():
    rm = RiskManager(max_open_positions=5)
    sig = Signal(symbol="2330", side="entry_short", score=1.0, reason="x")
    ok, reason = rm.check(sig, positions={"2330": object()})
    assert not ok and reason == "already_holding"


def test_risk_passes_when_empty():
    rm = RiskManager(max_open_positions=5)
    sig = Signal(symbol="2330", side="entry_short", score=1.0, reason="x")
    ok, _ = rm.check(sig, positions={})
    assert ok


def test_exit_signal_always_passes():
    rm = RiskManager(max_open_positions=1)
    sig = Signal(symbol="2330", side="exit", score=1.0, reason="sl")
    ok, _ = rm.check(sig, positions={"2330": object(), "00887": object()})
    assert ok
