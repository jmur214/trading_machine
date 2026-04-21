# engines/engine_f_governance/evaluator.py
from __future__ import annotations

"""
EdgeEvaluator
=============

Reads aggregated research results (e.g., from research/edge_harness.py),
scores each run with robust normalization + time-decay, and produces
ranked edge intelligence for downstream consumers (Governor, Dashboard).

Inputs (auto-detected, Parquet preferred with CSV fallback):
- data/research/edge_results.parquet
- data/research/edge_results.csv

Outputs:
- data/research/edge_intelligence.parquet (or .csv fallback)
- data/research/edge_intelligence_summary.json
- data/research/edge_recommendations.json  (normalized weights 0..1)

This module is dependency-light (pandas/numpy only) and fails closed:
missing columns are created as NaN, unsafe calcs are guarded, and
Parquet falls back to CSV if pyarrow/fastparquet are unavailable.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import json
import math
import numpy as np
import pandas as pd


# ----------------------------- Config ----------------------------- #

@dataclass
class EvaluatorConfig:
    # Composite score weights (sum does not need to be 1; we normalize)
    w_sharpe: float = 0.40
    w_cagr: float = 0.30
    w_winrate: float = 0.20
    w_mdd: float = 0.10  # applied as penalty

    # Time decay (half-life in days)
    decay_half_life_days: float = 180.0

    # Robust normalization
    rank_normalize: bool = True    # rank-based normalization [-1, +1]
    winsor_pct: float = 0.02       # if not using rank, winsorize tails

    # Recent window diagnostics
    recent_days: int = 90

    # Minimum rows per edge for stability stats
    min_rows_for_stats: int = 3


# --------------------------- Utilities ---------------------------- #

def _safe_now_utc_date() -> pd.Timestamp:
    # Always return tz-aware UTC date (normalized to midnight)
    return pd.Timestamp.now(tz="UTC").normalize()


def _coerce_float(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _ensure_cols(df: pd.DataFrame, cols: List[str]) -> pd.DataFrame:
    for c in cols:
        if c not in df.columns:
            df[c] = np.nan
    return df


def _rank_norm(x: pd.Series) -> pd.Series:
    """
    Rank-normalize to [-1, +1]. NaNs stay NaN.
    """
    s = x.copy()
    mask = s.notna()
    if mask.sum() == 0:
        return s
    ranks = s[mask].rank(method="average")
    n = float(mask.sum())
    rn = (ranks - 0.5) / n  # (0,1]
    rn = (rn - 0.5) * 2.0   # [-1, +1]
    s.loc[mask] = rn
    return s


def _winsorize(x: pd.Series, pct: float) -> pd.Series:
    s = x.copy()
    mask = s.notna()
    if mask.sum() == 0:
        return s
    lo = s[mask].quantile(pct)
    hi = s[mask].quantile(1 - pct)
    s.loc[mask] = s[mask].clip(lower=lo, upper=hi)
    return s


def _linear_trend(ts: pd.Series, ys: pd.Series) -> Optional[float]:
    """
    Simple slope (per day) using numpy polyfit. Returns None if insufficient data.
    """
    if len(ts) < 2 or len(ys) < 2:
        return None
    try:
        x = (ts - ts.min()).dt.days.astype(float)
        y = ys.astype(float)
        mask = y.notna()
        if mask.sum() < 2:
            return None
        b1, b0 = np.polyfit(x[mask], y[mask], 1)  # slope, intercept
        return float(b1)
    except Exception:
        return None


# --------------------------- Main Class --------------------------- #

class EdgeEvaluator:
    """
    Loads historical edge results, computes a composite score with time-decay,
    and aggregates into a ranked per-edge intelligence table.
    """

    REQUIRED_COLS = [
        "edge", "start", "end",
        "total_return_pct", "cagr_pct", "max_drawdown_pct",
        "sharpe", "win_rate_pct", "trades"
    ]

    DATE_COLS = ["start", "end"]

    def __init__(self,
                 db_path_parquet: str = "data/research/edge_results.parquet",
                 db_path_csv: str = "data/research/edge_results.csv",
                 out_dir: str = "data/research",
                 cfg: Optional[EvaluatorConfig] = None):
        self.db_pq = Path(db_path_parquet)
        self.db_csv = Path(db_path_csv)
        self.out_dir = Path(out_dir)
        self.cfg = cfg or EvaluatorConfig()

        self.raw: pd.DataFrame = pd.DataFrame()
        self.scored: pd.DataFrame = pd.DataFrame()
        self.summary: pd.DataFrame = pd.DataFrame()

    # ---------------------- I/O helpers ---------------------- #

    def _read_db(self) -> pd.DataFrame:
        """
        Prefer Parquet. If engine missing or file absent, fall back to CSV.
        """
        if self.db_pq.exists() and self.db_pq.stat().st_size > 0:
            try:
                return pd.read_parquet(self.db_pq)
            except Exception:
                pass
        if self.db_csv.exists() and self.db_csv.stat().st_size > 0:
            try:
                return pd.read_csv(self.db_csv)
            except Exception:
                pass
        return pd.DataFrame()

    def _write_parquet_or_csv(self, df: pd.DataFrame, base_name: str) -> Path:
        """
        Attempt Parquet; fallback to CSV with same base_name.
        """
        self.out_dir.mkdir(parents=True, exist_ok=True)
        pq_path = self.out_dir / f"{base_name}.parquet"
        try:
            df.to_parquet(pq_path, index=False)
            return pq_path
        except Exception:
            csv_path = self.out_dir / f"{base_name}.csv"
            df.to_csv(csv_path, index=False)
            return csv_path

    def _write_json(self, payload: Dict, base_name: str) -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        p = self.out_dir / f"{base_name}.json"
        p.write_text(json.dumps(payload, indent=2))
        return p

    # -------------------- Core processing -------------------- #

    def load(self) -> pd.DataFrame:
        df = self._read_db()
        if df.empty:
            self.raw = df
            return df

        # Ensure required cols exist
        df = _ensure_cols(df, self.REQUIRED_COLS)

        # Parse dates
        for c in self.DATE_COLS:
            if c in df.columns:
                df[c] = pd.to_datetime(df[c], errors="coerce")

        # Coerce numerics
        for c in ["total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "win_rate_pct", "trades"]:
            if c in df.columns:
                df[c] = _coerce_float(df[c])

        # A "completed" date to compute recency; use "end" if present, else now
        if "end" in df.columns:
            df["completed_on"] = df["end"].fillna(df["start"])
        else:
            df["completed_on"] = pd.NaT

        df["completed_on"] = pd.to_datetime(df["completed_on"], errors="coerce", utc=True)
        df.loc[df["completed_on"].isna(), "completed_on"] = _safe_now_utc_date()

        # Drop rows without edge name
        if "edge" in df.columns:
            df["edge"] = df["edge"].astype(str)
            df = df[df["edge"].str.len() > 0]

        self.raw = df.reset_index(drop=True)
        return self.raw

    def score_rows(self) -> pd.DataFrame:
        """
        Compute per-run normalized metrics and a composite score with time-decay.
        """
        df = self.raw.copy()
        if df.empty:
            self.scored = df
            return df

        # Normalization helpers
        def norm_pos(x: pd.Series) -> pd.Series:
            # Higher is better
            if self.cfg.rank_normalize:
                return _rank_norm(x)
            s = _winsorize(x, self.cfg.winsor_pct)
            mu, sd = s.mean(skipna=True), s.std(skipna=True)
            return (s - mu) / (sd if sd and sd > 0 else 1.0)

        def norm_neg(x: pd.Series) -> pd.Series:
            # Lower (less negative drawdown) is better -> invert
            return -norm_pos(x)

        # Build normalized columns
        df["norm_sharpe"] = norm_pos(df["sharpe"])
        df["norm_cagr"] = norm_pos(df["cagr_pct"])
        df["norm_winrate"] = norm_pos(df["win_rate_pct"])
        df["norm_mdd"] = norm_neg(df["max_drawdown_pct"])

        # Time decay weights (half-life -> lambda)
        today = _safe_now_utc_date()
        age_days = (today - pd.to_datetime(df["completed_on"])).dt.days.astype(float)
        lam = math.log(2.0) / max(self.cfg.decay_half_life_days, 1e-9)
        df["time_weight"] = np.exp(-lam * np.clip(age_days, 0.0, 36500.0))

        # Composite score before weighting
        # If any component is NaN, treat as 0 contribution (neutral) to keep rows usable.
        def nz(s: pd.Series) -> pd.Series:
            return s.fillna(0.0)

        num = (
            self.cfg.w_sharpe * nz(df["norm_sharpe"]) +
            self.cfg.w_cagr * nz(df["norm_cagr"]) +
            self.cfg.w_winrate * nz(df["norm_winrate"]) +
            self.cfg.w_mdd * nz(df["norm_mdd"])
        )
        denom = (abs(self.cfg.w_sharpe) + abs(self.cfg.w_cagr) +
                 abs(self.cfg.w_winrate) + abs(self.cfg.w_mdd))
        base_score = num / (denom if denom > 0 else 1.0)

        # Apply time weight
        df["score"] = base_score * df["time_weight"]

        # Keep a clean scored frame
        keep_cols = [
            "edge", "start", "end", "completed_on",
            "total_return_pct", "cagr_pct", "max_drawdown_pct",
            "sharpe", "win_rate_pct", "trades",
            "norm_sharpe", "norm_cagr", "norm_winrate", "norm_mdd",
            "time_weight", "score",
        ]
        self.scored = df[keep_cols].sort_values(["edge", "completed_on"]).reset_index(drop=True)
        return self.scored

    def summarize_edges(self) -> pd.DataFrame:
        """
        Aggregate per-edge: weighted means, stability (score std), and recent trend.
        Produces a ranked table for selection downstream.
        """
        df = self.scored.copy()
        if df.empty:
            self.summary = pd.DataFrame()
            return self.summary

        groups = []
        recent_cut = _safe_now_utc_date() - pd.Timedelta(days=int(self.cfg.recent_days))

        for edge, g in df.groupby("edge", dropna=False):
            g = g.sort_values("completed_on")
            n = len(g)

            # Weighted means
            w = g["time_weight"].fillna(0.0)
            wsum = float(w.sum()) if float(w.sum()) > 0 else 1.0

            def wmean(x: pd.Series) -> float:
                return float((x.fillna(0.0) * w).sum() / wsum)

            # Stability: standard deviation of scores (lower is more stable)
            stability = float(g["score"].std(skipna=True)) if n >= self.cfg.min_rows_for_stats else np.nan

            # Recent trend in score (slope per day)
            recent_g = g[g["completed_on"] >= recent_cut]
            trend = _linear_trend(recent_g["completed_on"], recent_g["score"]) if len(recent_g) >= 2 else None

            # Diagnostics
            row = {
                "edge": edge,
                "rows": int(n),
                "mean_score": wmean(g["score"]),
                "mean_sharpe": wmean(g["sharpe"]),
                "mean_cagr_pct": wmean(g["cagr_pct"]),
                "mean_win_rate_pct": wmean(g["win_rate_pct"]),
                "mean_max_dd_pct": wmean(g["max_drawdown_pct"]),
                "stability_sd": stability,
                "recent_trend_per_day": trend if trend is not None else np.nan,
                "last_completed_on": g["completed_on"].max(),
                "total_trades": int(g["trades"].fillna(0).sum()),
            }
            groups.append(row)

        out = pd.DataFrame(groups)
        if out.empty:
            self.summary = out
            return out

        # Rank by mean_score desc, then by stability (ascending), then recency
        out = out.sort_values(
            by=["mean_score", "stability_sd", "last_completed_on"],
            ascending=[False, True, False]
        ).reset_index(drop=True)

        self.summary = out
        return self.summary

    # --------------------- Export & Recommendations --------------------- #

    def export(self) -> Dict[str, Path]:
        paths: Dict[str, Path] = {}
        if not self.summary.empty:
            paths["intelligence_table"] = self._write_parquet_or_csv(self.summary, "edge_intelligence")

            # Build a compact JSON summary for the dashboard/governor
            head = self.summary.head(50).copy()
            head["last_completed_on"] = head["last_completed_on"].astype(str)
            summary_payload = {
                "generated_at": str(_safe_now_utc_date()),
                "recent_days": int(self.cfg.recent_days),
                "edges": head.to_dict(orient="records"),
            }
            paths["summary_json"] = self._write_json(summary_payload, "edge_intelligence_summary")

            # Normalized 0..1 recommendations (for governor weights)
            # Map mean_score to [0,1] via min-max over available edges; stable edges get a small boost
            s = self.summary["mean_score"].fillna(0.0)
            mn, mx = float(s.min()), float(s.max())
            span = (mx - mn) if (mx - mn) > 1e-12 else 1.0
            base = (s - mn) / span
            # Optional stability boost: lower sd => add up to +0.05
            sd = self.summary["stability_sd"].fillna(sd := self.summary["stability_sd"].median(skipna=True) if not self.summary["stability_sd"].isna().all() else 0.0)
            sd_norm = 1.0 - (sd / (sd.quantile(0.9) if sd.quantile(0.9) > 0 else 1.0)).clip(0.0, 1.0)
            weights = (0.95 * base + 0.05 * sd_norm).clip(0.0, 1.0)

            rec = {
                "generated_at": str(_safe_now_utc_date()),
                "weights": {e: float(w) for e, w in zip(self.summary["edge"], weights)}
            }
            paths["recommendations_json"] = self._write_json(rec, "edge_recommendations")

        return paths

    # ------------------------ Orchestrator ------------------------ #

    def run(self) -> Dict[str, Path]:
        self.load()
        self.score_rows()
        self.summarize_edges()
        return self.export()