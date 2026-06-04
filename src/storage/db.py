"""SQLite writer for signals. Schema is the future ML training source — keep stable."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from src.strategy.signals.base import Signal

log = logging.getLogger("stock.storage.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id        TEXT    NOT NULL,
  ts_utc        TEXT    NOT NULL,
  symbol        TEXT    NOT NULL,
  side          TEXT    NOT NULL,
  score         REAL    NOT NULL,
  reason        TEXT,
  features_json TEXT,
  model_version TEXT,
  risk_passed   INTEGER NOT NULL,
  risk_reason   TEXT,
  filled_price  REAL,
  exit_price    REAL,
  pnl           REAL,
  outcome       TEXT
);
CREATE INDEX IF NOT EXISTS idx_signals_run ON signals(run_id);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts ON signals(symbol, ts_utc);
"""


class SignalsDB:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        log.info("SignalsDB ready at %s", path)

    def insert(self, run_id: str, sig: Signal, risk_passed: bool, risk_reason: str) -> None:
        self._conn.execute(
            """INSERT INTO signals
                (run_id, ts_utc, symbol, side, score, reason, features_json,
                 model_version, risk_passed, risk_reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                sig.ts.isoformat(),
                sig.symbol,
                sig.side,
                float(sig.score),
                sig.reason,
                json.dumps(sig.features, default=float),
                sig.model_version,
                1 if risk_passed else 0,
                risk_reason,
            ),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
