from datetime import datetime, timedelta, timezone

from src.core.clock import TAIPEI
from src.data.feed_base import Tick
from src.strategy.position import PositionManager
from src.strategy.signals.base import Signal


def _tick(price: float, minutes: int = 0) -> Tick:
    ts = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return Tick(symbol="2330", ts=ts, price=price, volume=1)


def test_long_position_stop_loss_emits_exit():
    pm = PositionManager(stop_loss_pct=1.0, take_profit_pct=2.0)
    pm.on_entry_signal(Signal(symbol="2330", side="entry_long", score=1.0, reason="x"), _tick(100.0))
    exits = []
    pm.on_tick(_tick(98.9, minutes=1), exits.append)
    assert len(exits) == 1
    assert exits[0].reason == "stop_loss"


def test_long_position_take_profit_emits_exit():
    pm = PositionManager(stop_loss_pct=1.0, take_profit_pct=2.0)
    pm.on_entry_signal(Signal(symbol="2330", side="entry_long", score=1.0, reason="x"), _tick(100.0))
    exits = []
    pm.on_tick(_tick(102.1, minutes=1), exits.append)
    assert len(exits) == 1
    assert exits[0].reason == "take_profit"


def test_force_exit_emits_exit_and_clears_position():
    pm = PositionManager(stop_loss_pct=1.0, take_profit_pct=2.0, force_exit="13:00")
    pm.on_entry_signal(Signal(symbol="2330", side="entry_long", score=1.0, reason="x"), _tick(100.0))
    exits = []
    current_time = datetime(2026, 1, 1, 13, 0, tzinfo=TAIPEI).astimezone(timezone.utc)
    pm.on_tick(_tick(100.0, minutes=1), exits.append, current_time=current_time)
    assert len(exits) == 1
    assert exits[0].reason == "force_exit"
    assert "2330" not in pm.snapshot()
