"""Tests for src/strategy/feature_pipeline.py.

All tests are self-contained: tick DataFrames are constructed in-memory (or
written to a tmp directory), so no real market data is needed.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.core.config import Config
from src.strategy.feature_pipeline import (
    FeaturePipeline,
    SymbolClassifier,
    _compute_labels,
    _zscore_normalise,
)
from src.strategy.features import FeatureBuilder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

UTC = dt.timezone.utc
TAIPEI = ZoneInfo("Asia/Taipei")


def _make_config(overrides: dict | None = None) -> Config:
    """Return a minimal Config sufficient for pipeline tests."""
    raw: dict = {
        "universe": {
            "asset_class": {
                "electronics": ["2330", "2317"],
                "traditional": ["2002"],
            },
            "sectors": {
                "foundry": ["2330"],
                "ai_server_odm": ["2317"],
                "steel": ["2002"],
            },
        },
        "features": {
            "vwap_window_min": 5,
            "momentum_windows_min": [1, 3, 5],
        },
        "feature_pipeline": {
            "ticks_dir": "data/ticks",        # overridden in each test
            "output_dir": "data/features",    # overridden in each test
            "label_minutes": 3,
            "pooled": False,
            "pooled_output_path": "data/features/pooled.parquet",
            "drop_na_labels": True,
            "normalization_strategy": "none",
            "absolute_value_cols": ["last_price", "sma5", "ma5", "ma20", "ma60",
                                     "vol_ma5", "vol_sum_recent"],
        },
    }
    if overrides:
        # Shallow-merge at top level; for feature_pipeline we do a deeper merge
        for key, val in overrides.items():
            if key in raw and isinstance(raw[key], dict) and isinstance(val, dict):
                raw[key] = {**raw[key], **val}
            else:
                raw[key] = val
    return Config(raw=raw)


def _make_ticks_df(
    symbol: str,
    n: int = 60,
    start_price: float = 100.0,
    start_ts: dt.datetime | None = None,
    interval_sec: int = 60,
) -> pd.DataFrame:
    """Build a synthetic ticks DataFrame with *n* rows."""
    if start_ts is None:
        start_ts = dt.datetime(2025, 6, 4, 1, 30, 0, tzinfo=UTC)  # UTC

    rows = []
    price = start_price
    for i in range(n):
        ts = start_ts + dt.timedelta(seconds=i * interval_sec)
        price = round(price * (1 + 0.001 * (1 if i % 2 == 0 else -1)), 4)
        rows.append(
            {
                "symbol": symbol,
                "ts_utc": ts.isoformat(),
                "ts_taipei": ts.astimezone(TAIPEI).isoformat(),
                "price": price,
                "volume": 10 + i % 5,
                "bid": round(price * 0.999, 4),
                "ask": round(price * 1.001, 4),
            }
        )
    return pd.DataFrame(rows)


def _write_ticks_parquet(
    base_dir: Path,
    date: str,
    symbol: str,
    df: pd.DataFrame,
) -> Path:
    """Write a ticks DataFrame to ``{base_dir}/{date}/{symbol}.parquet``."""
    out = base_dir / date / f"{symbol}.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False, engine="pyarrow")
    return out


# ---------------------------------------------------------------------------
# Unit tests: SymbolClassifier
# ---------------------------------------------------------------------------

class TestSymbolClassifier:
    def test_known_symbol_returns_correct_class_and_sector(self) -> None:
        cfg = _make_config()
        clf = SymbolClassifier(cfg)
        asset_class, sector = clf.get("2330")
        assert asset_class == "electronics"
        assert sector == "foundry"

    def test_unknown_symbol_returns_unknown(self) -> None:
        cfg = _make_config()
        clf = SymbolClassifier(cfg)
        asset_class, sector = clf.get("9999")
        assert asset_class == "unknown"
        assert sector == "unknown"

    def test_traditional_symbol(self) -> None:
        cfg = _make_config()
        clf = SymbolClassifier(cfg)
        asset_class, sector = clf.get("2002")
        assert asset_class == "traditional"
        assert sector == "steel"


# ---------------------------------------------------------------------------
# Unit tests: _compute_labels
# ---------------------------------------------------------------------------

class TestComputeLabels:
    def test_label_aligns_to_future_price(self) -> None:
        """With 1-min intervals and label_minutes=1, each label uses the next tick."""
        base = dt.datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC)
        timestamps = [base + dt.timedelta(minutes=i) for i in range(5)]
        prices = [100.0, 101.0, 102.0, 103.0, 104.0]
        labels = _compute_labels(timestamps, prices, label_minutes=1)

        # row 0: future tick = row 1 (price 101) → return = 1%
        assert labels[0] == pytest.approx(1.0)
        # row 1: future tick = row 2 → return = (102-101)/101*100
        assert labels[1] == pytest.approx(100.0 * (102.0 - 101.0) / 101.0)
        # last row: no future data → None
        assert labels[-1] is None

    def test_rows_without_future_data_are_none(self) -> None:
        base = dt.datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC)
        # 3 ticks, label_minutes=5 → no tick is 5 min ahead
        timestamps = [base + dt.timedelta(minutes=i) for i in range(3)]
        prices = [100.0, 101.0, 102.0]
        labels = _compute_labels(timestamps, prices, label_minutes=5)
        assert all(lbl is None for lbl in labels)

    def test_exact_boundary_tick_is_used(self) -> None:
        base = dt.datetime(2025, 1, 1, 9, 0, 0, tzinfo=UTC)
        # 3 ticks exactly 3 minutes apart; label_minutes=3
        timestamps = [base + dt.timedelta(minutes=i * 3) for i in range(3)]
        prices = [100.0, 101.0, 103.0]
        labels = _compute_labels(timestamps, prices, label_minutes=3)
        # row 0: target_ts = base+3min = timestamps[1] → uses price 101
        assert labels[0] == pytest.approx(1.0)
        # row 1: target_ts = base+6min = timestamps[2] → uses price 103
        assert labels[1] == pytest.approx(100.0 * (103.0 - 101.0) / 101.0)


# ---------------------------------------------------------------------------
# Unit tests: _zscore_normalise
# ---------------------------------------------------------------------------

class TestZscoreNormalise:
    def test_normalised_columns_have_mean_zero_std_one(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0], "b": [10.0, 20.0, 30.0, 40.0, 50.0]})
        result = _zscore_normalise(df, ["a", "b"])
        assert result["a"].mean() == pytest.approx(0.0, abs=1e-10)
        assert result["a"].std(ddof=0) == pytest.approx(1.0, abs=1e-10)

    def test_missing_column_is_skipped(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
        result = _zscore_normalise(df, ["a", "nonexistent"])
        assert "nonexistent" not in result.columns

    def test_zero_std_column_is_unchanged(self) -> None:
        df = pd.DataFrame({"a": [5.0, 5.0, 5.0]})
        result = _zscore_normalise(df, ["a"])
        # All same value → std=0 → unchanged
        assert list(result["a"]) == [5.0, 5.0, 5.0]

    def test_original_df_is_not_mutated(self) -> None:
        df = pd.DataFrame({"a": [1.0, 2.0, 3.0]})
        original_values = list(df["a"])
        _zscore_normalise(df, ["a"])
        assert list(df["a"]) == original_values


# ---------------------------------------------------------------------------
# Integration tests: FeaturePipeline.process_symbol
# ---------------------------------------------------------------------------

class TestFeaturePipelineProcessSymbol:
    def test_output_has_required_columns(self) -> None:
        cfg = _make_config()
        pipeline = FeaturePipeline(cfg)
        ticks_df = _make_ticks_df("2330", n=60)
        result = pipeline.process_symbol("2330", ticks_df)

        assert result is not None
        required = {"symbol", "ts", "asset_class", "sector", "label"}
        assert required.issubset(set(result.columns))

    def test_symbol_and_categoricals_are_correct(self) -> None:
        cfg = _make_config()
        pipeline = FeaturePipeline(cfg)
        ticks_df = _make_ticks_df("2330", n=60)
        result = pipeline.process_symbol("2330", ticks_df)

        assert result is not None
        assert (result["symbol"] == "2330").all()
        assert (result["asset_class"] == "electronics").all()
        assert (result["sector"] == "foundry").all()

    def test_row_count_is_correct(self) -> None:
        """Rows = (ticks - MIN_TICKS + 1) feature rows, minus label-missing tail."""
        cfg = _make_config()
        pipeline = FeaturePipeline(cfg)
        n = 60
        ticks_df = _make_ticks_df("2330", n=n, interval_sec=60)
        result = pipeline.process_symbol("2330", ticks_df)

        assert result is not None
        # FeatureBuilder returns a snapshot on tick #MIN_TICKS (index MIN_TICKS-1)
        # and every tick thereafter → total feature rows = n - MIN_TICKS + 1
        feature_rows = n - FeatureBuilder.MIN_TICKS + 1
        # label_minutes=3, interval=1 min → last 3 feature rows lack future data
        expected = feature_rows - pipeline._label_minutes
        assert len(result) == expected

    def test_returns_none_for_too_few_ticks(self) -> None:
        cfg = _make_config()
        pipeline = FeaturePipeline(cfg)
        ticks_df = _make_ticks_df("2330", n=FeatureBuilder.MIN_TICKS - 1)
        result = pipeline.process_symbol("2330", ticks_df)
        assert result is None

    def test_label_is_future_n_min_return(self) -> None:
        """Verify label calculation with a known monotone price sequence."""
        cfg = _make_config({"feature_pipeline": {"label_minutes": 1, "drop_na_labels": True}})
        pipeline = FeaturePipeline(cfg)

        # Build a strictly increasing price sequence
        n = 50
        start_ts = dt.datetime(2025, 6, 4, 1, 0, 0, tzinfo=UTC)
        rows = []
        for i in range(n):
            ts = start_ts + dt.timedelta(minutes=i)
            rows.append({
                "symbol": "2330",
                "ts_utc": ts.isoformat(),
                "ts_taipei": ts.astimezone(TAIPEI).isoformat(),
                "price": 100.0 + i,   # price goes 100, 101, 102, …
                "volume": 10,
                "bid": 99.0 + i,
                "ask": 101.0 + i,
            })
        ticks_df = pd.DataFrame(rows)
        result = pipeline.process_symbol("2330", ticks_df)

        assert result is not None
        # Every label should be positive (price always rises)
        assert (result["label"] > 0).all()

    def test_drop_na_labels_false_keeps_nan_rows(self) -> None:
        cfg = _make_config({"feature_pipeline": {"drop_na_labels": False}})
        pipeline = FeaturePipeline(cfg)
        # Ensure drop_na_labels is actually False
        assert pipeline._drop_na_labels is False
        ticks_df = _make_ticks_df("2330", n=50, interval_sec=60)
        result = pipeline.process_symbol("2330", ticks_df)

        assert result is not None
        # feature_rows = 50 - 30 + 1 = 21; last 3 have no future data (label_minutes=3)
        assert len(result) == 50 - FeatureBuilder.MIN_TICKS + 1
        # With drop_na_labels=False the last few rows should have NaN label
        assert result["label"].isna().any()

    def test_zscore_normalisation_applied(self) -> None:
        cfg = _make_config({
            "feature_pipeline": {
                "normalization_strategy": "per_symbol_zscore",
                "absolute_value_cols": ["last_price"],
            }
        })
        pipeline = FeaturePipeline(cfg)
        ticks_df = _make_ticks_df("2330", n=60)
        result = pipeline.process_symbol("2330", ticks_df)

        assert result is not None
        # After z-score, mean ≈ 0, std ≈ 1
        assert result["last_price"].mean() == pytest.approx(0.0, abs=0.1)
        assert result["last_price"].std(ddof=0) == pytest.approx(1.0, abs=0.1)

    def test_empty_ticks_returns_none(self) -> None:
        cfg = _make_config()
        pipeline = FeaturePipeline(cfg)
        result = pipeline.process_symbol("2330", pd.DataFrame())
        assert result is None


# ---------------------------------------------------------------------------
# Integration tests: build_for_date / build_pooled / run
# ---------------------------------------------------------------------------

class TestFeaturePipelineBuildForDate:
    def test_build_for_date_returns_all_symbols(self, tmp_path: Path) -> None:
        date = "2025-06-04"
        ticks_dir = tmp_path / "ticks"
        for sym in ["2330", "2317"]:
            _write_ticks_parquet(ticks_dir, date, sym, _make_ticks_df(sym, n=60))

        cfg = _make_config({"feature_pipeline": {"ticks_dir": str(ticks_dir)}})
        pipeline = FeaturePipeline(cfg)
        result = pipeline.build_for_date(date)

        assert set(result.keys()) == {"2330", "2317"}
        for sym, df in result.items():
            assert not df.empty
            assert (df["symbol"] == sym).all()

    def test_build_for_date_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        cfg = _make_config({"feature_pipeline": {"ticks_dir": str(tmp_path / "no_such_dir")}})
        pipeline = FeaturePipeline(cfg)
        result = pipeline.build_for_date("2025-06-04")
        assert result == {}

    def test_build_pooled_stacks_all_symbols(self, tmp_path: Path) -> None:
        date = "2025-06-04"
        ticks_dir = tmp_path / "ticks"
        for sym in ["2330", "2317", "2002"]:
            _write_ticks_parquet(ticks_dir, date, sym, _make_ticks_df(sym, n=60))

        cfg = _make_config({"feature_pipeline": {"ticks_dir": str(ticks_dir)}})
        pipeline = FeaturePipeline(cfg)
        pooled = pipeline.build_pooled(date)

        assert not pooled.empty
        assert set(pooled["symbol"].unique()) == {"2330", "2317", "2002"}

    def test_build_pooled_has_all_required_columns(self, tmp_path: Path) -> None:
        date = "2025-06-04"
        ticks_dir = tmp_path / "ticks"
        _write_ticks_parquet(ticks_dir, date, "2330", _make_ticks_df("2330", n=60))

        cfg = _make_config({"feature_pipeline": {"ticks_dir": str(ticks_dir)}})
        pipeline = FeaturePipeline(cfg)
        pooled = pipeline.build_pooled(date)

        required = {"symbol", "ts", "asset_class", "sector", "label"}
        assert required.issubset(set(pooled.columns))

    def test_run_writes_per_symbol_parquet(self, tmp_path: Path) -> None:
        date = "2025-06-04"
        ticks_dir = tmp_path / "ticks"
        output_dir = tmp_path / "features"
        for sym in ["2330", "2317"]:
            _write_ticks_parquet(ticks_dir, date, sym, _make_ticks_df(sym, n=60))

        cfg = _make_config({
            "feature_pipeline": {
                "ticks_dir": str(ticks_dir),
                "output_dir": str(output_dir),
                "pooled": False,
            }
        })
        pipeline = FeaturePipeline(cfg)
        pipeline.run(date)

        assert (output_dir / date / "2330.parquet").exists()
        assert (output_dir / date / "2317.parquet").exists()

        # Round-trip check
        df = pd.read_parquet(output_dir / date / "2330.parquet")
        assert not df.empty
        assert "label" in df.columns

    def test_run_writes_pooled_parquet(self, tmp_path: Path) -> None:
        date = "2025-06-04"
        ticks_dir = tmp_path / "ticks"
        output_dir = tmp_path / "features"
        pooled_path = tmp_path / "pooled.parquet"
        for sym in ["2330", "2317"]:
            _write_ticks_parquet(ticks_dir, date, sym, _make_ticks_df(sym, n=60))

        cfg = _make_config({
            "feature_pipeline": {
                "ticks_dir": str(ticks_dir),
                "output_dir": str(output_dir),
                "pooled": True,
                "pooled_output_path": str(pooled_path),
            }
        })
        pipeline = FeaturePipeline(cfg)
        pipeline.run(date)

        assert pooled_path.exists()
        pooled_df = pd.read_parquet(pooled_path)
        assert set(pooled_df["symbol"].unique()) == {"2330", "2317"}

    def test_ts_stored_as_utc(self, tmp_path: Path) -> None:
        """Verify that ts values are UTC ISO-8601 strings."""
        date = "2025-06-04"
        ticks_dir = tmp_path / "ticks"
        start_utc = dt.datetime(2025, 6, 4, 1, 0, 0, tzinfo=UTC)
        _write_ticks_parquet(
            ticks_dir, date, "2330",
            _make_ticks_df("2330", n=60, start_ts=start_utc)
        )

        cfg = _make_config({"feature_pipeline": {"ticks_dir": str(ticks_dir)}})
        pipeline = FeaturePipeline(cfg)
        result = pipeline.build_for_date(date)

        assert "2330" in result
        df = result["2330"]
        # All ts strings should contain "+00:00" or "Z" (UTC offset)
        for ts_str in df["ts"]:
            parsed = pd.Timestamp(ts_str)
            assert parsed.tzinfo is not None, f"ts {ts_str!r} is not timezone-aware"
            assert parsed.utcoffset().total_seconds() == 0, (
                f"ts {ts_str!r} is not UTC"
            )
