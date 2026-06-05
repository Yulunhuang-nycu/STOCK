"""Offline feature pipeline.

Reads tick parquet files → feeds FeatureBuilder → attaches categorical columns
(asset_class, sector) → computes future-N-min return labels → optionally
normalises absolute-value features per symbol → writes feature parquet files.

Design rules (README §6):
- Pure data-transformation logic; no live I/O or network inside the classes
  themselves (I/O happens only in ``FeaturePipeline.run``).
- All parameters come from ``config/config.yaml``; nothing is hard-coded.
- Timestamps stored as UTC ISO-8601 strings.
- ``FeatureBuilder`` is called as a pure function (no I/O, no network).
"""
from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

import pandas as pd

from src.core.config import Config
from src.data.feed_base import Tick
from src.strategy.features import FeatureBuilder

log = logging.getLogger("stock.strategy.feature_pipeline")


# ---------------------------------------------------------------------------
# Symbol classifier
# ---------------------------------------------------------------------------

class SymbolClassifier:
    """Look up *asset_class* and *sector* for a symbol from ``config.yaml``.

    Pure: no I/O, no network.
    """

    def __init__(self, cfg: Config) -> None:
        self._asset_class: dict[str, str] = {}
        self._sector: dict[str, str] = {}

        asset_class_map: dict[str, list] = cfg.get("universe", "asset_class") or {}
        for cls_name, symbols in asset_class_map.items():
            for sym in symbols:
                self._asset_class[str(sym)] = str(cls_name)

        sectors_map: dict[str, list] = cfg.get("universe", "sectors") or {}
        for sector_name, symbols in sectors_map.items():
            for sym in symbols:
                self._sector[str(sym)] = str(sector_name)

    def get(self, symbol: str) -> tuple[str, str]:
        """Return ``(asset_class, sector)``; falls back to ``"unknown"``."""
        return (
            self._asset_class.get(symbol, "unknown"),
            self._sector.get(symbol, "unknown"),
        )


# ---------------------------------------------------------------------------
# Label computation helper (pure)
# ---------------------------------------------------------------------------

def _compute_labels(
    timestamps: list,
    prices: list[float],
    label_minutes: int,
) -> list[float | None]:
    """Compute future-N-minute return (%) for each row.

    For row *i*: label = 100 * (price_at_T+N – price_i) / price_i,
    where T+N is the first tick at or after ``ts_i + label_minutes`` minutes.
    Rows with no future data within the window get ``None``.

    Pure function — no I/O.
    """
    n = len(timestamps)
    label_delta = timedelta(minutes=label_minutes)
    labels: list[float | None] = [None] * n

    for i in range(n):
        target_ts = timestamps[i] + label_delta
        # Linear scan from i+1 (ticks are already sorted by ts)
        for k in range(i + 1, n):
            if timestamps[k] >= target_ts:
                current_price = prices[i]
                if current_price != 0.0:
                    labels[i] = 100.0 * (prices[k] - current_price) / current_price
                break

    return labels


# ---------------------------------------------------------------------------
# Per-symbol normalisation (pure)
# ---------------------------------------------------------------------------

def _zscore_normalise(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Return a copy of *df* with *cols* z-score normalised (mean=0, std=1).

    Columns with zero std are left unchanged (avoids division by zero).
    Pure: operates only on the passed DataFrame.
    """
    df = df.copy()
    for col in cols:
        if col not in df.columns:
            continue
        std = df[col].std(ddof=0)
        mean = df[col].mean()
        if std > 0:
            df[col] = (df[col] - mean) / std
    return df


# ---------------------------------------------------------------------------
# Main pipeline class
# ---------------------------------------------------------------------------

class FeaturePipeline:
    """Offline batch pipeline: ticks → feature snapshots with label.

    Usage::

        cfg = load_config("config/config.yaml")
        pipeline = FeaturePipeline(cfg)
        pipeline.run("2025-06-04")
    """

    def __init__(self, cfg: Config) -> None:
        self._cfg = cfg
        self._classifier = SymbolClassifier(cfg)

        def _fp(key: str, default):  # type: ignore[return]
            """Read from feature_pipeline section, returning *default* when absent."""
            val = cfg.get("feature_pipeline", key)
            return val if val is not None else default

        # Pipeline config with safe defaults
        self._ticks_dir = Path(_fp("ticks_dir", "data/ticks"))
        self._output_dir = Path(_fp("output_dir", "data/features"))
        self._label_minutes: int = int(_fp("label_minutes", 3))
        self._pooled: bool = bool(_fp("pooled", False))
        self._pooled_path = Path(_fp("pooled_output_path", "data/features/pooled.parquet"))
        self._drop_na_labels: bool = bool(_fp("drop_na_labels", True))
        self._norm_strategy: str = str(_fp("normalization_strategy", "none"))
        self._abs_cols: list[str] = list(_fp("absolute_value_cols", []))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_symbol(
        self,
        symbol: str,
        ticks_df: pd.DataFrame,
    ) -> pd.DataFrame | None:
        """Build a feature snapshot DataFrame for one symbol.

        Parameters
        ----------
        symbol:
            Ticker string (e.g. ``"2330"``).
        ticks_df:
            DataFrame with columns ``ts_utc``, ``price``, ``volume``,
            ``bid``, ``ask`` (as written by ``TickParquetWriter``).

        Returns
        -------
        DataFrame or None
            Feature snapshot table with columns ``symbol``, ``ts``,
            ``asset_class``, ``sector``, feature columns, and ``label``.
            Returns ``None`` when no features could be produced (e.g. too few
            ticks for warm-up).
        """
        if ticks_df.empty:
            return None

        fb = FeatureBuilder(
            vwap_window_min=int(self._cfg.get("features", "vwap_window_min") or 5),
            momentum_windows_min=list(
                self._cfg.get("features", "momentum_windows_min") or [1, 3, 5]
            ),
        )

        rows: list[dict] = []
        timestamps: list = []
        prices: list[float] = []

        for row in ticks_df.itertuples(index=False):
            ts_raw = row.ts_utc
            # Parse ISO timestamp; ensure it is timezone-aware UTC
            if isinstance(ts_raw, str):
                from datetime import timezone
                ts = pd.Timestamp(ts_raw).to_pydatetime()
                if ts.tzinfo is None:
                    import datetime as _dt
                    ts = ts.replace(tzinfo=_dt.timezone.utc)
            else:
                ts = pd.Timestamp(ts_raw).to_pydatetime()

            tick = Tick(
                symbol=symbol,
                ts=ts,
                price=float(row.price),
                volume=int(row.volume),
                bid=float(getattr(row, "bid", 0.0)),
                ask=float(getattr(row, "ask", 0.0)),
                cum_volume=int(getattr(row, "cum_volume", 0) or 0),
            )
            feats = fb.update(tick)
            if feats is None:
                continue  # still warming up

            asset_class, sector = self._classifier.get(symbol)
            record: dict = {
                "symbol": symbol,
                "ts": ts.isoformat(),
                "asset_class": asset_class,
                "sector": sector,
                **feats,
            }
            rows.append(record)
            timestamps.append(ts)
            prices.append(feats["last_price"])

        if not rows:
            return None

        # Compute labels
        labels = _compute_labels(timestamps, prices, self._label_minutes)
        for record, lbl in zip(rows, labels):
            record["label"] = lbl

        df = pd.DataFrame(rows)

        # Drop rows with NaN label if configured
        if self._drop_na_labels:
            df = df.dropna(subset=["label"]).reset_index(drop=True)

        if df.empty:
            return None

        # Normalise absolute-value columns per symbol
        if self._norm_strategy == "per_symbol_zscore" and self._abs_cols:
            df = _zscore_normalise(df, self._abs_cols)

        return df

    def build_for_date(self, date: str) -> dict[str, pd.DataFrame]:
        """Process all available symbols for *date*.

        Returns a mapping ``{symbol: DataFrame}``.
        """
        date_dir = self._ticks_dir / date
        if not date_dir.exists():
            log.warning("Ticks directory not found: %s", date_dir)
            return {}

        result: dict[str, pd.DataFrame] = {}
        for parquet_path in sorted(date_dir.glob("*.parquet")):
            symbol = parquet_path.stem
            try:
                ticks_df = pd.read_parquet(parquet_path)
            except Exception as exc:
                log.error("Could not read %s: %s", parquet_path, exc)
                continue

            df = self.process_symbol(symbol, ticks_df)
            if df is not None and not df.empty:
                result[symbol] = df
            else:
                log.debug("No features produced for %s on %s", symbol, date)

        return result

    def build_pooled(self, date: str) -> pd.DataFrame:
        """Build a single pooled DataFrame for all symbols on *date*."""
        per_symbol = self.build_for_date(date)
        if not per_symbol:
            return pd.DataFrame()
        return pd.concat(list(per_symbol.values()), ignore_index=True)

    def run(self, date: str) -> None:
        """Build features for *date* and write parquet files to disk.

        Writes:
        - ``{output_dir}/{date}/{symbol}.parquet`` for every symbol.
        - ``{pooled_output_path}`` (append mode) when ``pooled=True``.
        """
        log.info("FeaturePipeline: processing date=%s", date)
        per_symbol = self.build_for_date(date)

        out_date_dir = self._output_dir / date
        out_date_dir.mkdir(parents=True, exist_ok=True)

        for symbol, df in per_symbol.items():
            out_path = out_date_dir / f"{symbol}.parquet"
            df.to_parquet(out_path, index=False, engine="pyarrow")
            log.info("Wrote %d rows → %s", len(df), out_path)

        if self._pooled:
            frames = list(per_symbol.values())
            if frames:
                pooled_df = pd.concat(frames, ignore_index=True)
                self._pooled_path.parent.mkdir(parents=True, exist_ok=True)
                pooled_df.to_parquet(self._pooled_path, index=False, engine="pyarrow")
                log.info(
                    "Wrote pooled table: %d rows → %s",
                    len(pooled_df),
                    self._pooled_path,
                )

        log.info(
            "FeaturePipeline: done — %d symbols processed for %s",
            len(per_symbol),
            date,
        )
