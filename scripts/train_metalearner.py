"""
scripts/train_metalearner.py
=============================
Trains a Layer 3 MetaLearner against the active profile's fitness target,
using a recent backtest's trade log + snapshots as the (X, y) source.

Walk-forward rolling folds:
  At each anchor date t:
    Train on bars[t-train_window : t]
    Predict next forward_horizon days
    Roll anchor forward; repeat
  Continuous validation: every forward block is scored against realized
  profile-aware fitness as soon as that block's data is available.

Output:
  - data/governor/metalearner_<profile>.pkl  (trained model)
  - docs/Audit/metalearner_validation_<profile>.md  (validation report)

This is a portfolio-level meta-learner for the first build (Session N+1).
Per-ticker training is a Session N+1.5 follow-up — it requires logging
per-bar per-ticker edge scores during the backtest, which the current
backtest doesn't capture. The portfolio-level model is enough to prove
the architecture works and to validate against the linear baseline.

Read-only on the inputs (trade log + snapshots). Does NOT trigger a
backtest. Safe to run during another backtest in the background.

Usage:
  PYTHONPATH=. python scripts/train_metalearner.py
  PYTHONPATH=. python scripts/train_metalearner.py --profile growth
  PYTHONPATH=. python scripts/train_metalearner.py --run-id <uuid>
"""
from __future__ import annotations

import argparse
import math
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from core.fitness import compute_fitness, get_active_profile
from core.metrics_engine import MetricsEngine
from engines.engine_a_alpha.metalearner import MetaLearner

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def find_latest_run(run_id: Optional[str] = None) -> Path:
    """Locate the run directory whose trades.csv + portfolio_snapshots.csv
    we'll use as training data. Defaults to the most recent."""
    if run_id:
        path = ROOT / "data" / "trade_logs" / run_id
        if not (path / "trades.csv").exists():
            raise FileNotFoundError(f"No trades.csv at {path}")
        return path
    candidates = list((ROOT / "data" / "trade_logs").glob("*/trades.csv"))
    if not candidates:
        raise FileNotFoundError("No trade logs found")
    return max(candidates, key=lambda p: p.stat().st_mtime).parent


def load_per_edge_daily_pnl(trades_path: Path) -> pd.DataFrame:
    """Aggregate trade-level fills into a (date × edge) daily PnL matrix.

    Index: business-day dates from the trade log.
    Columns: edge_id strings (excluding the legacy 'Unknown' bucket).
    Values: realized PnL contributed by that edge on that date (USD).
    Missing (date, edge) cells default to 0.0.
    """
    trades = pd.read_csv(trades_path)
    if "edge" not in trades.columns or "pnl" not in trades.columns:
        raise ValueError(
            "trades.csv must have 'edge' and 'pnl' columns "
            "(post-attribution-fix shape)"
        )
    trades = trades.copy()
    trades["date"] = pd.to_datetime(trades["timestamp"]).dt.normalize()
    trades["pnl"] = pd.to_numeric(trades["pnl"], errors="coerce").fillna(0.0)
    trades = trades[trades["edge"].astype(str).str.len() > 0]
    trades = trades[trades["edge"] != "Unknown"]

    pivot = trades.pivot_table(
        index="date", columns="edge", values="pnl", aggfunc="sum", fill_value=0.0,
    ).sort_index()
    return pivot


def load_portfolio_returns(snapshots_path: Path) -> pd.Series:
    """Daily portfolio return series from portfolio_snapshots.csv.

    Returns a Series indexed by date; values are equity_t / equity_{t-1} - 1.
    """
    snaps = pd.read_csv(snapshots_path)
    snaps["date"] = pd.to_datetime(snaps["timestamp"]).dt.normalize()
    snaps = snaps.sort_values("date").drop_duplicates(subset="date", keep="last")
    snaps.set_index("date", inplace=True)
    return snaps["equity"].pct_change().dropna()


# ---------------------------------------------------------------------------
# Feature engineering
# ---------------------------------------------------------------------------

def build_features(
    edge_pnl: pd.DataFrame,
    initial_capital: float = 100_000.0,
    rolling_windows: Tuple[int, ...] = (5, 20),
) -> pd.DataFrame:
    """Build a (date × feature) DataFrame from per-edge daily PnL.

    For each edge column, generates:
      <edge>_ret_avg5   : trailing 5-day mean of daily return contribution
      <edge>_ret_avg20  : trailing 20-day mean
      <edge>_active5    : trailing 5-day count of non-zero days

    Daily return contribution = daily_pnl / initial_capital.
    Index aligns with edge_pnl. Initial bars where rolling windows aren't
    full produce NaN; the trainer drops those rows.
    """
    rets = edge_pnl / initial_capital
    parts: List[pd.DataFrame] = []
    for edge in rets.columns:
        for w in rolling_windows:
            series_avg = rets[edge].rolling(w, min_periods=max(2, w // 2)).mean()
            parts.append(series_avg.rename(f"{edge}_ret_avg{w}"))
        active = (rets[edge] != 0.0).astype(int)
        parts.append(
            active.rolling(5, min_periods=2).sum().rename(f"{edge}_active5")
        )
    feat_df = pd.concat(parts, axis=1)
    return feat_df


def build_profile_aware_target(
    portfolio_returns: pd.Series,
    profile,
    forward_horizon: int = 5,
) -> pd.Series:
    """Build the training target: profile-aware fitness over the next
    `forward_horizon` days, computed at each bar.

    For each date d, take the equity curve over [d, d+forward_horizon],
    compute MetricsEngine.calculate_all on that window, then apply the
    active profile's compute_fitness. Result is a Series indexed by d.
    """
    # We need the synthetic equity curve over each forward window. Easier:
    # work on cumulative returns and slide.
    targets: Dict[pd.Timestamp, float] = {}
    rets = portfolio_returns.copy()
    dates = list(rets.index)
    for i in range(len(dates) - forward_horizon):
        window_rets = rets.iloc[i : i + forward_horizon]
        equity = (1.0 + window_rets).cumprod()
        equity.index = window_rets.index  # ensure datetime index for cagr
        equity = pd.concat(
            [pd.Series([1.0], index=[window_rets.index[0] - pd.Timedelta(days=1)]), equity]
        )
        # MetricsEngine guards against degenerate windows by returning empty
        # metrics; treat that as fitness=0.
        try:
            metrics = MetricsEngine.calculate_all(equity)
            fit = compute_fitness(metrics, profile)
        except Exception:
            fit = 0.0
        if not math.isfinite(fit):
            fit = 0.0
        targets[dates[i]] = float(fit)
    return pd.Series(targets, name="profile_fitness").sort_index()


# ---------------------------------------------------------------------------
# Walk-forward training
# ---------------------------------------------------------------------------

def walk_forward_train(
    X: pd.DataFrame,
    y: pd.Series,
    train_window: int = 252,
    forward_horizon: int = 5,
    profile_name: str = "balanced",
) -> Tuple[MetaLearner, List[Dict[str, float]]]:
    """Train the meta-learner via walk-forward folds and report per-fold
    out-of-sample correlation between predictions and realized target.

    The FINAL model is fit on ALL aligned training data (last fold's
    training window) — this is the production model. The fold-by-fold
    OOS correlations are the validation evidence that promotion gates
    will use; we surface them in the report.
    """
    aligned = pd.concat([X, y.rename("target")], axis=1, sort=True).dropna()
    if len(aligned) < train_window + forward_horizon + 30:
        raise ValueError(
            f"Insufficient aligned data: {len(aligned)} rows. Need at least "
            f"{train_window + forward_horizon + 30} for walk-forward training."
        )

    fold_results: List[Dict[str, float]] = []
    fold_step = forward_horizon  # roll forward by the prediction horizon

    # Walk-forward: anchor at train_window, predict next forward_horizon,
    # roll forward by fold_step, repeat until we run out of data.
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
        except ValueError:
            # Insufficient samples after NaN drop — skip this fold.
            continue

        preds = ml.predict(X_val)
        if not isinstance(preds, np.ndarray):
            preds = np.array([preds])
        if len(preds) < 2 or y_val.std() == 0 or pd.Series(preds).std() == 0:
            corr = 0.0
        else:
            corr = float(np.corrcoef(preds, y_val.values)[0, 1])

        fold_results.append({
            "anchor_date": str(aligned.index[anchor_idx].date()),
            "n_train": int(len(X_train)),
            "n_val": int(len(X_val)),
            "oos_corr": float(corr) if math.isfinite(corr) else 0.0,
            "y_val_mean": float(y_val.mean()),
            "preds_mean": float(np.mean(preds)),
        })

    # Final production model: fit on ALL aligned data (no holdout — the
    # promotion evidence is the rolling fold corrs above).
    final = MetaLearner(profile_name=profile_name)
    final.fit(aligned.iloc[:, :-1], aligned.iloc[:, -1])

    return final, fold_results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_validation_report(
    profile_name: str,
    fold_results: List[Dict[str, float]],
    final_model: MetaLearner,
    run_path: Path,
    out_path: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    lines.append(f"# MetaLearner Validation Report — profile=`{profile_name}`")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"Source run: `{run_path.relative_to(ROOT)}`")
    lines.append(f"Final model: `data/governor/metalearner_{profile_name}.pkl`")
    lines.append("")
    lines.append("## What this measures")
    lines.append("")
    lines.append("Walk-forward rolling folds: at each anchor date, the model trains on")
    lines.append("the trailing 1-year window, predicts the next 5-day forward target,")
    lines.append("and rolls forward. Each fold's OOS correlation between predictions")
    lines.append("and realized profile-aware fitness is the validation signal.")
    lines.append("")
    lines.append("**Promotion gate** (Session N+2 wiring):")
    lines.append("- Mean OOS correlation > 0 across all folds (model adds signal)")
    lines.append("- ≥60% of folds with positive OOS correlation (consistent, not lucky)")
    lines.append("")

    # Final model summary
    lines.append("## Final model")
    lines.append("")
    lines.append(f"- Train samples (full data): **{final_model.n_train_samples}**")
    lines.append(f"- Features: **{len(final_model.feature_names) if final_model.feature_names else 0}**")
    lines.append(f"- Train R²: {final_model.train_metadata.get('train_score_r2', 0):.3f}")
    lines.append(f"- Target range: [{final_model.train_metadata.get('target_min', 0):.4f}, "
                 f"{final_model.train_metadata.get('target_max', 0):.4f}]")
    lines.append(f"- Predictions clipped to: ±{final_model.target_clip:.4f}")
    lines.append("")

    # Fold table
    lines.append("## Walk-forward folds")
    lines.append("")
    lines.append(f"Total folds: **{len(fold_results)}**")
    if fold_results:
        n_positive = sum(1 for r in fold_results if r["oos_corr"] > 0)
        mean_corr = float(np.mean([r["oos_corr"] for r in fold_results]))
        median_corr = float(np.median([r["oos_corr"] for r in fold_results]))
        lines.append(f"Folds with positive OOS correlation: **{n_positive}/{len(fold_results)}** "
                     f"({100*n_positive/len(fold_results):.0f}%)")
        lines.append(f"Mean OOS correlation: **{mean_corr:+.3f}**")
        lines.append(f"Median OOS correlation: **{median_corr:+.3f}**")
        lines.append("")
        lines.append("| Anchor | n_train | n_val | OOS corr | y_val mean | preds mean |")
        lines.append("|--------|---------|-------|----------|------------|------------|")
        for r in fold_results[:50]:  # cap table size for readability
            lines.append(
                f"| {r['anchor_date']} | {r['n_train']} | {r['n_val']} | "
                f"{r['oos_corr']:+.3f} | {r['y_val_mean']:+.4f} | {r['preds_mean']:+.4f} |"
            )
        if len(fold_results) > 50:
            lines.append(f"| ... | ... | ... | ... | ... | ... |")
            lines.append(f"| (total {len(fold_results)} folds, showing first 50) | | | | | |")
        lines.append("")

        # Promotion verdict
        passes = (mean_corr > 0) and (n_positive / len(fold_results) >= 0.6)
        lines.append("## Promotion verdict")
        lines.append("")
        if passes:
            lines.append(f"**🟢 PASSES promotion gate.** Mean OOS corr {mean_corr:+.3f} > 0 "
                         f"and {100*n_positive/len(fold_results):.0f}% of folds positive (≥60% required).")
        else:
            lines.append(f"**🔴 DOES NOT PASS promotion gate.** Mean OOS corr {mean_corr:+.3f}, "
                         f"{100*n_positive/len(fold_results):.0f}% of folds positive. "
                         f"Either model has no signal vs the profile target, or training data is "
                         f"too noisy. Investigate before wiring into signal_processor.")
        lines.append("")

    # Top features by importance (sklearn GBR exposes feature_importances_)
    if final_model._model is not None and final_model.feature_names:
        importances = getattr(final_model._model, "feature_importances_", None)
        if importances is not None:
            lines.append("## Top 15 features by importance")
            lines.append("")
            lines.append("| Feature | Importance |")
            lines.append("|---------|------------|")
            ranked = sorted(
                zip(final_model.feature_names, importances),
                key=lambda kv: kv[1], reverse=True,
            )
            for name, imp in ranked[:15]:
                lines.append(f"| `{name}` | {imp:.4f} |")
            lines.append("")

    lines.append("## Caveats")
    lines.append("")
    lines.append("- This is a **portfolio-level** meta-learner for the first build. Per-ticker")
    lines.append("  scoring requires logging per-bar per-ticker edge scores during the backtest")
    lines.append("  (Session N+1.5 follow-up).")
    lines.append("- Training data is from a single backtest run. Production deployment should")
    lines.append("  retrain on every new backtest to keep the rolling window fresh.")
    lines.append("- The profile-aware target uses 5-day forward windows. Multi-horizon training")
    lines.append("  + ensembling is deferred to Session N+3.")
    lines.append("- No adversarial-features audit yet (Boruta-style). Session N+1's scope was")
    lines.append("  the architecture; feature-selection refinement comes next.")

    out_path.write_text("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Train Layer 3 MetaLearner")
    parser.add_argument("--profile", default=None,
                        help="Profile name (default: active profile from fitness_profiles.yml)")
    parser.add_argument("--run-id", default=None,
                        help="Trade-log UUID (default: most recent)")
    parser.add_argument("--initial-capital", type=float, default=100_000.0)
    parser.add_argument("--train-window", type=int, default=252,
                        help="Trailing days used to train each fold")
    parser.add_argument("--forward-horizon", type=int, default=5,
                        help="Forward N-day target window")
    parser.add_argument("--output", default=None,
                        help="Override report path")
    args = parser.parse_args()

    # Resolve active profile
    profile = get_active_profile(profile_name=args.profile)
    print(f"[TRAIN] profile={profile.name} weights={profile.weights}")

    # Locate run + load data
    run_path = find_latest_run(args.run_id)
    trades_path = run_path / "trades.csv"
    snapshots_path = run_path / "portfolio_snapshots.csv"
    print(f"[TRAIN] source run: {run_path.relative_to(ROOT)}")

    edge_pnl = load_per_edge_daily_pnl(trades_path)
    portfolio_rets = load_portfolio_returns(snapshots_path)
    print(f"[TRAIN] {edge_pnl.shape[0]} trading days, {edge_pnl.shape[1]} edges")

    # Features + target
    X = build_features(edge_pnl, initial_capital=args.initial_capital)
    y = build_profile_aware_target(
        portfolio_rets, profile, forward_horizon=args.forward_horizon,
    )
    print(f"[TRAIN] features: {X.shape}, target: {len(y)} rows")

    # Walk-forward training
    final, fold_results = walk_forward_train(
        X, y,
        train_window=args.train_window,
        forward_horizon=args.forward_horizon,
        profile_name=profile.name,
    )
    print(f"[TRAIN] walk-forward folds: {len(fold_results)}")

    # Save model + report
    saved_path = final.save()
    print(f"[TRAIN] model saved → {saved_path.relative_to(ROOT)}")
    out_path = Path(args.output) if args.output else (
        ROOT / "docs" / "Audit" / f"metalearner_validation_{profile.name}.md"
    )
    write_validation_report(
        profile_name=profile.name,
        fold_results=fold_results,
        final_model=final,
        run_path=run_path,
        out_path=out_path,
    )
    try:
        display_path = out_path.relative_to(ROOT)
    except ValueError:
        display_path = out_path
    print(f"[TRAIN] report → {display_path}")

    # Console summary
    if fold_results:
        n_positive = sum(1 for r in fold_results if r["oos_corr"] > 0)
        mean_corr = float(np.mean([r["oos_corr"] for r in fold_results]))
        print()
        print("--- summary ---")
        print(f"Folds: {len(fold_results)}, positive OOS corr: "
              f"{n_positive}/{len(fold_results)} ({100*n_positive/len(fold_results):.0f}%)")
        print(f"Mean OOS correlation: {mean_corr:+.3f}")


if __name__ == "__main__":
    main()
