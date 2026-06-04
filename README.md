# STOCK — Day-Trade AI Bot Scaffold

Private scaffold for a Taiwan stock day-trading research & signal system.

> ⚠️ Research / educational use only. Trading involves risk; you are responsible for any real-money decisions.

## Architecture (3 layers, decoupled)

```
Data Layer       → MarketDataFeed (live / replay)
Strategy Layer   → FeatureBuilder → SignalGenerator → PositionManager → RiskManager
Execution Layer  → Executor (dryrun / paper / notify / broker)
```

The Strategy layer does NOT know whether data comes from live market or replay,
nor whether the executor is dry-run or a real broker. This is the whole point.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate           # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Run the empty pipeline with a FakeFeed + dummy rule + DryRunExecutor
python -m src.main --config config/config.yaml
```

You should see fake ticks streaming, occasional `Signal(...)` lines in the log,
and rows being inserted into `db/signals.sqlite`.

## Project layout

```
STOCK/
├── config/
│   ├── config.yaml
│   └── .env.example
├── src/
│   ├── core/         # engine, config loader, clock
│   ├── data/         # MarketDataFeed implementations
│   ├── strategy/     # features, signals, position, risk
│   ├── execution/    # executor implementations
│   ├── storage/      # SQLite + parquet writers
│   └── main.py
├── tests/
├── data/             # gitignored — tick parquet, etc.
├── models/           # gitignored — trained model artifacts
├── logs/             # gitignored
├── db/               # gitignored — sqlite files
├── requirements.txt
└── README.md
```

## Roadmap

- [x] Phase 0 — Skeleton: abstract interfaces + FakeFeed + dummy rule + DryRunExecutor
- [ ] Phase 1 — Fugle MarketData WebSocket feed + tick parquet collector
- [ ] Phase 2 — Feature engineering pipeline (VWAP, volume ratio, momentum, …) — **multi-symbol pooled training**
- [ ] Phase 3 — LightGBM signal model + walk-forward backtest
- [ ] Phase 4 — PaperExecutor (simulated fills)
- [ ] Phase 5 — Notification executor (Telegram / LINE Messaging API)
- [ ] Phase 6 — Broker adapter (Shioaji / Fubon) — optional

## Design rules (do not break these)

1. All timestamps are stored as **UTC**, displayed as `Asia/Taipei`.
2. `FeatureBuilder` and `SignalGenerator` must be **pure** — no I/O, no network.
3. Every signal (including risk-rejected ones) is persisted to `signals.sqlite`
   with a full feature snapshot. This table is the future ML training data.
4. Nothing is hard-coded — all parameters live in `config/config.yaml`.
5. Use the `Clock` abstraction; never call `datetime.now()` directly inside the
   strategy layer (so backtests can inject a fake clock).
6. ML training is **multi-symbol pooled** by default. Per-symbol features
   (sector, avg volume, price level, relative strength) are added so the model
   learns *patterns*, not *individual stocks*.
