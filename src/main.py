"""Entry point. Wires components based on config and starts the engine."""
from __future__ import annotations

import argparse

from src.core.config import load_config
from src.core.engine import Engine
from src.core.logging_setup import setup_logging
from src.data.fake_feed import FakeFeed
from src.execution.dryrun import DryRunExecutor
from src.storage.db import SignalsDB
from src.strategy.features import FeatureBuilder
from src.strategy.position import PositionManager
from src.strategy.risk import RiskManager
from src.strategy.signals.rule_model import DummyRuleModel


def build_feed(cfg):
    feed_type = cfg.get("data_feed", "type", default="fake")
    if feed_type == "fake":
        fake_cfg = cfg.get("data_feed", "fake", default={}) or {}
        return FakeFeed(
            tick_interval_ms=fake_cfg.get("tick_interval_ms", 200),
            seed=fake_cfg.get("seed", 42),
        )
    raise NotImplementedError(f"data_feed.type={feed_type!r} not implemented yet")


def build_signal_generator(cfg):
    sig_type = cfg.get("signal", "type", default="rule")
    if sig_type == "rule":
        rule_cfg = cfg.get("signal", "rule", default={}) or {}
        return DummyRuleModel(min_return_pct=rule_cfg.get("min_momentum_3m_pct", 0.3))
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
    )
    risk_mgr = RiskManager(
        total_capital=cfg.get("risk", "total_capital", default=500000),
        max_lot_per_symbol=cfg.get("risk", "max_lot_per_symbol", default=2),
        max_open_positions=cfg.get("risk", "max_open_positions", default=5),
    )
    executor = build_executor(cfg)
    signals_db = SignalsDB(cfg.get("storage", "signals_db", default="db/signals.sqlite"))

    engine = Engine(
        feed=feed,
        features=features,
        signal_gen=signal_gen,
        position_mgr=position_mgr,
        risk_mgr=risk_mgr,
        executor=executor,
        signals_db=signals_db,
    )
    engine.run()


if __name__ == "__main__":
    main()
