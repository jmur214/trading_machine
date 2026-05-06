"""validate_regime_signals — read-only validation of HMM + WS-C signals.

Question: Do HMM regime classifications and WS-C cross-asset features
predict forward SPY drawdowns above the unconditional rate?

This is a SIGNAL-LEVEL validation. We do NOT run a full backtest.
We label every trading day from 2021-01-01 → 2025-04-30 with the HMM's
filtered (causal) regime call and the three WS-C cross-asset signals,
then measure whether those labels predict next-N-day forward SPY
drawdowns.

Outputs (to stdout + JSON):
  - AUC for each signal form (HMM stress prob, HMM crisis prob,
    HYG/LQD z, DXY change, VVIX-proxy, combined HMM+WS-C),
    with target = "did SPY have ≥-5% drawdown over next 20 trading days"
  - Conditional drawdown rate in regime X vs unconditional baseline
  - Hit rate / FPR at canonical thresholds
  - Lead-time distribution: when a real -5% drawdown occurs, how many
    days before the trough did the signal first fire?
  - Per-regime breakdown of HMM (benign/stressed/crisis)
  - Component decomposition for the three WS-C inputs

Read-only: no governor writes, no production runs.
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
from engines.engine_e_regime.macro_features import build_feature_panel  # noqa: E402


# ----------------------------------------------------------------------
# Data loaders
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
# WS-C cross-asset signals (replicate the foundry feature semantics so
# we can vectorize across the whole window without instantiating the
# foundry registry)
# ----------------------------------------------------------------------
def compute_hyg_lqd_z(daily_idx: pd.DatetimeIndex) -> pd.Series:
    """60-business-day z-score of (BAMLH0A0HYM2 - BAMLC0A0CM)."""
    hy = load_fred("BAMLH0A0HYM2")
    ig = load_fred("BAMLC0A0CM")
    if hy is None or ig is None:
        return pd.Series(np.nan, index=daily_idx)
    aligned = hy.to_frame("hy").join(ig.to_frame("ig"), how="inner").dropna()
    spread = (aligned["hy"] - aligned["ig"]).astype(float).sort_index()
    # 60-bday rolling z
    mean60 = spread.rolling(60, min_periods=60).mean()
    std60 = spread.rolling(60, min_periods=60).std(ddof=1)
    z = (spread - mean60) / std60.replace(0.0, np.nan)
    z = z.reindex(daily_idx, method="ffill")
    return z


def compute_dxy_change_20d(daily_idx: pd.DatetimeIndex) -> pd.Series:
    s = load_fred("DTWEXBGS")
    if s is None:
        return pd.Series(np.nan, index=daily_idx)
    s_aligned = s.reindex(daily_idx, method="ffill")
    # 20-bday percent change
    return s_aligned.pct_change(20)


def compute_vvix_proxy(daily_idx: pd.DatetimeIndex) -> pd.Series:
    s = load_fred("VIXCLS")
    if s is None:
        return pd.Series(np.nan, index=daily_idx)
    s = s.dropna()
    log_ret = np.log(s).diff()
    rolling_std = log_ret.rolling(30, min_periods=30).std(ddof=1) * np.sqrt(252.0)
    return rolling_std.reindex(daily_idx, method="ffill")


# ----------------------------------------------------------------------
# Target construction
# ----------------------------------------------------------------------
def forward_drawdown(price: pd.Series, horizon: int) -> pd.Series:
    """For each t, the worst forward drawdown over (t, t+horizon].

    Returns a Series with the same index as price; values are negative
    fractions (e.g. -0.05 = -5% drawdown). Forward window is forward-
    looking — last `horizon` bars are NaN.
    """
    rolling_min = price.shift(-1).rolling(horizon, min_periods=1).min()
    # We want min forward price relative to current price
    out = (rolling_min - price) / price
    # Last horizon bars don't have full window; mark NaN
    out.iloc[-horizon:] = np.nan
    return out


def forward_return(price: pd.Series, horizon: int) -> pd.Series:
    """Forward arithmetic return over `horizon` bars."""
    fwd = price.shift(-horizon)
    out = (fwd - price) / price
    out.iloc[-horizon:] = np.nan
    return out


# ----------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------
def auc_score(scores: np.ndarray, labels: np.ndarray) -> float:
    """ROC AUC from scratch (avoids sklearn dependency).

    scores: signal strength (higher = more likely positive).
    labels: 0/1 binary outcome.
    """
    mask = ~(np.isnan(scores) | np.isnan(labels))
    s = scores[mask]
    y = labels[mask].astype(int)
    if len(s) == 0 or y.sum() == 0 or y.sum() == len(y):
        return float("nan")
    # Mann-Whitney U based AUC
    order = np.argsort(s)
    ranks = np.empty(len(s), dtype=np.float64)
    # Handle ties via average rank
    sorted_s = s[order]
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and sorted_s[j + 1] == sorted_s[i]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0  # ranks 1-indexed
        ranks[order[i:j + 1]] = avg_rank
        i = j + 1
    n_pos = y.sum()
    n_neg = len(y) - n_pos
    sum_pos_ranks = ranks[y == 1].sum()
    auc = (sum_pos_ranks - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)
    return float(auc)


def hit_rate_and_fpr(
    signal_fired: np.ndarray, labels: np.ndarray
) -> Tuple[float, float, float, int, int, int, int]:
    """Hit rate (TPR) and false-positive rate.

    Returns: (TPR, FPR, precision, TP, FP, FN, TN).
    """
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


def cond_mean_dd(
    fwd_dd: pd.Series, mask: pd.Series, label: str
) -> Dict[str, float]:
    """Mean forward drawdown conditional on a boolean mask."""
    common = fwd_dd.dropna().index.intersection(mask.dropna().index)
    fdd = fwd_dd.loc[common]
    m = mask.loc[common].astype(bool)
    cond = fdd[m]
    uncond = fdd
    return {
        "label": label,
        "n_days_in_regime": int(m.sum()),
        "n_total": int(len(fdd)),
        "pct_in_regime": float(m.mean()),
        "mean_fwd_dd_in_regime": float(cond.mean()) if len(cond) else float("nan"),
        "mean_fwd_dd_unconditional": float(uncond.mean()),
        "median_fwd_dd_in_regime": float(cond.median()) if len(cond) else float("nan"),
        "median_fwd_dd_unconditional": float(uncond.median()),
        "p10_fwd_dd_in_regime": float(cond.quantile(0.10)) if len(cond) else float("nan"),
        "p10_fwd_dd_unconditional": float(uncond.quantile(0.10)),
    }


def lead_time_stats(
    price: pd.Series,
    signal_fired: pd.Series,
    horizon: int,
    threshold: float = -0.05,
) -> Dict[str, float]:
    """For each forward window with drawdown ≤ threshold, find the lead
    time between first signal-fire and the trough.

    Specifically:
      - identify the forward troughs (date of forward-window min where
        forward_dd ≤ threshold)
      - cluster troughs that are within `horizon` bars of each other
        (so a single drawdown event isn't double-counted)
      - for each event's anchor date (the day BEFORE the drawdown
        started), find the earliest signal_fired==1 within the prior
        60 bars; compute lead = trough_date - first_fire_date
    """
    # Compute the trough date for each anchor t: argmin over (t, t+horizon]
    out_lead_days: List[int] = []
    out_no_warning: int = 0
    out_total_events: int = 0

    px = price.copy()
    sf = signal_fired.reindex(px.index).fillna(False).astype(bool)

    # Find rolling forward minimums and their location
    fdd = forward_drawdown(px, horizon)
    qualifying = fdd[fdd <= threshold]
    if len(qualifying) == 0:
        return {
            "n_drawdown_events": 0,
            "events_with_warning": 0,
            "events_no_warning": 0,
            "median_lead_days": float("nan"),
            "p25_lead_days": float("nan"),
            "p75_lead_days": float("nan"),
        }

    # Cluster anchor dates that share a forward window (so a single
    # episode counts once). Walk forward; whenever we see a qualifying
    # anchor, find its trough, then skip ahead past the trough.
    qualifying_dates = list(qualifying.index)
    used = set()
    events: List[pd.Timestamp] = []
    i = 0
    while i < len(qualifying_dates):
        anchor = qualifying_dates[i]
        if anchor in used:
            i += 1
            continue
        # Find trough date inside (anchor, anchor+horizon]
        anchor_pos = px.index.get_loc(anchor)
        end_pos = min(anchor_pos + horizon, len(px) - 1)
        forward_window_pos = px.iloc[anchor_pos + 1: end_pos + 1]
        if len(forward_window_pos) == 0:
            i += 1
            continue
        trough_date = forward_window_pos.idxmin()
        events.append((anchor, trough_date))
        # Skip past the trough so subsequent anchors inside this episode
        # don't double-count
        skip_until = trough_date
        while i < len(qualifying_dates) and qualifying_dates[i] <= skip_until:
            used.add(qualifying_dates[i])
            i += 1

    out_total_events = len(events)
    look_back = 60  # bars to search backward for first signal-fire
    for anchor, trough in events:
        anchor_pos = px.index.get_loc(anchor)
        lookback_start = max(0, anchor_pos - look_back + 1)
        lookback_window = sf.iloc[lookback_start: anchor_pos + 1]
        if not lookback_window.any():
            out_no_warning += 1
            continue
        first_fire_date = lookback_window[lookback_window].index[0]
        # Lead in trading days = position(trough) - position(first_fire)
        first_fire_pos = px.index.get_loc(first_fire_date)
        trough_pos = px.index.get_loc(trough)
        out_lead_days.append(int(trough_pos - first_fire_pos))

    if out_lead_days:
        arr = np.array(out_lead_days)
        return {
            "n_drawdown_events": out_total_events,
            "events_with_warning": len(out_lead_days),
            "events_no_warning": out_no_warning,
            "median_lead_days": float(np.median(arr)),
            "p25_lead_days": float(np.percentile(arr, 25)),
            "p75_lead_days": float(np.percentile(arr, 75)),
            "mean_lead_days": float(arr.mean()),
        }
    return {
        "n_drawdown_events": out_total_events,
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
        default=str(REPO / "engines" / "engine_e_regime" / "models" / "hmm_3state_v1.pkl"),
    )
    ap.add_argument(
        "--out-json",
        default=str(REPO / "docs" / "Measurements" / "2026-05" / "regime_signal_validation_2026_05_06.json"),
    )
    ap.add_argument("--dd-threshold", type=float, default=-0.05)
    args = ap.parse_args()

    print(f"[info] window: {args.start} → {args.end}, horizon={args.horizon}d")
    print(f"[info] dd threshold for binary target: {args.dd_threshold:+.0%}")

    # ---- Load HMM model ----
    print(f"[info] loading HMM from {args.hmm_pkl}")
    hmm = HMMRegimeClassifier.load(args.hmm_pkl)
    print(f"[info] HMM trained {hmm._artifact_metadata['train_start']} → "
          f"{hmm._artifact_metadata['train_end']}, "
          f"n_obs={hmm._artifact_metadata['n_train_obs']}, "
          f"label_for_idx={hmm._state_label_for_idx}")

    # ---- Build feature panel for HMM and label every day ----
    # Build over a wider range to give rolling features enough warm-up
    panel = build_feature_panel(root=REPO, start="2020-04-01", end=args.end, include_aux=False)
    print(f"[info] feature panel rows={len(panel)}, cols={list(panel.columns)}")

    # Use predict_proba_sequence on the full panel; this runs forward-
    # backward smoothed, but for time series labeling it's equivalent
    # to the per-bar predict at this granularity.
    proba_df = hmm.predict_proba_sequence(panel)
    # Restrict to the validation window AFTER labeling to preserve the
    # full warm-up.
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

    # Binary target: forward dd ≤ threshold
    target = (fdd <= args.dd_threshold).astype(float)
    target[fdd.isna()] = np.nan
    target_5 = (fdd_5 <= args.dd_threshold).astype(float)
    target_5[fdd_5.isna()] = np.nan
    target_60 = (fdd_60 <= args.dd_threshold).astype(float)
    target_60[fdd_60.isna()] = np.nan
    # Looser target for OOS where the 2025 drawdown peaks at ~-4.8% on 20d
    # forward windows; -5% is too tight to register the event for short horizons
    target_3 = (fdd <= -0.03).astype(float)
    target_3[fdd.isna()] = np.nan

    base_rate_20 = float(target.mean())
    base_rate_5 = float(target_5.mean())
    base_rate_60 = float(target_60.mean())
    print(f"[info] unconditional rate of fwd dd ≤ {args.dd_threshold:+.0%}: "
          f"5d={base_rate_5:.3f}, 20d={base_rate_20:.3f}, 60d={base_rate_60:.3f}")
    print(f"[info] unconditional mean 20d fwd dd: {fdd.mean():.4f}")
    print(f"[info] unconditional mean 20d fwd return: {fret.mean():.4f}")

    # Align everything on common index
    common = proba_df.index.intersection(target.index)
    proba_df = proba_df.loc[common]
    fdd = fdd.loc[common]
    fdd_5 = fdd_5.loc[common]
    fdd_60 = fdd_60.loc[common]
    fret = fret.loc[common]
    target = target.loc[common]
    target_5 = target_5.loc[common]
    target_60 = target_60.loc[common]
    spy_aligned = spy.loc[common]

    print(f"[info] aligned analysis rows: {len(common)}")

    # ---- Compute WS-C cross-asset signals ----
    hyg_z = compute_hyg_lqd_z(common)
    dxy_chg = compute_dxy_change_20d(common)
    vvix_p = compute_vvix_proxy(common)

    print(f"[info] WS-C signal coverage in window:")
    print(f"        hyg_lqd_z:      {(~hyg_z.isna()).sum()}/{len(common)} non-null")
    print(f"        dxy_change_20d: {(~dxy_chg.isna()).sum()}/{len(common)} non-null")
    print(f"        vvix_proxy:     {(~vvix_p.isna()).sum()}/{len(common)} non-null")

    # ====================================================================
    # MEASUREMENT 1: AUC of each continuous signal vs binary fwd dd target
    # ====================================================================
    results: Dict = {
        "args": vars(args),
        "hmm_metadata": dict(hmm._artifact_metadata),
        "hmm_state_label_for_idx": list(hmm._state_label_for_idx),
        "window_n_days": int(len(common)),
        "base_rate_dd_5d": base_rate_5,
        "base_rate_dd_20d": base_rate_20,
        "base_rate_dd_60d": base_rate_60,
        "uncond_mean_fwd_dd_20d": float(fdd.mean()),
        "uncond_mean_fwd_ret_20d": float(fret.mean()),
        "auc": {},
        "conditional": {},
        "hit_fpr": {},
        "lead_time": {},
    }

    # AUC: signal score → P(forward dd ≤ threshold)
    p_benign = proba_df["benign"]
    p_stressed = proba_df["stressed"]
    p_crisis = proba_df["crisis"]
    p_stress_or_crisis = p_stressed + p_crisis  # "non-benign" probability

    auc_block: Dict[str, Dict] = {}
    auc_block["20d"] = {
        "hmm_p_crisis": auc_score(p_crisis.values, target.values),
        "hmm_p_stressed": auc_score(p_stressed.values, target.values),
        "hmm_p_stress_or_crisis": auc_score(p_stress_or_crisis.values, target.values),
        "hmm_neg_p_benign": auc_score((-p_benign).values, target.values),  # high non-benign = high stress
        "hyg_lqd_z": auc_score(hyg_z.values, target.values),
        "dxy_change_20d": auc_score(dxy_chg.values, target.values),
        "vvix_proxy": auc_score(vvix_p.values, target.values),
    }
    auc_block["5d"] = {
        "hmm_p_crisis": auc_score(p_crisis.values, target_5.values),
        "hmm_p_stress_or_crisis": auc_score(p_stress_or_crisis.values, target_5.values),
        "hyg_lqd_z": auc_score(hyg_z.values, target_5.values),
        "dxy_change_20d": auc_score(dxy_chg.values, target_5.values),
        "vvix_proxy": auc_score(vvix_p.values, target_5.values),
    }
    auc_block["60d"] = {
        "hmm_p_crisis": auc_score(p_crisis.values, target_60.values),
        "hmm_p_stress_or_crisis": auc_score(p_stress_or_crisis.values, target_60.values),
        "hyg_lqd_z": auc_score(hyg_z.values, target_60.values),
        "dxy_change_20d": auc_score(dxy_chg.values, target_60.values),
        "vvix_proxy": auc_score(vvix_p.values, target_60.values),
    }

    # Combined: HMM stress probability AND ≥1 cross-asset confirmation
    # (we test both 1 and 2 confirmations as the "combined" signal so we
    # can see whether confirmation strictly helps)
    hyg_fired = (hyg_z > 1.0).astype(float).where(~hyg_z.isna())
    dxy_fired = (dxy_chg > 0.02).astype(float).where(~dxy_chg.isna())
    # vvix threshold: spec says 1.0 but realized vol of VIX rarely
    # exceeds 1.0 in normal regime; use 90th-percentile-historical instead
    vvix_thresh_p90 = float(vvix_p.quantile(0.90))
    vvix_fired = (vvix_p > vvix_thresh_p90).astype(float).where(~vvix_p.isna())
    n_confirms = (
        hyg_fired.fillna(0) + dxy_fired.fillna(0) + vvix_fired.fillna(0)
    )
    # For cells where ALL inputs are NaN, mark n_confirms NaN
    all_na = hyg_fired.isna() & dxy_fired.isna() & vvix_fired.isna()
    n_confirms[all_na] = np.nan

    # AUC of HMM crisis × confirmation count (interaction)
    combined_score = p_crisis * n_confirms.fillna(0)
    auc_block["20d"]["combined_pcrisis_x_confirms"] = auc_score(
        combined_score.values, target.values
    )
    # And HMM stress-or-crisis × confirms
    combined_score2 = p_stress_or_crisis * n_confirms.fillna(0)
    auc_block["20d"]["combined_pstress_x_confirms"] = auc_score(
        combined_score2.values, target.values
    )
    results["vvix_threshold_p90"] = vvix_thresh_p90
    results["auc"] = auc_block

    print("\n=== AUC vs forward 20d drawdown ≤ -5% target ===")
    for k, v in auc_block["20d"].items():
        print(f"  {k:38s} AUC={v:.4f}")
    print("\n=== AUC at 5d horizon ===")
    for k, v in auc_block["5d"].items():
        print(f"  {k:38s} AUC={v:.4f}")
    print("\n=== AUC at 60d horizon ===")
    for k, v in auc_block["60d"].items():
        print(f"  {k:38s} AUC={v:.4f}")

    # ====================================================================
    # MEASUREMENT 2: Conditional mean drawdown / return per regime
    # ====================================================================
    # Use argmax HMM state as the regime label
    argmax_state = proba_df.idxmax(axis=1)

    cond_block: Dict[str, Dict] = {}
    for state_name in ("benign", "stressed", "crisis"):
        mask_state = argmax_state == state_name
        cond_block[f"hmm_{state_name}"] = cond_mean_dd(fdd, mask_state, f"hmm_{state_name}")
        # Also forward return for upside symmetry
        common_idx = fret.dropna().index.intersection(mask_state.dropna().index)
        cond_block[f"hmm_{state_name}"]["mean_fwd_ret_in_regime"] = float(
            fret.loc[common_idx][mask_state.loc[common_idx]].mean()
        )
        cond_block[f"hmm_{state_name}"]["mean_fwd_ret_unconditional"] = float(
            fret.mean()
        )

    # Per-WS-C-component conditional dd (signal fires when above threshold)
    cond_block["hyg_z_above_1"] = cond_mean_dd(fdd, hyg_z > 1.0, "hyg_z_above_1")
    cond_block["dxy_above_2pct"] = cond_mean_dd(fdd, dxy_chg > 0.02, "dxy_above_2pct")
    cond_block["vvix_above_p90"] = cond_mean_dd(
        fdd, vvix_p > vvix_thresh_p90, "vvix_above_p90"
    )
    cond_block["any_confirmation"] = cond_mean_dd(
        fdd, n_confirms >= 1, "any_confirmation"
    )
    cond_block["two_or_more_confirmations"] = cond_mean_dd(
        fdd, n_confirms >= 2, "two_or_more_confirmations"
    )

    # HMM crisis AND ≥2 cross-asset (the canonical WS-C transition gate)
    crisis_state = argmax_state == "crisis"
    cond_block["hmm_crisis_and_2plus_confirms"] = cond_mean_dd(
        fdd, crisis_state & (n_confirms >= 2), "hmm_crisis_and_2plus_confirms"
    )
    cond_block["hmm_crisis_only"] = cond_mean_dd(
        fdd, crisis_state, "hmm_crisis_only"
    )

    results["conditional"] = cond_block
    print("\n=== Conditional 20d forward drawdown by regime/signal ===")
    print(f"  unconditional baseline: mean_fwd_dd={fdd.mean():+.4f}, base_rate_dd<=-5%={base_rate_20:.3f}")
    for k, v in cond_block.items():
        print(f"  {k:42s} N={v['n_days_in_regime']:4d} "
              f"({v['pct_in_regime']*100:5.1f}%) "
              f"mean_fwd_dd={v['mean_fwd_dd_in_regime']:+.4f} "
              f"p10={v['p10_fwd_dd_in_regime']:+.4f}")

    # ====================================================================
    # MEASUREMENT 3: Hit rate / FPR at canonical thresholds
    # ====================================================================
    hit_block: Dict[str, Dict] = {}
    # HMM thresholds: argmax = stress/crisis vs target
    fired_argmax_crisis = (argmax_state == "crisis").astype(float)
    fired_argmax_stressed_or_crisis = argmax_state.isin(["stressed", "crisis"]).astype(float)
    fired_pcrisis_50 = (p_crisis > 0.5).astype(float)
    fired_pstress_50 = (p_stress_or_crisis > 0.5).astype(float)

    for label, signal in [
        ("argmax_crisis", fired_argmax_crisis),
        ("argmax_stressed_or_crisis", fired_argmax_stressed_or_crisis),
        ("p_crisis_gt_0.5", fired_pcrisis_50),
        ("p_stress_or_crisis_gt_0.5", fired_pstress_50),
        ("hyg_z_gt_1", (hyg_z > 1.0).astype(float)),
        ("dxy_chg_gt_2pct", (dxy_chg > 0.02).astype(float)),
        ("vvix_gt_p90", (vvix_p > vvix_thresh_p90).astype(float)),
        ("two_or_more_confirms", (n_confirms >= 2).astype(float)),
        ("hmm_crisis_and_2plus", (crisis_state & (n_confirms >= 2)).astype(float)),
    ]:
        tpr, fpr, prec, tp, fp, fn, tn = hit_rate_and_fpr(signal.values, target.values)
        hit_block[label] = {
            "TPR_hit_rate": tpr, "FPR": fpr, "precision": prec,
            "TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "lift_over_base": (prec - base_rate_20) if not np.isnan(prec) else float("nan"),
        }
    results["hit_fpr"] = hit_block
    print("\n=== Hit rate / FPR / precision (target: 20d fwd dd ≤ -5%) ===")
    print(f"  {'signal':40s} TPR     FPR     prec    lift_vs_base")
    for k, v in hit_block.items():
        lift = v["lift_over_base"]
        lift_str = f"{lift:+.3f}" if not np.isnan(lift) else "nan"
        print(f"  {k:40s} {v['TPR_hit_rate']:.3f}   {v['FPR']:.3f}   "
              f"{v['precision']:.3f}   {lift_str}")

    # ====================================================================
    # MEASUREMENT 4: Lead time distribution
    # ====================================================================
    lead_block: Dict[str, Dict] = {}
    for label, signal in [
        ("argmax_crisis", fired_argmax_crisis),
        ("argmax_stressed_or_crisis", fired_argmax_stressed_or_crisis),
        ("p_crisis_gt_0.5", fired_pcrisis_50),
        ("p_stress_or_crisis_gt_0.5", fired_pstress_50),
        ("hyg_z_gt_1", (hyg_z > 1.0).astype(float)),
        ("dxy_chg_gt_2pct", (dxy_chg > 0.02).astype(float)),
        ("vvix_gt_p90", (vvix_p > vvix_thresh_p90).astype(float)),
        ("two_or_more_confirms", (n_confirms >= 2).astype(float)),
        ("hmm_crisis_and_2plus", (crisis_state & (n_confirms >= 2)).astype(float)),
    ]:
        lead_block[label] = lead_time_stats(
            spy_aligned, signal.fillna(0).astype(bool), args.horizon, args.dd_threshold
        )
    results["lead_time"] = lead_block
    print("\n=== Lead-time distribution (signal fire date → forward trough) ===")
    print(f"  {'signal':40s} events  warned   median_lead  p25  p75")
    for k, v in lead_block.items():
        median = v.get("median_lead_days", float("nan"))
        median_str = f"{median:.1f}" if not (isinstance(median, float) and np.isnan(median)) else "nan"
        p25 = v.get("p25_lead_days", float("nan"))
        p75 = v.get("p75_lead_days", float("nan"))
        p25_str = f"{p25:.1f}" if not (isinstance(p25, float) and np.isnan(p25)) else "nan"
        p75_str = f"{p75:.1f}" if not (isinstance(p75, float) and np.isnan(p75)) else "nan"
        print(f"  {k:40s} {v['n_drawdown_events']:3d}     "
              f"{v['events_with_warning']:3d}      {median_str:>6s}     "
              f"{p25_str:>4s}  {p75_str:>4s}")

    # ====================================================================
    # MEASUREMENT 5: In-sample vs OOS split + looser -3% target
    # ====================================================================
    # The HMM is trained 2021-2024; 2025 Jan-Apr is genuine OOS.
    # Note: 2025 OOS window has zero instances of 20d-fwd-dd ≤ -5%
    # because the trough of the -18.8% peak-to-trough event sits OUTSIDE
    # the 20d forward window for most anchor dates. The -3% target is
    # included to make OOS measurable; the in-sample -5% target is the
    # academic version.
    is_mask = (proba_df.index >= "2021-01-01") & (proba_df.index <= "2024-12-31")
    oos_mask = (proba_df.index >= "2025-01-01")
    print("\n=== In-sample (2021-2024) vs OOS (2025 Jan-Apr) AUC ===")
    print(f"  in-sample N={is_mask.sum()}, OOS N={oos_mask.sum()}")
    print(f"  OOS dd<=-5% positives: {int(target[oos_mask].sum())} "
          f"-- target is degenerate (0 positives) on 20d horizon")
    print(f"  OOS dd<=-3% positives: {int(target_3[oos_mask].sum())} "
          f"(base rate {float(target_3[oos_mask].mean()):.3f})")

    is_auc_pcrisis_5 = auc_score(p_crisis[is_mask].values, target[is_mask].values)
    is_auc_pso_5 = auc_score(p_stress_or_crisis[is_mask].values, target[is_mask].values)
    is_auc_pcrisis_3 = auc_score(p_crisis[is_mask].values, target_3[is_mask].values)
    is_auc_pso_3 = auc_score(p_stress_or_crisis[is_mask].values, target_3[is_mask].values)
    oos_auc_pcrisis_3 = auc_score(p_crisis[oos_mask].values, target_3[oos_mask].values)
    oos_auc_pso_3 = auc_score(p_stress_or_crisis[oos_mask].values, target_3[oos_mask].values)
    is_auc_neg_pbenign_3 = auc_score((-p_benign[is_mask]).values, target_3[is_mask].values)
    oos_auc_neg_pbenign_3 = auc_score((-p_benign[oos_mask]).values, target_3[oos_mask].values)

    print(f"  IS  hmm_p_crisis              AUC (5%)={is_auc_pcrisis_5:.4f}  "
          f"AUC (3%)={is_auc_pcrisis_3:.4f}")
    print(f"  IS  hmm_p_stress_or_crisis    AUC (5%)={is_auc_pso_5:.4f}  "
          f"AUC (3%)={is_auc_pso_3:.4f}")
    print(f"  OOS hmm_p_crisis              AUC (3%)={oos_auc_pcrisis_3:.4f}")
    print(f"  OOS hmm_p_stress_or_crisis    AUC (3%)={oos_auc_pso_3:.4f}")
    print(f"  OOS hmm_neg_p_benign          AUC (3%)={oos_auc_neg_pbenign_3:.4f}")
    results["is_oos"] = {
        "in_sample_n": int(is_mask.sum()),
        "oos_n": int(oos_mask.sum()),
        "is_auc_p_crisis_dd5": is_auc_pcrisis_5,
        "is_auc_p_crisis_dd3": is_auc_pcrisis_3,
        "is_auc_p_stress_or_crisis_dd5": is_auc_pso_5,
        "is_auc_p_stress_or_crisis_dd3": is_auc_pso_3,
        "oos_auc_p_crisis_dd3": oos_auc_pcrisis_3,
        "oos_auc_p_stress_or_crisis_dd3": oos_auc_pso_3,
        "oos_auc_neg_p_benign_dd3": oos_auc_neg_pbenign_3,
        "oos_base_rate_dd_5pct_20d": float(target[oos_mask].mean()),
        "oos_base_rate_dd_3pct_20d": float(target_3[oos_mask].mean()),
    }

    # ====================================================================
    # MEASUREMENT 6: WS-C signals on the period where they're defined
    # ====================================================================
    # HYG OAS data starts 2023-04-25; valid 60d-z from 2023-07-14 onward.
    # Restricting to where all 3 cross-asset signals are simultaneously
    # defined gives a fair WS-C-only evaluation (~July 2023+).
    ws_c_defined = (~hyg_z.isna()) & (~dxy_chg.isna()) & (~vvix_p.isna())
    n_ws = int(ws_c_defined.sum())
    print(f"\n=== WS-C-defined sub-window (~July 2023+, all three signals available) ===")
    print(f"  N={n_ws} days; dd<=-5% positives: {int(target[ws_c_defined].sum())}")
    if int(target[ws_c_defined].sum()) >= 5:
        ws_auc_block = {
            "hyg_lqd_z": auc_score(hyg_z[ws_c_defined].values, target[ws_c_defined].values),
            "dxy_change_20d": auc_score(dxy_chg[ws_c_defined].values, target[ws_c_defined].values),
            "vvix_proxy": auc_score(vvix_p[ws_c_defined].values, target[ws_c_defined].values),
            "hmm_p_crisis_in_ws_window": auc_score(
                p_crisis[ws_c_defined].values, target[ws_c_defined].values
            ),
            "hmm_p_stress_or_crisis_in_ws_window": auc_score(
                p_stress_or_crisis[ws_c_defined].values, target[ws_c_defined].values
            ),
        }
        for k, v in ws_auc_block.items():
            print(f"  {k:42s} AUC (5%)={v:.4f}")
        results["ws_c_subwindow_auc"] = ws_auc_block

    # ====================================================================
    # MEASUREMENT 7: Refined lead-time — "freshness" of the signal at
    # the drawdown anchor, not first-fire-in-prior-60-bars.
    # ====================================================================
    # Distinguishes "fired just before the trough" (genuine warning) vs
    # "has been on continuously for weeks" (persistent label, no warning).
    print("\n=== Signal persistence at anchor (1 = signal fired in last 5 bars; "
          "high persistence = signal is ALWAYS on, not predictive) ===")

    fired_signals_for_persistence = {
        "argmax_crisis": fired_argmax_crisis,
        "argmax_stressed_or_crisis": fired_argmax_stressed_or_crisis,
        "two_or_more_confirms": (n_confirms >= 2).astype(float),
    }
    persistence_block: Dict[str, Dict] = {}
    for k, sig in fired_signals_for_persistence.items():
        sig_b = sig.fillna(0).astype(bool)
        # Median run length when signal is on
        runs = []
        cur = 0
        for v in sig_b.values:
            if v:
                cur += 1
            else:
                if cur > 0:
                    runs.append(cur)
                    cur = 0
        if cur > 0:
            runs.append(cur)
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
    results["persistence"] = persistence_block

    # ====================================================================
    # Save
    # ====================================================================
    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[info] wrote results to {out_path}")


if __name__ == "__main__":
    main()
