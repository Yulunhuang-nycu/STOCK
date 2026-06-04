"""Entry point. Wires components based on config and starts the engine."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.core.config import load_config
from src.core.engine import Engine
from src.core.logging_setup import setup_logging
from src.data.fake_feed import FakeFeed
from src.execution.dryrun import DryRunExecutor
from src.storage.db import SignalsDB
from src.storage.parquet_writer import TickParquetWriter
from src.strategy.features import FeatureBuilder
from src.strategy.position import PositionManager
from src.strategy.risk import RiskManager
from src.strategy.signals.rule_model import MomentumLongRule


def build_feed(cfg):
    feed_type = cfg.get("data_feed", "type", default="fake")
    if feed_type == "fake":
        fake_cfg = cfg.get("data_feed", "fake", default={}) or {}
        return FakeFeed(
            tick_interval_ms=fake_cfg.get("tick_interval_ms", 200),
            seed=fake_cfg.get("seed", 42),
        )
    elif feed_type == "fugle_live":
        api_key = os.environ.get("FUGLE_API_KEY", "")
        if not api_key:
            raise ValueError("FUGLE_API_KEY not set in .env")
        from src.data.fugle_feed import FugleFeed
        return FugleFeed(api_key=api_key)
    elif feed_type == "fugle_live_multi":
        multi_cfg = cfg.get("data_feed", "fugle_live_multi", default={}) or {}
        keys_file = str(multi_cfg.get("keys_file", "") or "").strip()
        if keys_file:
            api_keys = _read_api_keys_from_file(keys_file)
        else:
            api_keys = _read_api_keys_from_env()
        if not api_keys:
            raise ValueError(
                "fugle_live_multi 未讀到任何 API key，請設定 keys_file 或 FUGLE_API_KEY_1..N"
            )
        from src.data.multi_fugle_feed import MultiFugleFeed
        return MultiFugleFeed(
            api_keys=api_keys,
            symbols_per_key=int(multi_cfg.get("symbols_per_key", 5)),
        )
    elif feed_type == "replay":
        replay_cfg = cfg.get("data_feed", "replay", default={}) or {}
        from src.data.replay_feed import ReplayFeed
        return ReplayFeed(
            date=replay_cfg.get("date", ""),
            base_dir=cfg.get("storage", "ticks_dir", default="data/ticks"),
            speed_multiplier=replay_cfg.get("speed_multiplier", 1.0),
        )
    raise NotImplementedError(f"data_feed.type={feed_type!r} not implemented yet")


def _read_api_keys_from_file(path: str) -> list[str]:
    keys: list[str] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        keys.append(stripped)
    return keys


def _read_api_keys_from_env() -> list[str]:
    keys: list[str] = []
    index = 1
    while True:
        value = os.environ.get(f"FUGLE_API_KEY_{index}", "").strip()
        if not value:
            break
        keys.append(value)
        index += 1
    return keys


def build_signal_generator(cfg):
    sig_type = cfg.get("signal", "type", default="rule")
    if sig_type == "rule":
        rule_cfg = cfg.get("signal", "rule", default={}) or {}
        return MomentumLongRule(
            min_conditions_met=rule_cfg.get("min_conditions_met", 3),
            vol_ratio_threshold=rule_cfg.get("vol_ratio_threshold", 1.5),
            momentum_3m_threshold=rule_cfg.get("momentum_3m_threshold", 0.2),
            price_vs_ma20_min=rule_cfg.get("price_vs_ma20_min", -2.0),
        )
    raise NotImplementedError(f"signal.type={sig_type!r} not implemented yet")


def build_executor(cfg):
    exe_type = cfg.get("executor", "type", default="dryrun")
    if exe_type == "dryrun":
        return DryRunExecutor()
    raise NotImplementedError(f"executor.type={exe_type!r} not implemented yet")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(
        level=cfg.get("logging", "level", default="INFO"),
        log_file=cfg.get("logging", "file", default=None),
    )

    feed = build_feed(cfg)
    feed.subscribe(cfg.get("universe", "symbols", default=["2330"]))

    features = FeatureBuilder(
        vwap_window_min=cfg.get("features", "vwap_window_min", default=5),
        momentum_windows_min=cfg.get("features", "momentum_windows_min", default=[1, 3, 5]),
    )
    signal_gen = build_signal_generator(cfg)
    position_mgr = PositionManager(
        stop_loss_pct=cfg.get("position", "stop_loss_pct", default=1.0),
        take_profit_pct=cfg.get("position", "take_profit_pct", default=1.7),
        force_exit=cfg.get("market", "force_exit", default="13:00"),
    )
    risk_mgr = RiskManager(
        total_capital=cfg.get("risk", "total_capital", default=500000),
        max_lot_per_symbol=cfg.get("risk", "max_lot_per_symbol", default=2),
        max_open_positions=cfg.get("risk", "max_open_positions", default=5),
        entry_cutoff=cfg.get("market", "entry_cutoff", default="09:45"),
        force_exit=cfg.get("market", "force_exit", default="13:00"),
        timezone=cfg.get("market", "timezone", default="Asia/Taipei"),
    )
    executor = build_executor(cfg)
    signals_db = SignalsDB(cfg.get("storage", "signals_db", default="db/signals.sqlite"))
    ticks_dir = cfg.get("storage", "ticks_dir", default="data/ticks")
    tick_writer = TickParquetWriter(base_dir=ticks_dir)

    engine = Engine(
        feed=feed,
        features=features,
        signal_gen=signal_gen,
        position_mgr=position_mgr,
        risk_mgr=risk_mgr,
        executor=executor,
        signals_db=signals_db,
        tick_writer=tick_writer,
    )
    engine.run()


if __name__ == "__main__":
    main()
