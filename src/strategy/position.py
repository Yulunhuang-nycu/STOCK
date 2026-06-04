"""PositionManager: holds open positions, emits exits on stop-loss / TP / time."""
from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Callable

from src.core.clock import TAIPEI
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
    def __init__(self, stop_loss_pct: float = 1.0, take_profit_pct: float = 1.7, force_exit: str = "13:00"):
        self._stop_loss_pct = stop_loss_pct
        self._take_profit_pct = take_profit_pct
        self._force_exit_time = self._parse_hhmm(force_exit)
        self._positions: dict[str, Position] = {}

    def snapshot(self) -> dict[str, Position]:
        return dict(self._positions)

    def on_entry_signal(self, sig: Signal, tick: Tick) -> None:
        if sig.symbol in self._positions:
            return
        side = None
        if sig.side == "entry_long":
            side = "long"
        elif sig.side == "entry_short":
            side = "short"
        if side is None:
            return
        self._positions[sig.symbol] = Position(
            symbol=sig.symbol, side=side, entry_price=tick.price, quantity=1,
        )
        log.info("OPEN  %s %s @ %.2f", sig.symbol, side, tick.price)

    def on_tick(self, tick: Tick, emit_exit: Callable[[Signal], None], current_time: dt.datetime | None = None) -> None:
        pos = self._positions.get(tick.symbol)
        if pos is None:
            return

        if current_time is not None and current_time.astimezone(TAIPEI).time() >= self._force_exit_time:
            pnl_pct = self._calc_pnl_pct(pos, tick.price)
            log.info("CLOSE %s @ %.2f pnl=%.2f%% reason=force_exit", tick.symbol, tick.price, pnl_pct)
            del self._positions[tick.symbol]
            emit_exit(Signal(
                symbol=tick.symbol,
                side="exit",
                score=1.0,
                reason="force_exit",
                features={"pnl_pct": pnl_pct},
            ))
            return

        pnl_pct = self._calc_pnl_pct(pos, tick.price)
        if pnl_pct <= -self._stop_loss_pct or pnl_pct >= self._take_profit_pct:
            reason = "stop_loss" if pnl_pct <= -self._stop_loss_pct else "take_profit"
            log.info("CLOSE %s @ %.2f pnl=%.2f%% reason=%s", tick.symbol, tick.price, pnl_pct, reason)
            del self._positions[tick.symbol]
            emit_exit(Signal(
                symbol=tick.symbol, side="exit", score=1.0,
                reason=reason, features={"pnl_pct": pnl_pct},
            ))

    @staticmethod
    def _calc_pnl_pct(pos: Position, price: float) -> float:
        if pos.side == "long":
            return 100.0 * (price - pos.entry_price) / pos.entry_price
        return 100.0 * (pos.entry_price - price) / pos.entry_price

    @staticmethod
    def _parse_hhmm(raw: str) -> dt.time:
        return dt.datetime.strptime(raw, "%H:%M").time()
