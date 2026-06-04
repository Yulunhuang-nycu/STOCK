"""Phase 1 integration tests.

No real Fugle API is needed — all tests use FakeFeed / TickParquetWriter / ReplayFeed.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.core.clock import UTC
from src.data.fake_feed import FakeFeed
from src.data.feed_base import Tick
from src.data.replay_feed import ReplayFeed
from src.storage.parquet_writer import TickParquetWriter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_fake_feed_to_writer(
    tmp_dir: Path,
    symbols: list[str] | None = None,
    max_ticks: int = 20,
) -> tuple[list[Tick], TickParquetWriter]:
    """Run a FakeFeed into a TickParquetWriter; return (emitted_ticks, writer)."""
    symbols = symbols or ["2330"]
    feed = FakeFeed(tick_interval_ms=0, seed=42, max_ticks=max_ticks)
    feed.subscribe(symbols)

    writer = TickParquetWriter(base_dir=str(tmp_dir), flush_every=max_ticks + 1)
    emitted: list[Tick] = []

    def callback(tick: Tick) -> None:
        emitted.append(tick)
        writer.write(tick)

    feed.on_tick(callback)
    feed.start()
    writer.close()
    return emitted, writer


# ---------------------------------------------------------------------------
# Test 1: FakeFeed → TickParquetWriter
# ---------------------------------------------------------------------------

def test_fake_feed_to_parquet(tmp_path: Path) -> None:
    ticks_dir = tmp_path / "ticks"
    emitted, _ = _run_fake_feed_to_writer(ticks_dir, symbols=["2330"], max_ticks=20)

    assert emitted, "FakeFeed should emit at least one tick"

    # Collect all parquet files written
    parquet_files = list(ticks_dir.glob("**/*.parquet"))
    assert parquet_files, "TickParquetWriter should have created at least one parquet file"

    # Read all rows and verify count matches emitted
    all_dfs = [pd.read_parquet(p) for p in parquet_files]
    total_rows = sum(len(df) for df in all_dfs)
    assert total_rows == len(emitted), (
        f"Parquet row count {total_rows} != emitted tick count {len(emitted)}"
    )


# ---------------------------------------------------------------------------
# Test 2: ReplayFeed reproduces ticks
# ---------------------------------------------------------------------------

def test_replay_feed_reproduces_ticks(tmp_path: Path) -> None:
    ticks_dir = tmp_path / "ticks"
    symbols = ["2330", "2395"]
    emitted, _ = _run_fake_feed_to_writer(ticks_dir, symbols=symbols, max_ticks=30)

    assert emitted, "FakeFeed should emit ticks"

    # Determine the date(s) written (Asia/Taipei) from the directory structure
    date_dirs = sorted([d.name for d in ticks_dir.iterdir() if d.is_dir()])
    assert date_dirs, "TickParquetWriter should have created at least one date directory"

    # Replay all dates and collect replayed ticks
    replayed: list[Tick] = []
    for date_str in date_dirs:
        replay = ReplayFeed(
            date=date_str,
            symbols=symbols,
            base_dir=str(ticks_dir),
            speed_multiplier=0.0,
        )
        # Only subscribe to symbols that actually have a file for this date
        available = [
            p.stem
            for p in (ticks_dir / date_str).glob("*.parquet")
            if p.stem in symbols
        ]
        if not available:
            continue
        replay.subscribe(available)
        replay.on_tick(replayed.append)
        replay.start()

    assert len(replayed) == len(emitted), (
        f"Replayed {len(replayed)} ticks, expected {len(emitted)}"
    )

    # Verify per-symbol price sequences match
    for sym in symbols:
        original_prices = [t.price for t in emitted if t.symbol == sym]
        replayed_prices = [t.price for t in replayed if t.symbol == sym]
        assert original_prices == replayed_prices, (
            f"Price sequence mismatch for symbol {sym}"
        )


# ---------------------------------------------------------------------------
# Test 3: Engine with ReplayFeed runs without exceptions
# ---------------------------------------------------------------------------

def test_engine_with_replay_feed(tmp_path: Path) -> None:
    from src.core.engine import Engine
    from src.execution.dryrun import DryRunExecutor
    from src.storage.db import SignalsDB
    from src.strategy.features import FeatureBuilder
    from src.strategy.position import PositionManager
    from src.strategy.risk import RiskManager
    from src.strategy.signals.rule_model import MomentumLongRule

    # 1. Produce parquet data with enough ticks for features to warm up
    ticks_dir = tmp_path / "ticks"
    symbols = ["2330"]
    needed_ticks = FeatureBuilder.MIN_TICKS + 10  # enough for feature warmup
    emitted, _ = _run_fake_feed_to_writer(
        ticks_dir, symbols=symbols, max_ticks=needed_ticks
    )
    assert emitted

    # Determine date(s) written
    date_dirs = sorted([d.name for d in ticks_dir.iterdir() if d.is_dir()])
    assert date_dirs

    # Use the first available date that has a parquet for our symbol
    date_str = None
    for d in date_dirs:
        if (ticks_dir / d / "2330.parquet").exists():
            date_str = d
            break
    assert date_str is not None, "No parquet file written for 2330"

    # 2. Build the replay feed
    replay_feed = ReplayFeed(
        date=date_str,
        symbols=symbols,
        base_dir=str(ticks_dir),
        speed_multiplier=0.0,
    )

    # 3. Build engine components
    db_path = str(tmp_path / "signals.sqlite")
    engine = Engine(
        feed=replay_feed,
        features=FeatureBuilder(),
        signal_gen=MomentumLongRule(
            require_ma_bullish=True,
            min_kd_golden_cross=True,
            min_vol_ratio=1.5,
            require_macd_positive=True,
            min_price_vs_ma20_pct=-2.0,
        ),
        position_mgr=PositionManager(
            stop_loss_pct=1.0,
            take_profit_pct=1.7,
            force_exit="13:00",
        ),
        risk_mgr=RiskManager(
            total_capital=500_000,
            max_lot_per_symbol=2,
            max_open_positions=5,
            entry_cutoff="09:45",
            force_exit="13:00",
            timezone="Asia/Taipei",
        ),
        executor=DryRunExecutor(),
        signals_db=SignalsDB(db_path),
    )

    # 4. Run — must not raise
    engine.run()

    # 5. Verify signals.sqlite is queryable (even if 0 rows is OK)
    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    conn.close()
    assert isinstance(rows, int)
