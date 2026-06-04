from datetime import datetime, timezone

from src.core.clock import TAIPEI
from src.strategy.risk import RiskManager
from src.strategy.signals.base import Signal


def test_risk_rejects_when_already_holding():
    rm = RiskManager(max_open_positions=5)
    sig = Signal(symbol="2330", side="entry_long", score=1.0, reason="x")
    ok, reason = rm.check(sig, positions={"2330": object()})
    assert not ok and reason == "already_holding"


def test_risk_passes_when_before_cutoff():
    rm = RiskManager(max_open_positions=5)
    sig = Signal(symbol="2330", side="entry_long", score=1.0, reason="x")
    current_time = datetime(2026, 1, 1, 9, 30, tzinfo=TAIPEI).astimezone(timezone.utc)
    ok, _ = rm.check(sig, positions={}, current_time=current_time)
    assert ok


def test_exit_signal_always_passes():
    rm = RiskManager(max_open_positions=1)
    sig = Signal(symbol="2330", side="exit", score=1.0, reason="sl")
    current_time = datetime(2026, 1, 1, 10, 0, tzinfo=TAIPEI).astimezone(timezone.utc)
    ok, _ = rm.check(sig, positions={"2330": object(), "00887": object()}, current_time=current_time)
    assert ok


def test_risk_rejects_after_entry_cutoff():
    rm = RiskManager(entry_cutoff="09:45")
    sig = Signal(symbol="2330", side="entry_short", score=1.0, reason="x")
    current_time = datetime(2026, 1, 1, 10, 0, tzinfo=TAIPEI).astimezone(timezone.utc)
    ok, reason = rm.check(sig, positions={}, current_time=current_time)
    assert not ok
    assert reason == "after_entry_cutoff"


def test_risk_rejects_when_max_open_positions_reached():
    rm = RiskManager(max_open_positions=1)
    sig = Signal(symbol="2330", side="entry_long", score=1.0, reason="x")
    ok, reason = rm.check(sig, positions={"0050": object()})
    assert not ok
    assert reason == "max_open_positions=1"
