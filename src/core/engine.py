"""The engine wires Data -> Strategy -> Execution. Knows nothing about implementations."""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from src.data.feed_base import MarketDataFeed, Tick
from src.execution.base import Executor
from src.strategy.features import FeatureBuilder
from src.strategy.position import PositionManager
from src.strategy.risk import RiskManager
from src.strategy.signals.base import SignalGenerator
from src.storage.db import SignalsDB

log = logging.getLogger("stock.engine")


@dataclass
class Engine:
    feed: MarketDataFeed
    features: FeatureBuilder
    signal_gen: SignalGenerator
    position_mgr: PositionManager
    risk_mgr: RiskManager
    executor: Executor
    signals_db: SignalsDB
    run_id: str = ""

    def __post_init__(self) -> None:
        if not self.run_id:
            self.run_id = uuid.uuid4().hex[:12]

    def _on_tick(self, tick: Tick) -> None:
        feats = self.features.update(tick)
        if feats is None:
            self.position_mgr.on_tick(tick, self._submit_exit)
            return

        sig = self.signal_gen.generate(tick.symbol, feats)
        self.position_mgr.on_tick(tick, self._submit_exit)

        if sig is None:
            return

        ok, reason = self.risk_mgr.check(sig, self.position_mgr.snapshot())
        self.signals_db.insert(self.run_id, sig, risk_passed=ok, risk_reason=reason)
        if not ok:
            log.info("Signal REJECTED by risk: %s reason=%s", sig, reason)
            return

        self.position_mgr.on_entry_signal(sig, tick)
        self.executor.submit(sig)

    def _submit_exit(self, exit_signal) -> None:
        self.signals_db.insert(self.run_id, exit_signal, risk_passed=True, risk_reason="exit")
        self.executor.submit(exit_signal)

    def run(self) -> None:
        log.info("Engine starting | run_id=%s", self.run_id)
        self.feed.on_tick(self._on_tick)
        self.feed.start()
