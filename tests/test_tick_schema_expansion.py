from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from src.core.clock import UTC
from src.data.fake_feed import FakeFeed
from src.data.feed_base import Tick
from src.data.fugle_feed import FugleFeed
from src.data.replay_feed import ReplayFeed
from src.storage.parquet_writer import TickParquetWriter


def test_tick_new_fields_have_defaults() -> None:
    tick = Tick(
        symbol="2330",
        ts=dt.datetime.now(tz=UTC),
        price=100.0,
        volume=3,
    )
    assert tick.size == 0
    assert tick.cum_volume == 0
    assert tick.tick_type == 0
    assert tick.serial == 0


def test_tick_writer_persists_new_fields(tmp_path: Path) -> None:
    writer = TickParquetWriter(base_dir=str(tmp_path), flush_every=1)
    tick = Tick(
        symbol="2330",
        ts=dt.datetime(2026, 1, 2, 1, 0, tzinfo=UTC),
        price=100.0,
        volume=3,
        bid=99.5,
        ask=100.5,
        size=3000,
        cum_volume=12345,
        tick_type=1,
        serial=9,
    )
    writer.write(tick)
    writer.close()

    parquet_files = list(tmp_path.glob("**/*.parquet"))
    assert len(parquet_files) == 1

    df = pd.read_parquet(parquet_files[0])
    assert {"size", "cum_volume", "tick_type", "serial"}.issubset(df.columns)
    row = df.iloc[0]
    assert int(row["size"]) == 3000
    assert int(row["cum_volume"]) == 12345
    assert int(row["tick_type"]) == 1
    assert int(row["serial"]) == 9


def test_replay_feed_backwards_compatible_with_old_parquet(tmp_path: Path) -> None:
    date_str = "2026-01-02"
    date_dir = tmp_path / date_str
    date_dir.mkdir(parents=True)

    ts = dt.datetime(2026, 1, 2, 1, 0, tzinfo=UTC).isoformat()

    old_df = pd.DataFrame(
        [
            {
                "symbol": "OLD",
                "ts_utc": ts,
                "ts_taipei": ts,
                "price": 10.0,
                "volume": 1,
                "bid": 9.9,
                "ask": 10.1,
            }
        ]
    )
    old_df.to_parquet(date_dir / "OLD.parquet", index=False)

    new_df = pd.DataFrame(
        [
            {
                "symbol": "NEW",
                "ts_utc": ts,
                "ts_taipei": ts,
                "price": 20.0,
                "volume": 2,
                "bid": 19.9,
                "ask": 20.1,
                "size": 2000,
                "cum_volume": 100,
                "tick_type": -1,
                "serial": 8,
            }
        ]
    )
    new_df.to_parquet(date_dir / "NEW.parquet", index=False)

    replay = ReplayFeed(
        date=date_str,
        symbols=["OLD", "NEW"],
        base_dir=str(tmp_path),
        speed_multiplier=0.0,
    )
    replayed: list[Tick] = []
    replay.on_tick(replayed.append)
    replay.start()

    assert len(replayed) == 2
    old_tick = next(t for t in replayed if t.symbol == "OLD")
    new_tick = next(t for t in replayed if t.symbol == "NEW")

    assert old_tick.size == 0
    assert old_tick.cum_volume == 0
    assert old_tick.tick_type == 0
    assert old_tick.serial == 0

    assert new_tick.size == 2000
    assert new_tick.cum_volume == 100
    assert new_tick.tick_type == -1
    assert new_tick.serial == 8


def test_fugle_handle_message_maps_new_fields() -> None:
    feed = FugleFeed(api_key="dummy")
    ticks: list[Tick] = []
    feed.on_tick(ticks.append)

    feed._handle_message(
        {
            "event": "data",
            "channel": "trades",
            "data": {
                "symbol": "2330",
                "price": 100.0,
                "size": 3000,
                "bid": 99.5,
                "ask": 100.5,
                "volume": 12345,
                "time": 1_700_000_000_000_000,
                "serial": 77,
                "tick": 2,
            },
        }
    )
    feed._handle_message(
        {
            "event": "data",
            "channel": "trades",
            "data": {
                "symbol": "2330",
                "price": 101.0,
                "size": 1000,
                "time": 1_700_000_000_100_000,
            },
        }
    )
    feed._handle_message(
        {
            "event": "data",
            "channel": "trades",
            "data": {
                "symbol": "2330",
                "price": 102.0,
                "size": 1000,
                "time": 1_700_000_000_200_000,
                "tick": 1,
            },
        }
    )

    assert len(ticks) == 3
    first, second, third = ticks
    assert first.volume == 3  # keep existing lots conversion
    assert first.size == 3000
    assert first.cum_volume == 12345
    assert first.tick_type == 1
    assert first.serial == 77

    assert second.size == 1000
    assert second.cum_volume == 0
    assert second.tick_type == 0
    assert second.serial == 0

    assert third.tick_type == -1


def test_fake_feed_populates_new_fields() -> None:
    feed = FakeFeed(tick_interval_ms=0, seed=1, max_ticks=5)
    feed.subscribe(["2330"])
    ticks: list[Tick] = []
    feed.on_tick(ticks.append)
    feed.start()

    assert len(ticks) == 5
    for tick in ticks:
        assert tick.size == tick.volume * 1000
        assert tick.tick_type in (-1, 1)

    serials = [tick.serial for tick in ticks]
    assert serials == [1, 2, 3, 4, 5]

    cum_volumes = [tick.cum_volume for tick in ticks]
    assert cum_volumes == sorted(cum_volumes)
