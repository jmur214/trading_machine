"""validate_regime_signals_vix_term — slice-1 panel-rebuild validation.

Same harness as `scripts/validate_regime_signals.py`, but loads the
VIX-term-structure HMM (`hmm_3state_vix_term_v1.pkl`) and feeds it the
extended feature panel (FEATURE_COLUMNS + VIX_TERM_FEATURES). All other
metrics, conditional drawdown analysis, hit-rate / FPR, lead-time, and
in-sample/OOS splits are identical so the new AUC is an apples-to-apples
delta vs the 2026-05-06 baseline.

Output JSON sits in `docs/Measurements/2026-05/` with a `_vix_term`
suffix so it doesn't overwrite the baseline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engines.engine_e_regime.hmm_classifier import HMMRegimeClassifier  # noqa: E402
from engines.engine_e_regime.macro_features import (  # noqa: E402
    build_feature_panel, FEATURE_COLUMNS, VIX_TERM_FEATURES,
)


# ----------------------------------------------------------------------
# Data loaders (same as baseline)
# ----------------------------------------------------------------------
def load_spy() -> pd.Series:
    p = REPO / "data" / "processed" / "SPY_1d.csv"
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    s = df["Close"].astype(float).sort_index()
    s.index = pd.to_datetime(s.index).tz_localize(None) if s.index.tz is not None else pd.to_datetime(s.index)
    return s


def load_fred(series_id: str) -> Optional[pd.Series]:
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
# Target construction
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
# Metrics
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


def hit_rate_and_fpr(
    signal_fired: np.ndarray, labels: np.ndarray
) -> Tuple[float, float, float, int, int, int, int]:
    mask = ~(np.isnan(signal_fired.astype(float)) | np.isnan(labels))
    s = signal_fired[mask].astype(int)
    y = labels[mask].astype(int)
    tp = int(((s == 1) & (y == 1)).sum())
    fp = int(((s == 1) & (y == 0)).sum())
    fn = int(((s == 0) & (y == 1)).sum())
    tn = int(((s == 0) & (y == 0)).sum())
    tpr = tp / (tp + fn) if (tp + fn) > 0 else float("nan")
    fpr = fp / (fp + tn) if (fp + tn) > 0 else float("nan")
    prec = tp / (tp + fp) if (tp + fp) > 0 else float("nan")
    return tpr, fpr, prec, tp, fp, fn, tn


def cond_mean_dd(fdd: pd.Series, mask: pd.Series, label: str) -> Dict:
    common = fdd.dropna().index.intersection(mask.dropna().index)
    fdd_c = fdd.loc[common]
    m = mask.loc[common].astype(bool)
    cond = fdd_c[m]
    return {
        "label": label,
        "n_days_in_regime": int(m.sum()),
        "n_total": int(len(fdd_c)),
        "pct_in_regime": float(m.mean()),
        "mean_fwd_dd_in_regime": float(cond.mean()) if len(cond) else float("nan"),
        "mean_fwd_dd_unconditional": float(fdd_c.mean()),
        "p10_fwd_dd_in_regime": float(cond.quantile(0.10)) if len(cond) else float("nan"),
        "p10_fwd_dd_unconditional": float(fdd_c.quantile(0.10)),
    }


def lead_time_stats(
    price: pd.Series, signal_fired: pd.Series, horizon: int, threshold: float
) -> Dict:
    out_lead_days: List[int] = []
    out_no_warning = 0
    px = price.copy()
    sf = signal_fired.reindex(px.index).fillna(False).astype(bool)
    fdd = forward_drawdown(px, horizon)
    qualifying = fdd[fdd <= threshold]
    if len(qualifying) == 0:
        return {
            "n_drawdown_events": 0, "events_with_warning": 0,
            "events_no_warning": 0, "median_lead_days": float("nan"),
            "p25_lead_days": float("nan"), "p75_lead_days": float("nan"),
        }
    qualifying_dates = list(qualifying.index)
    used = set()
    events: List[Tuple[pd.Timestamp, pd.Timestamp]] = []
    i = 0
    while i < len(qualifying_dates):
        anchor = qualifying_dates[i]
        if anchor in used:
            i += 1
            continue
        anchor_pos = px.index.get_loc(anchor)
        end_pos = min(anchor_pos + horizon, len(px) - 1)
        forward_window = px.iloc[anchor_pos + 1: end_pos + 1]
        if len(forward_window) == 0:
            i += 1
            continue
        trough_date = forward_window.idxmin()
        events.append((anchor, trough_date))
        skip_until = trough_date
        while i < len(qualifying_dates) and qualifying_dates[i] <= skip_until:
            used.add(qualifying_dates[i])
            i += 1

    look_back = 60
    for anchor, trough in events:
        anchor_pos = px.index.get_loc(anchor)
        lookback_start = max(0, anchor_pos - look_back + 1)
        lookback_window = sf.iloc[lookback_start: anchor_pos + 1]
        if not lookback_window.any():
            out_no_warning += 1
            continue
        first_fire_date = lookback_window[lookback_window].index[0]
        first_fire_pos = px.index.get_loc(first_fire_date)
        trough_pos = px.index.get_loc(trough)
        out_lead_days.append(int(trough_pos - first_fire_pos))

    if out_lead_days:
        arr = np.array(out_lead_days)
        return {
            "n_drawdown_events": len(events),
            "events_with_warning": len(out_lead_days),
            "events_no_warning": out_no_warning,
            "median_lead_days": float(np.median(arr)),
            "p25_lead_days": float(np.percentile(arr, 25)),
            "p75_lead_days": float(np.percentile(arr, 75)),
            "mean_lead_days": float(arr.mean()),
        }
    return {
        "n_drawdown_events": len(events),
        "events_with_warning": 0,
        "events_no_warning": out_no_warning,
        "median_lead_days": float("nan"),
        "p25_lead_days": float("nan"),
        "p75_lead_days": float("nan"),
    }


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default="2025-04-30")
    ap.add_argument("--horizon", type=int, default=20)
    ap.add_argument(
        "--hmm-pkl",
        default=str(REPO / "engines" / "engine_e_regime" / "models" / "hmm_3state_vix_term_v1.pkl"),
    )
    ap.add_argument(
        "--out-json",
        default=str(REPO / "docs" / "Measurements" / "2026-05" / "regime_signal_validation_vix_term_2026_05_06.json"),
    )
    ap.add_argument("--dd-threshold", type=float, default=-0.05)
    args = ap.parse_args()

    print(f"[info] window: {args.start} -> {args.end}, horizon={args.horizon}d")

    # ---- Load HMM model ----
    print(f"[info] loading HMM from {args.hmm_pkl}")
    hmm = HMMRegimeClassifier.load(args.hmm_pkl)
    print(f"[info] HMM trained {hmm._artifact_metadata['train_start']} -> "
          f"{hmm._artifact_metadata['train_end']}, "
          f"n_obs={hmm._artifact_metadata['n_train_obs']}, "
          f"n_features={len(hmm.feature_names)}, "
          f"label_for_idx={hmm._state_label_for_idx}")
    print(f"[info] feature_names={hmm.feature_names}")

    # ---- Build extended feature panel ----
    panel = build_feature_panel(
        root=REPO, start="2020-04-01", end=args.end,
        include_aux=False, include_vix_term=True,
    )
    print(f"[info] feature panel rows={len(panel)}, cols={list(panel.columns)}")

    proba_df = hmm.predict_proba_sequence(panel)
    mask_window = (proba_df.index >= pd.Timestamp(args.start)) & (proba_df.index <= pd.Timestamp(args.end))
    proba_df = proba_df.loc[mask_window]
    print(f"[info] HMM proba labeled rows in window: {len(proba_df)}")
    print(f"[info] state mean probabilities in window:")
    for col in proba_df.columns:
        print(f"        {col}: mean={proba_df[col].mean():.4f}")

    # ---- Load SPY and forward targets ----
    spy = load_spy()
    spy = spy.loc[(spy.index >= pd.Timestamp(args.start)) & (spy.index <= pd.Timestamp(args.end))]
    fdd = forward_drawdown(spy, args.horizon)
    fret = forward_return(spy, args.horizon)
    fdd_5 = forward_drawdown(spy, 5)
    fdd_60 = forward_drawdown(spy, 60)

    target = (fdd <= args.dd_threshold).astype(float); target[fdd.isna()] = np.nan
    target_5 = (fdd_5 <= args.dd_threshold).astype(float); target_5[fdd_5.isna()] = np.nan
    target_60 = (fdd_60 <= args.dd_threshold).astype(float); target_60[fdd_60.isna()] = np.nan
    target_3 = (fdd <= -0.03).astype(float); target_3[fdd.isna()] = np.nan

    base_rate_20 = float(target.mean())
    base_rate_5 = float(target_5.mean())
    base_rate_60 = float(target_60.mean())
    print(f"[info] uncond rate of fwd dd <= {args.dd_threshold:+.0%}: "
          f"5d={base_rate_5:.3f}, 20d={base_rate_20:.3f}, 60d={base_rate_60:.3f}")

    common = proba_df.index.intersection(target.index)
    proba_df = proba_df.loc[common]
    fdd = fdd.loc[common]
    fdd_5 = fdd_5.loc[common]
    fdd_60 = fdd_60.loc[common]
    fret = fret.loc[common]
    target = target.loc[common]
    target_5 = target_5.loc[common]
    target_60 = target_60.loc[common]
    target_3 = target_3.loc[common]
    spy_aligned = spy.loc[common]
    panel_window = panel.loc[panel.index.isin(common)]
    print(f"[info] aligned analysis rows: {len(common)}")

    # ---- Standalone AUC on the new VIX features (per dispatch ask 2) ----
    standalone_auc = {}
    for feat in VIX_TERM_FEATURES:
        if feat in panel_window.columns:
            x = panel_window[feat].reindex(common).values
            standalone_auc[feat] = {
                "20d_dd_5pct": auc_score(x, target.values),
                "20d_dd_3pct": auc_score(x, target_3.values),
                "5d_dd_5pct": auc_score(x, target_5.values),
                "60d_dd_5pct": auc_score(x, target_60.values),
            }
    print("\n=== Standalone AUC of VIX term-structure features ===")
    print(f"  feature                                   20d_5%   20d_3%   5d_5%    60d_5%")
    for feat, vals in standalone_auc.items():
        print(f"  {feat:42s} {vals['20d_dd_5pct']:.4f}   "
              f"{vals['20d_dd_3pct']:.4f}   "
              f"{vals['5d_dd_5pct']:.4f}   "
              f"{vals['60d_dd_5pct']:.4f}")

    # ---- HMM AUC block (the headline numbers vs baseline) ----
    p_benign = proba_df["benign"]
    p_stressed = proba_df["stressed"]
    p_crisis = proba_df["crisis"]
    p_stress_or_crisis = p_stressed + p_crisis

    auc_block: Dict[str, Dict] = {
        "20d": {
            "hmm_p_crisis": auc_score(p_crisis.values, target.values),
            "hmm_p_stressed": auc_score(p_stressed.values, target.values),
            "hmm_p_stress_or_crisis": auc_score(p_stress_or_crisis.values, target.values),
            "hmm_neg_p_benign": auc_score((-p_benign).values, target.values),
        },
        "5d": {
            "hmm_p_crisis": auc_score(p_crisis.values, target_5.values),
            "hmm_p_stress_or_crisis": auc_score(p_stress_or_crisis.values, target_5.values),
        },
        "60d": {
            "hmm_p_crisis": auc_score(p_crisis.values, target_60.values),
            "hmm_p_stress_or_crisis": auc_score(p_stress_or_crisis.values, target_60.values),
        },
    }
    print("\n=== HMM AUC vs forward 20d drawdown <= -5% target ===")
    for k, v in auc_block["20d"].items():
        print(f"  {k:38s} AUC={v:.4f}")
    print("\n=== HMM AUC at 5d horizon ===")
    for k, v in auc_block["5d"].items():
        print(f"  {k:38s} AUC={v:.4f}")
    print("\n=== HMM AUC at 60d horizon ===")
    for k, v in auc_block["60d"].items():
        print(f"  {k:38s} AUC={v:.4f}")

    # ---- Coincident-vs-leading correlation test (the verdict signal) ----
    # Pearson(p_crisis, trailing 20d return) vs Pearson(p_crisis, forward 20d return)
    trailing_ret_20d = (spy_aligned / spy_aligned.shift(20) - 1.0)
    fret_aligned = fret.reindex(common)
    df_corr = pd.DataFrame({
        "p_crisis": p_crisis.reindex(common),
        "p_stress_or_crisis": p_stress_or_crisis.reindex(common),
        "neg_p_benign": -p_benign.reindex(common),
        "trailing_20d_ret": trailing_ret_20d,
        "forward_20d_ret": fret_aligned,
    }).dropna()
    coincident_leading = {}
    for sig_col in ("p_crisis", "p_stress_or_crisis", "neg_p_benign"):
        coincident_leading[sig_col] = {
            "pearson_vs_trailing_20d_ret": float(df_corr[sig_col].corr(df_corr["trailing_20d_ret"])),
            "pearson_vs_forward_20d_ret": float(df_corr[sig_col].corr(df_corr["forward_20d_ret"])),
        }
    print("\n=== Coincident-vs-leading test (Pearson) ===")
    print(f"  signal                  trailing_20d_ret   forward_20d_ret   |fwd|/|trail|")
    for k, v in coincident_leading.items():
        ratio = abs(v["pearson_vs_forward_20d_ret"]) / max(abs(v["pearson_vs_trailing_20d_ret"]), 1e-9)
        print(f"  {k:24s} {v['pearson_vs_trailing_20d_ret']:+.4f}             "
              f"{v['pearson_vs_forward_20d_ret']:+.4f}            {ratio:.3f}")

    # Same correlations for the standalone term-structure features
    for feat in VIX_TERM_FEATURES:
        if feat in panel_window.columns:
            x = panel_window[feat].reindex(common)
            df_x = pd.DataFrame({
                "x": x,
                "trailing_20d_ret": trailing_ret_20d,
                "forward_20d_ret": fret_aligned,
            }).dropna()
            coincident_leading[feat] = {
                "pearson_vs_trailing_20d_ret": float(df_x["x"].corr(df_x["trailing_20d_ret"])),
                "pearson_vs_forward_20d_ret": float(df_x["x"].corr(df_x["forward_20d_ret"])),
            }
            ratio = abs(coincident_leading[feat]["pearson_vs_forward_20d_ret"]) / max(abs(coincident_leading[feat]["pearson_vs_trailing_20d_ret"]), 1e-9)
            print(f"  {feat:24s} {coincident_leading[feat]['pearson_vs_trailing_20d_ret']:+.4f}             "
                  f"{coincident_leading[feat]['pearson_vs_forward_20d_ret']:+.4f}            {ratio:.3f}")

    # ---- Conditional mean drawdowns by HMM state ----
    argmax_state = proba_df.idxmax(axis=1)
    cond_block: Dict[str, Dict] = {}
    for state_name in ("benign", "stressed", "crisis"):
        mask_state = argmax_state == state_name
        cond_block[f"hmm_{state_name}"] = cond_mean_dd(fdd, mask_state, f"hmm_{state_name}")
        common_idx = fret.dropna().index.intersection(mask_state.dropna().index)
        cond_block[f"hmm_{state_name}"]["mean_fwd_ret_in_regime"] = float(
            fret.loc[common_idx][mask_state.loc[common_idx]].mean()
        )

    print("\n=== Conditional 20d forward drawdown by regime ===")
    print(f"  unconditional baseline: mean_fwd_dd={fdd.mean():+.4f}, base_rate={base_rate_20:.3f}")
    for k, v in cond_block.items():
        print(f"  {k:42s} N={v['n_days_in_regime']:4d} "
              f"({v['pct_in_regime']*100:5.1f}%) "
              f"mean_fwd_dd={v['mean_fwd_dd_in_regime']:+.4f} "
              f"p10={v['p10_fwd_dd_in_regime']:+.4f}")

    # ---- Hit rate / FPR ----
    fired_argmax_crisis = (argmax_state == "crisis").astype(float)
    fired_argmax_stressed_or_crisis = argmax_state.isin(["stressed", "crisis"]).astype(float)
    fired_pcrisis_50 = (p_crisis > 0.5).astype(float)
    fired_pstress_50 = (p_stress_or_crisis > 0.5).astype(float)

    hit_block: Dict[str, Dict] = {}
    for label, signal in [
        ("argmax_crisis", fired_argmax_crisis),
        ("argmax_stressed_or_crisis", fired_argmax_stressed_or_crisis),
        ("p_crisis_gt_0.5", fired_pcrisis_50),
        ("p_stress_or_crisis_gt_0.5", fired_pstress_50),
    ]:
        tpr, fpr, prec, tp, fp, fn, tn = hit_rate_and_fpr(signal.values, target.values)
        hit_block[label] = {
            "TPR_hit_rate": tpr, "FPR": fpr, "precision": prec,
            "TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "lift_over_base": (prec - base_rate_20) if not np.isnan(prec) else float("nan"),
        }
    print("\n=== Hit rate / FPR / precision (target: 20d fwd dd <= -5%) ===")
    print(f"  {'signal':40s} TPR     FPR     prec    lift_vs_base")
    for k, v in hit_block.items():
        lift = v["lift_over_base"]
        lift_str = f"{lift:+.3f}" if not np.isnan(lift) else "nan"
        print(f"  {k:40s} {v['TPR_hit_rate']:.3f}   {v['FPR']:.3f}   "
              f"{v['precision']:.3f}   {lift_str}")

    # ---- Lead time ----
    lead_block: Dict[str, Dict] = {}
    for label, signal in [
        ("argmax_crisis", fired_argmax_crisis),
        ("argmax_stressed_or_crisis", fired_argmax_stressed_or_crisis),
        ("p_crisis_gt_0.5", fired_pcrisis_50),
        ("p_stress_or_crisis_gt_0.5", fired_pstress_50),
    ]:
        lead_block[label] = lead_time_stats(
            spy_aligned, signal.fillna(0).astype(bool), args.horizon, args.dd_threshold
        )
    print("\n=== Lead-time distribution ===")
    print(f"  {'signal':40s} events  warned   median_lead  p25  p75")
    for k, v in lead_block.items():
        median = v.get("median_lead_days", float("nan"))
        median_str = f"{median:.1f}" if not (isinstance(median, float) and np.isnan(median)) else "nan"
        print(f"  {k:40s} {v['n_drawdown_events']:3d}     "
              f"{v['events_with_warning']:3d}      {median_str:>6s}")

    # ---- IS vs OOS (2025 Jan-Apr is the canonical -18.8% drawdown OOS slice) ----
    is_mask = (proba_df.index >= "2021-01-01") & (proba_df.index <= "2024-12-31")
    oos_mask = (proba_df.index >= "2025-01-01")
    print("\n=== In-sample (2021-2024) vs OOS (2025 Jan-Apr) ===")
    print(f"  in-sample N={is_mask.sum()}, OOS N={oos_mask.sum()}")
    print(f"  OOS dd<=-5% positives: {int(target[oos_mask].sum())}")
    print(f"  OOS dd<=-3% positives: {int(target_3[oos_mask].sum())}")

    is_oos_block = {
        "in_sample_n": int(is_mask.sum()),
        "oos_n": int(oos_mask.sum()),
        "is_auc_p_crisis_dd5": auc_score(p_crisis[is_mask].values, target[is_mask].values),
        "is_auc_p_crisis_dd3": auc_score(p_crisis[is_mask].values, target_3[is_mask].values),
        "is_auc_p_stress_or_crisis_dd5": auc_score(p_stress_or_crisis[is_mask].values, target[is_mask].values),
        "is_auc_p_stress_or_crisis_dd3": auc_score(p_stress_or_crisis[is_mask].values, target_3[is_mask].values),
        "oos_auc_p_crisis_dd3": auc_score(p_crisis[oos_mask].values, target_3[oos_mask].values),
        "oos_auc_p_stress_or_crisis_dd3": auc_score(p_stress_or_crisis[oos_mask].values, target_3[oos_mask].values),
        "oos_auc_neg_p_benign_dd3": auc_score((-p_benign[oos_mask]).values, target_3[oos_mask].values),
        "oos_base_rate_dd_3pct_20d": float(target_3[oos_mask].mean()),
    }
    print(f"  IS  hmm_p_crisis              AUC (5%)={is_oos_block['is_auc_p_crisis_dd5']:.4f}  "
          f"AUC (3%)={is_oos_block['is_auc_p_crisis_dd3']:.4f}")
    print(f"  IS  hmm_p_stress_or_crisis    AUC (5%)={is_oos_block['is_auc_p_stress_or_crisis_dd5']:.4f}  "
          f"AUC (3%)={is_oos_block['is_auc_p_stress_or_crisis_dd3']:.4f}")
    print(f"  OOS hmm_p_crisis              AUC (3%)={is_oos_block['oos_auc_p_crisis_dd3']:.4f}")
    print(f"  OOS hmm_p_stress_or_crisis    AUC (3%)={is_oos_block['oos_auc_p_stress_or_crisis_dd3']:.4f}")
    print(f"  OOS hmm_neg_p_benign          AUC (3%)={is_oos_block['oos_auc_neg_p_benign_dd3']:.4f}")

    # ---- 2025 OOS narrative slice ----
    # Did the rebuilt HMM call stress BEFORE or DURING the -18.8% drawdown?
    spy_oos = spy.loc[(spy.index >= "2025-01-01")]
    if len(spy_oos) > 5:
        # Find the trough date in the OOS window
        trough_date = spy_oos.idxmin()
        # SPY peak before trough (within OOS window)
        pre_trough = spy_oos.loc[:trough_date]
        peak_date = pre_trough.idxmax() if len(pre_trough) else None
        oos_max_dd = float((spy_oos.min() - pre_trough.max()) / pre_trough.max()) if peak_date else float("nan")
        print(f"\n=== 2025 OOS drawdown narrative ===")
        print(f"  Peak: {peak_date} @ ${spy.loc[peak_date]:.2f}" if peak_date else "  no peak")
        print(f"  Trough: {trough_date} @ ${spy.loc[trough_date]:.2f}")
        print(f"  Peak-to-trough: {oos_max_dd:+.4f}")
        # State on each of: peak day, week-before-trough, trough day, day-after-trough
        for tag, d in [("peak", peak_date), ("trough-7d",
                                              (trough_date - pd.Timedelta(days=7)) if trough_date else None),
                       ("trough", trough_date),
                       ("trough+7d",
                        (trough_date + pd.Timedelta(days=7)) if trough_date else None)]:
            if d is None:
                continue
            # Find the closest panel date <= d
            valid = proba_df.index[proba_df.index <= d]
            if len(valid) == 0:
                print(f"  {tag:11s} {d.date()}  no HMM probs available")
                continue
            anchor = valid[-1]
            row = proba_df.loc[anchor]
            argm = row.idxmax()
            print(f"  {tag:11s} as of {anchor.date()}  argmax={argm}  "
                  f"benign={row['benign']:.3f} stressed={row['stressed']:.3f} crisis={row['crisis']:.3f}")
        # And the standalone VIX features on those same anchor dates
        print(f"  standalone VIX features at those anchors:")
        for tag, d in [("peak", peak_date), ("trough", trough_date)]:
            if d is None: continue
            valid = panel.index[panel.index <= d]
            if len(valid) == 0: continue
            anchor = valid[-1]
            row = panel.loc[anchor, VIX_TERM_FEATURES]
            print(f"  {tag:11s} as of {anchor.date()}  {row.to_dict()}")
        oos_narrative = {
            "peak_date": str(peak_date.date()) if peak_date else None,
            "trough_date": str(trough_date.date()) if trough_date else None,
            "peak_to_trough_dd": oos_max_dd,
        }
    else:
        oos_narrative = {"note": "insufficient OOS data"}

    # ---- Persistence ----
    fired_signals = {
        "argmax_crisis": fired_argmax_crisis,
        "argmax_stressed_or_crisis": fired_argmax_stressed_or_crisis,
    }
    persistence_block: Dict[str, Dict] = {}
    print("\n=== Signal persistence ===")
    for k, sig in fired_signals.items():
        sig_b = sig.fillna(0).astype(bool)
        runs = []; cur = 0
        for v in sig_b.values:
            if v: cur += 1
            else:
                if cur > 0: runs.append(cur); cur = 0
        if cur > 0: runs.append(cur)
        median_run = float(np.median(runs)) if runs else 0.0
        max_run = float(np.max(runs)) if runs else 0.0
        on_pct = float(sig_b.mean())
        persistence_block[k] = {
            "n_runs": len(runs),
            "median_run_length_bars": median_run,
            "max_run_length_bars": max_run,
            "pct_time_on": on_pct,
        }
        print(f"  {k:40s} n_runs={len(runs):3d}  median_run={median_run:5.1f}  "
              f"max_run={max_run:5.1f}  pct_on={on_pct:.3f}")

    results = {
        "args": vars(args),
        "hmm_metadata": dict(hmm._artifact_metadata),
        "hmm_state_label_for_idx": list(hmm._state_label_for_idx),
        "hmm_feature_names": list(hmm.feature_names),
        "window_n_days": int(len(common)),
        "base_rate_dd_5d": base_rate_5,
        "base_rate_dd_20d": base_rate_20,
        "base_rate_dd_60d": base_rate_60,
        "uncond_mean_fwd_dd_20d": float(fdd.mean()),
        "uncond_mean_fwd_ret_20d": float(fret.mean()),
        "auc": auc_block,
        "standalone_vix_term_auc": standalone_auc,
        "coincident_leading_correlation": coincident_leading,
        "conditional": cond_block,
        "hit_fpr": hit_block,
        "lead_time": lead_block,
        "is_oos": is_oos_block,
        "oos_narrative_2025": oos_narrative,
        "persistence": persistence_block,
    }

    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[info] wrote results to {out_path}")


if __name__ == "__main__":
    main()
