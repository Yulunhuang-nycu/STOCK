"""RiskManager: every signal goes through here before reaching the Executor."""
from __future__ import annotations

import logging

from src.strategy.signals.base import Signal

log = logging.getLogger("stock.risk")


class RiskManager:
    def __init__(
        self,
        total_capital: float = 500000,
        max_lot_per_symbol: int = 2,
        max_open_positions: int = 5,
    ):
        self._total_capital = total_capital
        self._max_lot_per_symbol = max_lot_per_symbol
        self._max_open_positions = max_open_positions

    def check(self, sig: Signal, positions: dict) -> tuple[bool, str]:
        if sig.side == "exit":
            return True, ""
        if len(positions) >= self._max_open_positions:
            return False, f"max_open_positions={self._max_open_positions}"
        if sig.symbol in positions:
            return False, "already_holding"
        return True, ""
