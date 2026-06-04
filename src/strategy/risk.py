"""RiskManager: every signal goes through here before reaching the Executor."""
from __future__ import annotations

import datetime as dt
import logging

from src.core.clock import TAIPEI
from src.strategy.signals.base import Signal

log = logging.getLogger("stock.risk")


class RiskManager:
    def __init__(
        self,
        total_capital: float = 500000,
        max_lot_per_symbol: int = 2,
        max_open_positions: int = 5,
        entry_cutoff: str = "09:45",
        force_exit: str = "13:00",
        timezone: str = "Asia/Taipei",
    ):
        self._total_capital = total_capital
        self._max_lot_per_symbol = max_lot_per_symbol
        self._max_open_positions = max_open_positions
        self._entry_cutoff = self._parse_hhmm(entry_cutoff)
        self._force_exit = self._parse_hhmm(force_exit)
        self._timezone = timezone

    def check(self, sig: Signal, positions: dict, current_time: dt.datetime | None = None) -> tuple[bool, str]:
        if sig.side == "exit":
            return True, ""
        if sig.side.startswith("entry") and current_time is not None:
            local_time = current_time.astimezone(TAIPEI).time()
            if local_time >= self._entry_cutoff:
                return False, "after_entry_cutoff"
        if len(positions) >= self._max_open_positions:
            return False, f"max_open_positions={self._max_open_positions}"
        if sig.symbol in positions:
            return False, "already_holding"
        return True, ""

    @staticmethod
    def _parse_hhmm(raw: str) -> dt.time:
        return dt.datetime.strptime(raw, "%H:%M").time()
