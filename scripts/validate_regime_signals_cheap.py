"""validate_regime_signals_cheap — feature-level cheap-input validation.

Tests whether VIX term structure (yfinance) and CBOE P/C ratio carry
LEADING information for forward SPY drawdowns, BEFORE any HMM training.

This is a feature-level analog of `validate_regime_signals.py`. We do
not train any HMM. We compute candidate term-structure / P/C features
directly and run them through the AUC + conditional-drawdown +
coincident-vs-leading methodology used in the 2026-05-06 baseline.

Per the dispatch (5-5-26_schwab-plan-reflection.md), this answers the
go/no-go question: can the regime panel rebuild ship without paid
options data integration?

Outputs:
  - AUC of each feature vs P(forward 20d SPY dd <= -5%) [+ 5d, 60d]
  - Pearson correlation vs trailing 20d return AND vs forward 20d return
    (the coincident-vs-leading test — leading => |fwd| > |trail|)
  - Conditional mean fwd dd in top-decile vs unconditional baseline
  - Markdown + JSON verdict written to docs/Measurements/2026-05/

Read-only: no governor writes, no production runs, no full backtests.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


# ----------------------------------------------------------------------
# Data loaders (mirrored from validate_regime_signals.py — kept local so
# this script can run without instantiating the HMM model path)
# ----------------------------------------------------------------------
def load_spy() -> pd.Series:
    p = REPO / "data" / "processed" / "SPY_1d.csv"
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    s = df["Close"].astype(float).sort_index()
    s.index = pd.to_datetime(s.index).tz_localize(None) if s.index.tz is not None else pd.to_datetime(s.index)
    return s


def load_macro_series(series_id: str) -> Optional[pd.Series]:
    p = REPO / "data" / "macro" / f"{series_id}.parquet"
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    if "value" in df.columns:
        s = df["value"].dropna()
    else:
        numeric = df.select_dtypes(include=[np.number]).columns
        if len(numeric) == 0:
            return None
        s = df[numeric[0]].dropna()
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


# ----------------------------------------------------------------------
# Forward target construction (identical semantics to baseline script)
# ----------------------------------------------------------------------
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


# ----------------------------------------------------------------------
# AUC (Mann-Whitney U with tie handling)
# ----------------------------------------------------------------------
def auc_score(scores: np.ndarray, labels: np.ndarray) -> float:
    mask = ~(np.isnan(scores) | np.isnan(labels))
    s = scores[mask]
    y = labels[mask].astype(int)
    if len(s) == 0 or y.sum() == 0 or y.sum() == len(y):
        return float("nan")
    order = np.argsort(s)
    ranks = np.empty(len(s), dtype=np.float64)
    sorted_s = s[order]
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
    return float((sum_pos_ranks - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


# ----------------------------------------------------------------------
# Feature builders
# ----------------------------------------------------------------------
def build_vix_term_features(daily_idx: pd.DatetimeIndex) -> pd.DataFrame:
    """Compute VIX term-structure slopes on the daily index.

    Slopes are LOG ratios so they are sign-symmetric and unitless:
      vix_term_slope_9_30   = log(VIX9D / VIX)        (- = backwardation)
      vix_term_slope_30_3m  = log(VIX  / VIX3M)       (- = short backwardation)
      vix_term_slope_3m_6m  = log(VIX3M / VIX6M)      (- = mid backwardation)
      vix_term_slope_9_6m   = log(VIX9D / VIX6M)      (full term structure)

    A leading feature should have |corr_vs_forward_ret| > |corr_vs_trailing_ret|.
    Backwardation (negative slope) is the academic crisis signature, so
    a leading feature should have NEGATIVE Pearson with forward return
    (more backwardation now → smaller forward return) and a |fwd|/|trail|
    ratio > 1.
    """
    v9d = load_macro_series("VIX9D")
    v30 = load_macro_series("VIX")
    v3m = load_macro_series("VIX3M")
    v6m = load_macro_series("VIX6M")

    out = pd.DataFrame(index=daily_idx)
    if v9d is None or v30 is None or v3m is None or v6m is None:
        for c in ("vix_term_slope_9_30", "vix_term_slope_30_3m",
                  "vix_term_slope_3m_6m", "vix_term_slope_9_6m"):
            out[c] = np.nan
        return out

    v9d_a = v9d.reindex(daily_idx, method="ffill")
    v30_a = v30.reindex(daily_idx, method="ffill")
    v3m_a = v3m.reindex(daily_idx, method="ffill")
    v6m_a = v6m.reindex(daily_idx, method="ffill")

    # Guard against zero/negative (shouldn't happen for VIX series)
    safe = lambda s: s.where(s > 0)
    out["vix_term_slope_9_30"] = np.log(safe(v9d_a) / safe(v30_a))
    out["vix_term_slope_30_3m"] = np.log(safe(v30_a) / safe(v3m_a))
    out["vix_term_slope_3m_6m"] = np.log(safe(v3m_a) / safe(v6m_a))
    out["vix_term_slope_9_6m"] = np.log(safe(v9d_a) / safe(v6m_a))
    return out


def build_pc_ratio_features(daily_idx: pd.DatetimeIndex) -> Tuple[pd.DataFrame, str]:
    """Attempt to load CBOE total P/C ratio from data/macro/cboe_pc_ratio.parquet.

    If the data is missing, return an empty DataFrame plus a status note.
    The dispatch's contingency: "If the CBOE API is unreachable, document
    the gap." We honor that here — DO NOT silently invent a proxy that
    might mislead the verdict.
    """
    pc = load_macro_series("cboe_pc_ratio")
    if pc is None or pc.empty:
        return pd.DataFrame(index=daily_idx), "missing"

    out = pd.DataFrame(index=daily_idx)
    pc_a = pc.reindex(daily_idx, method="ffill")
    out["cboe_pc_ratio"] = pc_a
    mean60 = pc_a.rolling(60, min_periods=60).mean()
    std60 = pc_a.rolling(60, min_periods=60).std(ddof=1)
    out["cboe_pc_zscore_60d"] = (pc_a - mean60) / std60.replace(0.0, np.nan)
    return out, "ok"


# ----------------------------------------------------------------------
# Top-decile conditional drawdown
# ----------------------------------------------------------------------
def conditional_top_decile(
    feature: pd.Series,
    fdd: pd.Series,
    direction: str,  # "low_decile" or "high_decile" or "abs_high"
) -> Dict:
    aligned = pd.concat([feature, fdd], axis=1).dropna()
    if len(aligned) == 0:
        return {"n": 0}
    feat = aligned.iloc[:, 0]
    f = aligned.iloc[:, 1]
    if direction == "low_decile":
        thresh = feat.quantile(0.10)
        mask = feat <= thresh
        regime_label = f"feature in bottom decile (<= {thresh:.4f})"
    elif direction == "high_decile":
        thresh = feat.quantile(0.90)
        mask = feat >= thresh
        regime_label = f"feature in top decile (>= {thresh:.4f})"
    else:  # abs_high
        absf = feat.abs()
        thresh = absf.quantile(0.90)
        mask = absf >= thresh
        regime_label = f"|feature| in top decile (>= {thresh:.4f})"
    cond = f[mask]
    return {
        "regime_label": regime_label,
        "n_in_regime": int(mask.sum()),
        "n_total": int(len(aligned)),
        "pct_in_regime": float(mask.mean()),
        "mean_fwd_dd_in_regime": float(cond.mean()) if len(cond) else float("nan"),
        "mean_fwd_dd_unconditional": float(f.mean()),
        "median_fwd_dd_in_regime": float(cond.median()) if len(cond) else float("nan"),
        "p10_fwd_dd_in_regime": float(cond.quantile(0.10)) if len(cond) else float("nan"),
        "p10_fwd_dd_unconditional": float(f.quantile(0.10)),
    }


# ----------------------------------------------------------------------
# Coincident-vs-leading test
# ----------------------------------------------------------------------
def coincident_leading_test(
    feature: pd.Series, spy: pd.Series, horizon: int
) -> Dict:
    trail = spy / spy.shift(horizon) - 1.0
    fwd = spy.shift(-horizon) / spy - 1.0
    df = pd.DataFrame({"feat": feature, "trail": trail, "fwd": fwd}).dropna()
    if len(df) == 0:
        return {
            "pearson_vs_trailing_ret": float("nan"),
            "pearson_vs_forward_ret": float("nan"),
            "abs_fwd_over_trail": float("nan"),
            "is_leading": False,
            "n": 0,
        }
    r_trail = float(df["feat"].corr(df["trail"]))
    r_fwd = float(df["feat"].corr(df["fwd"]))
    ratio = abs(r_fwd) / max(abs(r_trail), 1e-9)
    return {
        "pearson_vs_trailing_ret": r_trail,
        "pearson_vs_forward_ret": r_fwd,
        "abs_fwd_over_trail": ratio,
        "is_leading": ratio > 1.0,
        "n": int(len(df)),
    }


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default="2025-04-30")
    ap.add_argument("--horizon", type=int, default=20)
    ap.add_argument("--dd-threshold", type=float, default=-0.05)
    ap.add_argument(
        "--out-json",
        default=str(REPO / "docs" / "Measurements" / "2026-05" / "regime_signal_validation_cheap_2026_05_06.json"),
    )
    args = ap.parse_args()

    print(f"[info] window: {args.start} -> {args.end}, horizon={args.horizon}d")
    print(f"[info] dd threshold for binary target: {args.dd_threshold:+.0%}")

    # ---- Load SPY and forward targets ----
    spy = load_spy()
    spy = spy.loc[(spy.index >= pd.Timestamp(args.start)) & (spy.index <= pd.Timestamp(args.end))]
    daily_idx = spy.index

    fdd_5 = forward_drawdown(spy, 5)
    fdd_20 = forward_drawdown(spy, args.horizon)
    fdd_60 = forward_drawdown(spy, 60)

    target_5 = (fdd_5 <= args.dd_threshold).astype(float); target_5[fdd_5.isna()] = np.nan
    target_20 = (fdd_20 <= args.dd_threshold).astype(float); target_20[fdd_20.isna()] = np.nan
    target_60 = (fdd_60 <= args.dd_threshold).astype(float); target_60[fdd_60.isna()] = np.nan
    target_3 = (fdd_20 <= -0.03).astype(float); target_3[fdd_20.isna()] = np.nan

    base_rate_20 = float(target_20.mean())
    base_rate_5 = float(target_5.mean())
    base_rate_60 = float(target_60.mean())
    print(f"[info] uncond rate fwd dd <= {args.dd_threshold:+.0%}: "
          f"5d={base_rate_5:.3f}, 20d={base_rate_20:.3f}, 60d={base_rate_60:.3f}")
    print(f"[info] uncond mean 20d fwd dd: {fdd_20.mean():+.4f}")

    # ---- Build candidate features ----
    vix_term = build_vix_term_features(daily_idx)
    pc_features, pc_status = build_pc_ratio_features(daily_idx)

    print(f"\n[info] VIX-term features built: {list(vix_term.columns)}")
    for c in vix_term.columns:
        n_ok = int((~vix_term[c].isna()).sum())
        print(f"        {c:30s} non-null={n_ok}/{len(daily_idx)}")
    print(f"[info] CBOE P/C status: {pc_status}")
    if pc_status == "ok":
        for c in pc_features.columns:
            n_ok = int((~pc_features[c].isna()).sum())
            print(f"        {c:30s} non-null={n_ok}/{len(daily_idx)}")
    else:
        print(f"        (no data/macro/cboe_pc_ratio.parquet — see verdict for "
              f"upstream-source notes)")

    # ---- Compose feature panel for analysis ----
    features = pd.concat([vix_term, pc_features], axis=1)

    # ---- AUC by feature × horizon ----
    print(f"\n=== AUC vs forward drawdown <= {args.dd_threshold:+.0%} ===")
    print(f"{'feature':32s} {'5d':>8s} {'20d':>8s} {'60d':>8s} {'20d_3%':>8s}")
    auc_block: Dict[str, Dict[str, float]] = {}
    for feat in features.columns:
        x = features[feat].values
        a5 = auc_score(x, target_5.values)
        a20 = auc_score(x, target_20.values)
        a60 = auc_score(x, target_60.values)
        a3 = auc_score(x, target_3.values)
        auc_block[feat] = {"5d_5pct": a5, "20d_5pct": a20, "60d_5pct": a60, "20d_3pct": a3}
        print(f"{feat:32s} {a5:>8.4f} {a20:>8.4f} {a60:>8.4f} {a3:>8.4f}")
        # Negative AUC interpretation: 1-AUC for the inverted feature
        # (when high feature value → less drawdown)
        if a20 < 0.5:
            print(f"{'  (feature inverted: 1-AUC)':32s} {1-a5:>8.4f} {1-a20:>8.4f} {1-a60:>8.4f} {1-a3:>8.4f}")

    # ---- Coincident-vs-leading test ----
    print(f"\n=== Coincident-vs-leading test (Pearson, 20d) ===")
    print(f"{'feature':32s} {'corr_trail':>12s} {'corr_fwd':>12s} {'|fwd|/|trail|':>14s} {'leading?':>10s}")
    coinc_block: Dict[str, Dict] = {}
    for feat in features.columns:
        coinc_block[feat] = coincident_leading_test(features[feat], spy, args.horizon)
        v = coinc_block[feat]
        is_lead = "YES" if v["is_leading"] else "no"
        print(f"{feat:32s} {v['pearson_vs_trailing_ret']:>+12.4f} "
              f"{v['pearson_vs_forward_ret']:>+12.4f} "
              f"{v['abs_fwd_over_trail']:>14.3f} {is_lead:>10s}")

    # ---- Conditional drawdown by top-decile ----
    print(f"\n=== Conditional 20d forward drawdown by feature decile ===")
    print(f"  unconditional baseline: mean_fwd_dd={fdd_20.mean():+.4f}, "
          f"base_rate={base_rate_20:.3f}, p10={fdd_20.quantile(0.10):+.4f}")
    cond_block: Dict[str, Dict] = {}
    for feat in features.columns:
        # For backwardation/negative-slope features, low decile = stress
        # For absolute-magnitude features (abs_high), |feature| top decile = stress
        s = features[feat]
        # Economically: log(near / far) > 0 = backwardation = canonical
        # crisis signature. So HIGH decile of log-slope = stress regime.
        # (My earlier comment was inverted; the academic crisis sign is
        # POSITIVE log slope = near-term implied vol > far-term.)
        if feat.startswith("vix_term_slope"):
            cond = conditional_top_decile(s, fdd_20, "high_decile")
        elif feat == "cboe_pc_ratio":
            # Higher P/C = more puts = bearish signal
            cond = conditional_top_decile(s, fdd_20, "high_decile")
        elif feat == "cboe_pc_zscore_60d":
            cond = conditional_top_decile(s, fdd_20, "high_decile")
        else:
            cond = conditional_top_decile(s, fdd_20, "abs_high")
        cond_block[feat] = cond
        if cond.get("n_in_regime", 0) == 0:
            print(f"  {feat:32s} (no data)")
            continue
        print(f"  {feat:32s} N={cond['n_in_regime']:4d} "
              f"({cond['pct_in_regime']*100:5.1f}%) "
              f"mean_fwd_dd={cond['mean_fwd_dd_in_regime']:+.4f} "
              f"p10={cond['p10_fwd_dd_in_regime']:+.4f}")

    # ---- IS / OOS split (2025 Jan-Apr is the canonical OOS slice) ----
    is_mask = (daily_idx >= pd.Timestamp("2021-01-01")) & (daily_idx <= pd.Timestamp("2024-12-31"))
    oos_mask = (daily_idx >= pd.Timestamp("2025-01-01"))
    print(f"\n=== In-sample (2021-2024) vs OOS (2025 Jan-Apr) AUC ===")
    print(f"  in-sample N={int(is_mask.sum())}, OOS N={int(oos_mask.sum())}")
    print(f"  OOS dd<=-5% positives: {int(target_20[oos_mask].sum())}")
    print(f"  OOS dd<=-3% positives: {int(target_3[oos_mask].sum())}")
    print(f"{'feature':32s} {'IS 20d_5%':>10s} {'IS 20d_3%':>10s} {'OOS 20d_3%':>11s}")
    is_oos_block: Dict[str, Dict] = {}
    for feat in features.columns:
        x = features[feat].values
        is_5 = auc_score(x[is_mask], target_20.values[is_mask])
        is_3 = auc_score(x[is_mask], target_3.values[is_mask])
        oos_3 = auc_score(x[oos_mask], target_3.values[oos_mask])
        is_oos_block[feat] = {"is_20d_5pct": is_5, "is_20d_3pct": is_3, "oos_20d_3pct": oos_3}
        print(f"{feat:32s} {is_5:>10.4f} {is_3:>10.4f} {oos_3:>11.4f}")

    # ---- Hit rate / FPR at the anchor threshold ----
    print(f"\n=== Hit rate / FPR (firing = top decile, target: 20d fwd dd <= -5%) ===")
    print(f"  base_rate={base_rate_20:.3f}")
    print(f"  {'feature':32s} {'TPR':>6s} {'FPR':>6s} {'prec':>6s} {'lift':>7s}")
    hit_fpr_block: Dict[str, Dict] = {}
    for feat in features.columns:
        s = features[feat]
        # Backwardation (slope > 0) = stress, so fire when in HIGH decile
        if feat.startswith("vix_term_slope"):
            thresh = s.quantile(0.90)
            fired = (s >= thresh)
        elif feat in ("cboe_pc_ratio", "cboe_pc_zscore_60d"):
            thresh = s.quantile(0.90)
            fired = (s >= thresh)
        else:
            absf = s.abs()
            thresh = absf.quantile(0.90)
            fired = (absf >= thresh)
        # align
        df = pd.concat([fired.astype(float).rename("fired"), target_20.rename("y")], axis=1).dropna()
        if len(df) == 0:
            continue
        tp = int(((df["fired"] == 1) & (df["y"] == 1)).sum())
        fp = int(((df["fired"] == 1) & (df["y"] == 0)).sum())
        fn = int(((df["fired"] == 0) & (df["y"] == 1)).sum())
        tn = int(((df["fired"] == 0) & (df["y"] == 0)).sum())
        tpr = tp / (tp + fn) if (tp + fn) > 0 else float("nan")
        fpr = fp / (fp + tn) if (fp + tn) > 0 else float("nan")
        prec = tp / (tp + fp) if (tp + fp) > 0 else float("nan")
        lift = (prec - base_rate_20) if not np.isnan(prec) else float("nan")
        hit_fpr_block[feat] = {
            "TPR": tpr, "FPR": fpr, "precision": prec, "lift_over_base": lift,
            "TP": tp, "FP": fp, "FN": fn, "TN": tn, "threshold": float(thresh),
        }
        print(f"  {feat:32s} {tpr:>6.3f} {fpr:>6.3f} {prec:>6.3f} {lift:>+7.3f}")

    # ---- Verdict logic ----
    # Branch 1: at least one feature has 20d 5% AUC > 0.55 AND |fwd| > |trail| (Pearson)
    # Branch 2: borderline (AUC 0.50-0.55 OR ambiguous)
    # Branch 3: nothing leads
    leading_features = []
    borderline_features = []
    for feat in features.columns:
        # AUC: directional. We accept either side > 0.55 (an inverted leading
        # feature is still a leading feature if 1-AUC > 0.55).
        a20 = auc_block[feat]["20d_5pct"]
        if pd.isna(a20):
            continue
        a20_eff = max(a20, 1 - a20)
        is_lead_corr = coinc_block[feat]["is_leading"]
        if a20_eff > 0.55 and is_lead_corr:
            leading_features.append(feat)
        elif a20_eff >= 0.50 and a20_eff <= 0.55:
            borderline_features.append(feat)

    if leading_features:
        verdict = "Branch 1 — at least one feature carries leading information"
        verdict_short = "branch_1_leading"
    elif borderline_features:
        verdict = "Branch 2 — borderline; one more cheap probe before Schwab"
        verdict_short = "branch_2_borderline"
    else:
        verdict = "Branch 3 — neither cheap source is leading; Schwab IV skew is next"
        verdict_short = "branch_3_not_leading"

    print(f"\n=== VERDICT ===")
    print(f"  {verdict}")
    print(f"  leading features (AUC>0.55 AND |fwd|>|trail|): {leading_features}")
    print(f"  borderline features (0.50<=AUC<=0.55): {borderline_features}")

    # ---- Persist ----
    results: Dict = {
        "args": vars(args),
        "window_n_days": int(len(daily_idx)),
        "base_rate_dd_5d": base_rate_5,
        "base_rate_dd_20d": base_rate_20,
        "base_rate_dd_60d": base_rate_60,
        "uncond_mean_fwd_dd_20d": float(fdd_20.mean()),
        "auc_by_feature_horizon": auc_block,
        "coincident_leading_by_feature": coinc_block,
        "conditional_top_decile_by_feature": cond_block,
        "is_oos_auc_by_feature": is_oos_block,
        "hit_fpr_by_feature_top_decile": hit_fpr_block,
        "pc_status": pc_status,
        "leading_features": leading_features,
        "borderline_features": borderline_features,
        "verdict": verdict,
        "verdict_short": verdict_short,
    }
    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[info] wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
