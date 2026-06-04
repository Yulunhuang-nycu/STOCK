"""PositionManager: holds open positions, emits exits on stop-loss / TP / time."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from src.data.feed_base import Tick
from src.strategy.signals.base import Signal

log = logging.getLogger("stock.position")


@dataclass
class Position:
    symbol: str
    side: str
    entry_price: float
    quantity: int


class PositionManager:
    def __init__(self, stop_loss_pct: float = 1.0, take_profit_pct: float = 1.7):
        self._stop_loss_pct = stop_loss_pct
        self._take_profit_pct = take_profit_pct
        self._positions: dict[str, Position] = {}

    def snapshot(self) -> dict[str, Position]:
        return dict(self._positions)

    def on_entry_signal(self, sig: Signal, tick: Tick) -> None:
        if sig.symbol in self._positions:
            return
        self._positions[sig.symbol] = Position(
            symbol=sig.symbol, side="short", entry_price=tick.price, quantity=1,
        )
        log.info("OPEN  %s short @ %.2f", sig.symbol, tick.price)

    def on_tick(self, tick: Tick, emit_exit: Callable[[Signal], None]) -> None:
        pos = self._positions.get(tick.symbol)
        if pos is None:
            return
        # sell-first day-trade: profit when price falls
        pnl_pct = 100.0 * (pos.entry_price - tick.price) / pos.entry_price
        if pnl_pct <= -self._stop_loss_pct or pnl_pct >= self._take_profit_pct:
            reason = "stop_loss" if pnl_pct <= -self._stop_loss_pct else "take_profit"
            log.info("CLOSE %s @ %.2f pnl=%.2f%% reason=%s", tick.symbol, tick.price, pnl_pct, reason)
            del self._positions[tick.symbol]
            emit_exit(Signal(
                symbol=tick.symbol, side="exit", score=1.0,
                reason=reason, features={"pnl_pct": pnl_pct},
            ))
