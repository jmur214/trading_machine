"""scripts/train_per_ticker_metalearner.py
=============================================
Phase 2.11 proper — per-ticker meta-learner training.

Companion to scripts/train_metalearner.py (portfolio-level). This trainer
consumes the per-ticker-score parquet emitted by the
PerTickerScoreLogger and produces ONE MODEL PER TICKER. The structural
hypothesis is that ticker-specific edge-weighting beats a single
portfolio-wide model by capturing idiosyncratic edge × ticker
interactions the linear allocator and portfolio model can't express.

Design
------
- Data source: data/research/per_ticker_scores/{run_uuid}.parquet
  (schema: timestamp, ticker, edge_id, raw_score, norm_score, weight,
   aggregate_score, regime_summary, fired)
- Per ticker:
    1. Filter parquet to that ticker
    2. Pivot to (date × edge_id) using raw_score as the value
    3. Build forward N-day target from data/processed/{ticker}_1d.csv
       (per-ticker price-derived return — pure ticker-future signal)
    4. Walk-forward folds (anchor 252d / forward 5d / step 5d) to
       measure OOS correlation
    5. Final model fit on full per-ticker data
    6. Save to data/governor/per_ticker_metalearners/{ticker}.pkl
- Cold-start fallback: sparse-data tickers (< min_train_samples after
  alignment) are SKIPPED. SignalProcessor's per-ticker loader falls
  back to the portfolio model when no per-ticker file exists. This
  keeps the deployment simple — a ticker either has its own model or
  uses the portfolio default; no clustering needed unless we discover
  it helps.

Leakage guards
--------------
- Training corpus must end 2024-12-31 for the 2025 OOS validation
  to be honest. The CLI prints the parquet's date range; if any
  timestamp >= 2025-01-01 is present the trainer aborts.
- Forward-return target uses N+1..N+H window — never includes the
  training row itself.

Usage
-----
    python scripts/train_per_ticker_metalearner.py
    python scripts/train_per_ticker_metalearner.py --parquet PATH
    python scripts/train_per_ticker_metalearner.py --tickers AAPL MSFT
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engines.engine_a_alpha.metalearner import MetaLearner  # noqa: E402

PER_TICKER_PARQUET_DIR = ROOT / "data" / "research" / "per_ticker_scores"
PER_TICKER_MODEL_DIR = ROOT / "data" / "governor" / "per_ticker_metalearners"
PROCESSED_DIR = ROOT / "data" / "processed"

# Leakage check: training corpus must not contain any 2025+ data so the
# 2025 OOS validation is honest.
LEAKAGE_CUTOFF = pd.Timestamp("2025-01-01")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def find_latest_per_ticker_parquet() -> Path:
    candidates = sorted(
        PER_TICKER_PARQUET_DIR.glob("*.parquet"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )
    # Prefer the largest file (a real in-sample run vs a tiny smoke).
    if not candidates:
        raise FileNotFoundError(
            f"No per-ticker score parquet found at {PER_TICKER_PARQUET_DIR}. "
            "Run a backtest with --log-per-ticker-scores first."
        )
    largest = max(candidates, key=lambda p: p.stat().st_size)
    return largest


def load_per_ticker_scores(parquet_path: Path) -> pd.DataFrame:
    df = pd.read_parquet(parquet_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def assert_no_leakage(df: pd.DataFrame, cutoff: pd.Timestamp = LEAKAGE_CUTOFF) -> Dict[str, Any]:
    """Refuse to train if the corpus contains any rows >= cutoff. Returns
    a diagnostic dict for inclusion in the audit doc."""
    diag = {
        "min_timestamp": str(df["timestamp"].min()),
        "max_timestamp": str(df["timestamp"].max()),
        "n_rows": int(len(df)),
        "n_tickers": int(df["ticker"].nunique()),
        "n_edges": int(df["edge_id"].nunique()),
        "leakage_cutoff": str(cutoff),
    }
    if df["timestamp"].max() >= cutoff:
        n_leak = int((df["timestamp"] >= cutoff).sum())
        diag["leakage_rows"] = n_leak
        raise ValueError(
            f"LEAKAGE DETECTED: {n_leak} rows have timestamp >= {cutoff}. "
            f"Training corpus must end before the OOS window. "
            f"max_timestamp={diag['max_timestamp']}"
        )
    diag["leakage_check"] = "PASS"
    return diag


# ---------------------------------------------------------------------------
# Per-ticker feature/target construction
# ---------------------------------------------------------------------------

def per_ticker_features(
    df: pd.DataFrame, ticker: str,
) -> pd.DataFrame:
    """Pivot per-ticker rows to (date × edge_id) of raw_score.

    Result: index = trading dates the ticker was active, columns =
    edge_ids. NaN where the edge produced no row that day; we fill with
    0 to match the inference-path treatment of "no opinion."
    """
    sub = df[df["ticker"] == ticker]
    if sub.empty:
        return pd.DataFrame()
    sub = sub.copy()
    sub["date"] = sub["timestamp"].dt.normalize()
    pivot = sub.pivot_table(
        index="date", columns="edge_id", values="raw_score",
        aggfunc="mean",
    ).fillna(0.0).sort_index()
    return pivot


def per_ticker_forward_return(
    ticker: str, dates: pd.DatetimeIndex, forward_horizon: int = 5,
) -> pd.Series:
    """Forward H-day return on the ticker's CLOSE series.

    target[d] = ticker_close[d+H] / ticker_close[d] - 1, evaluated on
    the trading-day calendar of the ticker's processed CSV. Uses
    iloc-based indexing so the calendar is the ticker's own (handles
    holidays + delistings naturally). Returns NaN for the last H bars.
    """
    csv_path = PROCESSED_DIR / f"{ticker}_1d.csv"
    if not csv_path.exists():
        return pd.Series(dtype=float, name=f"{ticker}_fwd")
    px = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    if "Close" not in px.columns:
        return pd.Series(dtype=float, name=f"{ticker}_fwd")
    close = pd.to_numeric(px["Close"], errors="coerce").dropna()
    if close.empty:
        return pd.Series(dtype=float, name=f"{ticker}_fwd")
    fwd = close.shift(-forward_horizon) / close - 1.0
    fwd.index = pd.to_datetime(fwd.index).normalize()
    # Reindex to the requested dates so caller can align with features
    return fwd.reindex(dates).rename(f"{ticker}_fwd")


# ---------------------------------------------------------------------------
# Per-ticker walk-forward training
# ---------------------------------------------------------------------------

def walk_forward_train_ticker(
    X: pd.DataFrame, y: pd.Series,
    train_window: int = 252,
    forward_horizon: int = 5,
    profile_name: str = "balanced",
) -> Tuple[Optional[MetaLearner], List[Dict[str, float]]]:
    """Walk-forward training for ONE ticker.

    Same fold structure as scripts/train_metalearner.py. Returns
    (final_model_or_None, fold_diagnostics). final_model is None when
    the ticker has insufficient aligned data — caller skips it; the
    inference-time loader will cold-start to the portfolio model.
    """
    aligned = pd.concat([X, y.rename("target")], axis=1, sort=True).dropna()
    min_required = train_window + forward_horizon + 30
    if len(aligned) < min_required:
        return None, [{
            "skip": True,
            "reason": f"insufficient_aligned_rows {len(aligned)} < {min_required}",
        }]

    fold_results: List[Dict[str, float]] = []
    fold_step = forward_horizon
    anchors = list(range(train_window, len(aligned) - forward_horizon, fold_step))

    for anchor_idx in anchors:
        train_start = anchor_idx - train_window
        X_train = aligned.iloc[train_start:anchor_idx, :-1]
        y_train = aligned.iloc[train_start:anchor_idx, -1]
        X_val = aligned.iloc[anchor_idx : anchor_idx + forward_horizon, :-1]
        y_val = aligned.iloc[anchor_idx : anchor_idx + forward_horizon, -1]

        ml = MetaLearner(profile_name=profile_name)
        try:
            ml.fit(X_train, y_train)
        except (ValueError, RuntimeError):
            continue

        preds = ml.predict(X_val)
        if not isinstance(preds, np.ndarray):
            preds = np.array([preds])
        if (
            len(preds) < 2 or y_val.std() == 0 or pd.Series(preds).std() == 0
        ):
            corr = 0.0
        else:
            corr = float(np.corrcoef(preds, y_val.values)[0, 1])

        fold_results.append({
            "anchor_date": str(aligned.index[anchor_idx].date()),
            "n_train": int(len(X_train)),
            "n_val": int(len(X_val)),
            "oos_corr": float(corr) if math.isfinite(corr) else 0.0,
        })

    # Final model on ALL aligned data (production model)
    final = MetaLearner(profile_name=profile_name)
    final.fit(aligned.iloc[:, :-1], aligned.iloc[:, -1])
    return final, fold_results


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _save_per_ticker(model: MetaLearner, ticker: str) -> Path:
    """Same payload format as MetaLearner.save() but at the per-ticker
    path. We can't reuse MetaLearner.save() because it derives the path
    from profile_name; here we want ticker-keyed paths."""
    import joblib
    PER_TICKER_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    path = PER_TICKER_MODEL_DIR / f"{ticker}.pkl"
    payload = {
        "profile_name": model.profile_name,
        "ticker": ticker,
        "hyperparams": model.hyperparams,
        "model": model._model,
        "feature_names": model.feature_names,
        "target_clip": model.target_clip,
        "n_train_samples": model.n_train_samples,
        "train_metadata": model.train_metadata,
    }
    joblib.dump(payload, path)
    return path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parquet", default=None,
                    help="Path to per-ticker scores parquet (default: largest in default dir)")
    ap.add_argument("--profile", default="balanced",
                    help="Profile name to write into model metadata")
    ap.add_argument("--train-window", type=int, default=252)
    ap.add_argument("--forward-horizon", type=int, default=5)
    ap.add_argument("--tickers", nargs="*", default=None,
                    help="Train only this subset (default: all tickers in parquet)")
    ap.add_argument("--out-csv", default="data/research/per_ticker_metalearner_summary.csv")
    args = ap.parse_args()

    parquet_path = Path(args.parquet) if args.parquet else find_latest_per_ticker_parquet()
    print(f"[TRAIN-PT] Loading {parquet_path} ...")
    df = load_per_ticker_scores(parquet_path)
    diag = assert_no_leakage(df)
    print(f"[TRAIN-PT] Corpus: {diag['n_rows']:,} rows, "
          f"{diag['n_tickers']} tickers, "
          f"{diag['n_edges']} edges, "
          f"date range {diag['min_timestamp'][:10]} → {diag['max_timestamp'][:10]}")
    print(f"[TRAIN-PT] Leakage check: {diag['leakage_check']}")

    tickers_in_corpus: List[str] = sorted(df["ticker"].unique().tolist())
    if args.tickers:
        tickers_to_train = [t for t in args.tickers if t in tickers_in_corpus]
        print(f"[TRAIN-PT] Filtered to {len(tickers_to_train)} of {len(args.tickers)} requested")
    else:
        tickers_to_train = tickers_in_corpus
    print(f"[TRAIN-PT] Will train {len(tickers_to_train)} per-ticker models")

    summary_rows: List[Dict[str, Any]] = []
    n_trained = 0
    n_skipped = 0
    for i, ticker in enumerate(tickers_to_train, 1):
        X = per_ticker_features(df, ticker)
        if X.empty:
            n_skipped += 1
            summary_rows.append({
                "ticker": ticker, "trained": False, "reason": "empty_features",
                "n_rows": 0, "n_features": 0, "mean_oos_corr": 0.0,
                "n_folds": 0, "frac_positive_folds": 0.0,
                "train_r2": 0.0, "n_train_samples": 0,
            })
            continue
        y = per_ticker_forward_return(ticker, X.index, args.forward_horizon)
        model, fold_results = walk_forward_train_ticker(
            X, y,
            train_window=args.train_window,
            forward_horizon=args.forward_horizon,
            profile_name=args.profile,
        )
        if model is None:
            n_skipped += 1
            reason = fold_results[0].get("reason", "unknown") if fold_results else "no_folds"
            summary_rows.append({
                "ticker": ticker, "trained": False, "reason": reason,
                "n_rows": int(len(X)), "n_features": int(X.shape[1]),
                "mean_oos_corr": 0.0, "n_folds": 0,
                "frac_positive_folds": 0.0, "train_r2": 0.0,
                "n_train_samples": 0,
            })
            print(f"[TRAIN-PT] [{i:3d}/{len(tickers_to_train)}] {ticker:<8} SKIP ({reason})")
            continue

        path = _save_per_ticker(model, ticker)
        n_trained += 1
        n_folds = len(fold_results)
        if n_folds:
            mean_corr = float(np.mean([r["oos_corr"] for r in fold_results]))
            frac_pos = sum(1 for r in fold_results if r["oos_corr"] > 0) / n_folds
        else:
            mean_corr = 0.0
            frac_pos = 0.0
        summary_rows.append({
            "ticker": ticker, "trained": True, "reason": "ok",
            "n_rows": int(len(X)), "n_features": int(X.shape[1]),
            "mean_oos_corr": mean_corr, "n_folds": n_folds,
            "frac_positive_folds": frac_pos,
            "train_r2": float(model.train_metadata.get("train_score_r2", 0.0)),
            "n_train_samples": int(model.n_train_samples),
        })
        print(f"[TRAIN-PT] [{i:3d}/{len(tickers_to_train)}] {ticker:<8} "
              f"OK n={model.n_train_samples} folds={n_folds} "
              f"mean_corr={mean_corr:+.3f} R²={model.train_metadata.get('train_score_r2',0):.3f}")

    print()
    print(f"[TRAIN-PT] Trained {n_trained} models, skipped {n_skipped}")

    summary_df = pd.DataFrame(summary_rows)
    out_csv = ROOT / args.out_csv
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    summary_df.to_csv(out_csv, index=False)
    print(f"[TRAIN-PT] Summary → {out_csv}")

    # Aggregate stats for the audit doc
    if not summary_df.empty:
        trained_mask = summary_df["trained"]
        if trained_mask.any():
            t = summary_df[trained_mask]
            print()
            print("=== aggregate over trained tickers ===")
            print(f"  n_models: {int(trained_mask.sum())}")
            print(f"  mean OOS corr: {t['mean_oos_corr'].mean():+.4f}")
            print(f"  median OOS corr: {t['mean_oos_corr'].median():+.4f}")
            print(f"  fraction with mean_oos_corr > 0: "
                  f"{(t['mean_oos_corr'] > 0).mean():.1%}")
            print(f"  mean train R²: {t['train_r2'].mean():.3f}")
            print()
            top = t.sort_values("mean_oos_corr", ascending=False).head(10)
            print("Top 10 tickers by mean OOS corr:")
            print(top[["ticker", "mean_oos_corr", "n_folds", "train_r2", "n_train_samples"]].to_string(index=False))
            print()
            bot = t.sort_values("mean_oos_corr").head(10)
            print("Bottom 10 tickers by mean OOS corr:")
            print(bot[["ticker", "mean_oos_corr", "n_folds", "train_r2", "n_train_samples"]].to_string(index=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
