"""
validate_minimal_hmm — read-only validation of E-rebuild phase-1 variants.

For each of variants A/B/C, computes 3 horizons (5d/20d/60d) of:
  - AUC vs forward SPY drawdown ≤ -5%
  - Pearson correlation of p_stressed_or_crisis vs forward N-d SPY return
  - Pearson correlation of p_stressed_or_crisis vs TRAILING N-d SPY return
  - Coincident-vs-leading flip: |fwd_corr| > |trail_corr|?
  - Per-state forward drawdown breakdown (benign/stressed/crisis)

Verdict per (variant, horizon) cell:
  LEADING       — AUC > 0.55 AND |fwd_corr| > |trail_corr|
  COINCIDENT    — AUC > 0.55 BUT |fwd_corr| <= |trail_corr|
  INDETERMINATE — AUC <= 0.55

Output:
  data/research/hmm_minimal_validation_2026_05.json   — full table
  stdout                                              — readable summary

Reads the regime states written by scripts/train_minimal_hmm.py from
data/macro/minimal_hmm_states_<variant>.parquet — does NOT retrain.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# Reused from validate_regime_signals.py (kept self-contained here to
# avoid cross-script churn).
def auc_score(scores: np.ndarray, labels: np.ndarray) -> float:
    mask = ~(np.isnan(scores) | np.isnan(labels))
    s = scores[mask]
    y = labels[mask].astype(int)
    if len(s) == 0 or y.sum() == 0 or y.sum() == len(y):
        return float("nan")
    order = np.argsort(s)
    sorted_s = s[order]
    ranks = np.empty(len(s), dtype=np.float64)
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        ranks[order[i:j + 1]] = avg_rank
        i = j + 1
    n_pos = y.sum()
    n_neg = len(y) - n_pos
    sum_pos_ranks = ranks[y == 1].sum()
    auc = (sum_pos_ranks - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    return float(auc)


def forward_drawdown(price: pd.Series, horizon: int) -> pd.Series:
    rolling_min = price.shift(-1).rolling(horizon, min_periods=1).min()
    out = (rolling_min - price) / price
    out.iloc[-horizon:] = np.nan
    return out


def forward_return(price: pd.Series, horizon: int) -> pd.Series:
    fwd = price.shift(-horizon)
    out = (fwd - price) / price
    out.iloc[-horizon:] = np.nan
    return out


def trailing_return(price: pd.Series, horizon: int) -> pd.Series:
    return price.pct_change(horizon)


def load_spy() -> pd.Series:
    p = ROOT / "data" / "processed" / "SPY_1d.csv"
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    s = df["Close"].astype(float).sort_index()
    s.index = pd.to_datetime(s.index)
    if s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    return s


def load_states(variant: str) -> pd.DataFrame:
    p = ROOT / "data" / "macro" / f"minimal_hmm_states_{variant}.parquet"
    if not p.exists():
        raise FileNotFoundError(
            f"states file missing: {p}. Train first: "
            f"python scripts/train_minimal_hmm.py --variant {variant}"
        )
    df = pd.read_parquet(p)
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df


def per_state_dd_breakdown(
    states: pd.Series, fdd: pd.Series
) -> Dict[str, Dict[str, float]]:
    common = states.dropna().index.intersection(fdd.dropna().index)
    if len(common) == 0:
        return {}
    s = states.loc[common]
    f = fdd.loc[common]
    out: Dict[str, Dict[str, float]] = {}
    for label in s.unique():
        mask = (s == label)
        sub = f[mask]
        out[str(label)] = {
            "n_days": int(mask.sum()),
            "mean_fwd_dd": float(sub.mean()) if len(sub) else float("nan"),
            "median_fwd_dd": float(sub.median()) if len(sub) else float("nan"),
            "p10_fwd_dd": float(sub.quantile(0.10)) if len(sub) else float("nan"),
        }
    out["_unconditional"] = {
        "n_days": int(len(f)),
        "mean_fwd_dd": float(f.mean()),
        "median_fwd_dd": float(f.median()),
        "p10_fwd_dd": float(f.quantile(0.10)),
    }
    return out


def evaluate_variant(
    variant: str,
    spy: pd.Series,
    test_start: str,
    test_end: str,
    horizons: List[int],
    dd_threshold: float,
) -> Dict:
    states_df = load_states(variant)
    # p_stress_or_crisis = 1 - p_benign (continuous score)
    if "benign" in states_df.columns:
        p_risk = 1.0 - states_df["benign"]
    else:
        # Fallback: sum non-benign states
        non_benign = [c for c in states_df.columns if c not in ("regime", "benign")]
        p_risk = states_df[non_benign].sum(axis=1)

    # Restrict scoring to test window (out-of-sample only)
    test_mask = (states_df.index >= pd.Timestamp(test_start)) & \
                (states_df.index <= pd.Timestamp(test_end))
    p_risk_oos = p_risk.loc[test_mask]
    states_oos = states_df["regime"].loc[test_mask]

    # SPY in test window
    spy_oos = spy.loc[(spy.index >= pd.Timestamp(test_start)) &
                      (spy.index <= pd.Timestamp(test_end))]

    out: Dict = {
        "variant": variant,
        "test_start": test_start,
        "test_end": test_end,
        "n_oos_days": int(len(p_risk_oos)),
        "by_horizon": {},
    }

    for h in horizons:
        fdd = forward_drawdown(spy_oos, h)
        fret = forward_return(spy_oos, h)
        tret = trailing_return(spy_oos, h)
        binary_dd = (fdd <= dd_threshold).astype(float)
        # Mask out NaN forward windows (last h bars)
        binary_dd.iloc[-h:] = np.nan

        # Align signals to SPY's exact dates
        common = p_risk_oos.index.intersection(spy_oos.index)
        p_aligned = p_risk_oos.loc[common]
        states_aligned = states_oos.loc[common]
        fdd_aligned = fdd.loc[common]
        fret_aligned = fret.loc[common]
        tret_aligned = tret.loc[common]
        bin_aligned = binary_dd.loc[common]

        auc = auc_score(p_aligned.values, bin_aligned.values)

        # Pearson corrs (ignore NaN windows)
        f_mask = ~(p_aligned.isna() | fret_aligned.isna())
        t_mask = ~(p_aligned.isna() | tret_aligned.isna())
        fwd_corr = float(p_aligned[f_mask].corr(fret_aligned[f_mask])) \
            if f_mask.sum() > 5 else float("nan")
        trail_corr = float(p_aligned[t_mask].corr(tret_aligned[t_mask])) \
            if t_mask.sum() > 5 else float("nan")

        # Verdict
        if not (auc > 0.55):
            verdict = "INDETERMINATE"
        else:
            if not np.isnan(fwd_corr) and not np.isnan(trail_corr) and \
               abs(fwd_corr) > abs(trail_corr):
                verdict = "LEADING"
            else:
                verdict = "COINCIDENT"

        breakdown = per_state_dd_breakdown(states_aligned, fdd_aligned)

        out["by_horizon"][str(h)] = {
            "horizon_days": h,
            "auc_p_risk_vs_fwd_dd": auc,
            "n_pos_dd_events": int(bin_aligned.fillna(0).sum()),
            "pearson_fwd_ret": fwd_corr,
            "pearson_trail_ret": trail_corr,
            "leading_flip": (
                bool(abs(fwd_corr) > abs(trail_corr))
                if not np.isnan(fwd_corr) and not np.isnan(trail_corr)
                else None
            ),
            "verdict": verdict,
            "per_state_breakdown": breakdown,
        }

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-start", default="2025-01-01")
    ap.add_argument("--test-end", default="2025-04-30")
    ap.add_argument("--horizons", default="5,20,60",
                    help="Comma-separated forward-drawdown horizons in trading days")
    ap.add_argument("--dd-threshold", type=float, default=-0.05)
    ap.add_argument(
        "--out-json",
        default=str(ROOT / "data" / "research" / "hmm_minimal_validation_2026_05.json"),
    )
    args = ap.parse_args()

    horizons = [int(h.strip()) for h in args.horizons.split(",") if h.strip()]
    spy = load_spy()
    results: Dict[str, Dict] = {
        "test_start": args.test_start,
        "test_end": args.test_end,
        "horizons": horizons,
        "dd_threshold": args.dd_threshold,
        "variants": {},
    }
    for variant in ("A", "B", "C"):
        print(f"\n=== Validating Variant {variant} ===")
        r = evaluate_variant(
            variant, spy, args.test_start, args.test_end,
            horizons, args.dd_threshold,
        )
        results["variants"][variant] = r
        for h_str, cell in r["by_horizon"].items():
            print(f"  h={h_str}d  AUC={cell['auc_p_risk_vs_fwd_dd']:.3f} "
                  f"events={cell['n_pos_dd_events']:3d}  "
                  f"corr_fwd={cell['pearson_fwd_ret']:+.3f}  "
                  f"corr_trail={cell['pearson_trail_ret']:+.3f}  "
                  f"verdict={cell['verdict']}")

    out_p = Path(args.out_json)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    out_p.write_text(json.dumps(results, indent=2))
    print(f"\n[VALIDATION] wrote {out_p}")

    # Final summary table
    print("\n=== SUMMARY: AUC table (variant × horizon) ===")
    print(f"{'Variant':10s}  " + "  ".join(f"{h:>6d}d" for h in horizons))
    for v in ("A", "B", "C"):
        cells = results["variants"][v]["by_horizon"]
        row = "  ".join(f"{cells[str(h)]['auc_p_risk_vs_fwd_dd']:>6.3f} " for h in horizons)
        print(f"{v:10s}  {row}")

    print("\n=== SUMMARY: leading-flip table ===")
    print(f"{'Variant':10s}  " + "  ".join(f"{h:>6d}d" for h in horizons))
    for v in ("A", "B", "C"):
        cells = results["variants"][v]["by_horizon"]
        row = "  ".join(
            f"  {'L' if cells[str(h)]['leading_flip'] else 'C' if cells[str(h)]['leading_flip'] is False else '?'}    "
            for h in horizons
        )
        print(f"{v:10s}  {row}")

    print("\n=== SUMMARY: verdicts ===")
    for v in ("A", "B", "C"):
        cells = results["variants"][v]["by_horizon"]
        verdicts = [cells[str(h)]["verdict"] for h in horizons]
        print(f"  Variant {v}: {dict(zip(horizons, verdicts))}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
