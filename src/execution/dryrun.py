"""DryRunExecutor: just logs the signal. Phase 0 default."""
from __future__ import annotations

import logging

from src.execution.base import Executor
from src.strategy.signals.base import Signal

log = logging.getLogger("stock.exec.dryrun")


class DryRunExecutor(Executor):
    def submit(self, signal: Signal) -> None:
        log.info(
            "DRYRUN | %s %s score=%.2f reason=%s model=%s",
            signal.side, signal.symbol, signal.score, signal.reason, signal.model_version,
        )
