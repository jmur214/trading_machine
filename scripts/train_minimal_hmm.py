"""
train_minimal_hmm — train a 3-state HMM on the leading-feature subset.

E-rebuild phase-1 dispatch (2026-05-07). Three variants share a common
training window so feature-set differences (not data-quantity differences)
drive the comparison.

Variants
--------
  A: spy_vol_20d, yield_curve_spread, credit_spread_baa_aaa, dollar_ret_63d
     (4 long-history FRED features — drops spy_ret_5d, tlt_ret_20d,
      vix_level which are coincident by construction)

  B: A + hyg_ig_oas
     (HY OAS minus IG OAS — credit-quality slope from FRED)

  C: B + copper_gold_ratio + xlp_xly_ratio
     (intermarket relative strength from yfinance — copper/gold +
      defensive/cyclical sector rotation)

Training window
---------------
The HY-IG OAS series (BAMLH0A0HYM2 + BAMLC0A0CM) has only ~2023-05-08
onward of free-tier history; ICE BofA shortened the FRED feed in mid-2023.
For an apples-to-apples comparison across variants, all three are trained
on the SAME window: 2023-10-01 → 2024-12-31. This window:
  - is wide enough for 3-state HMM Gaussian emission fitting (~315 obs)
  - gives every variant the same data budget
  - reserves 2025-01-01 → 2025-04-30 as untouched OOS (which contains
    the early-April 2025 -18.8% drawdown event)

Output
------
  data/macro/minimal_hmm_states_<variant>.parquet — regime label time series
  engines/engine_e_regime/models/hmm_minimal_<variant>_v1.pkl — trained model
  data/research/hmm_minimal_<variant>_train_2026_05.json — train metadata

Usage
-----
  python scripts/train_minimal_hmm.py --variant A
  python scripts/train_minimal_hmm.py --variant B
  python scripts/train_minimal_hmm.py --variant C
  python scripts/train_minimal_hmm.py --variant all   # train all three

Each run is deterministic (random_state=42).
"""
from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


# Variant definitions ---------------------------------------------------------
# Each variant is a tuple of (feature_list, build_panel_kwargs).
VARIANTS = {
    "A": (
        ("spy_vol_20d", "yield_curve_spread", "credit_spread_baa_aaa",
         "dollar_ret_63d"),
        {"include_hyg_ig": False, "include_leading_rs": False},
    ),
    "B": (
        ("spy_vol_20d", "yield_curve_spread", "credit_spread_baa_aaa",
         "dollar_ret_63d", "hyg_ig_oas"),
        {"include_hyg_ig": True, "include_leading_rs": False},
    ),
    "C": (
        ("spy_vol_20d", "yield_curve_spread", "credit_spread_baa_aaa",
         "dollar_ret_63d", "hyg_ig_oas", "copper_gold_ratio", "xlp_xly_ratio"),
        {"include_hyg_ig": True, "include_leading_rs": True},
    ),
}


def train_one(
    variant: str,
    train_start: str,
    train_end: str,
    test_start: str,
    test_end: str,
) -> dict:
    import sys
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from engines.engine_e_regime.hmm_classifier import HMMRegimeClassifier
    from engines.engine_e_regime.macro_features import build_feature_panel

    if variant not in VARIANTS:
        raise ValueError(f"unknown variant {variant!r}; options: {list(VARIANTS)}")
    features, kwargs = VARIANTS[variant]

    # Build panel over (train_start - 1y warm-up) to test_end.
    warmup_start = (
        pd.Timestamp(train_start) - pd.Timedelta(days=400)
    ).strftime("%Y-%m-%d")
    panel = build_feature_panel(
        root=ROOT, start=warmup_start, end=test_end, **kwargs,
    )
    panel = panel[list(features)]

    train_panel = panel.loc[train_start:train_end].dropna()
    test_panel = panel.loc[test_start:test_end].dropna()

    print(f"\n[VARIANT {variant}] features ({len(features)}): {features}")
    print(f"[VARIANT {variant}] train rows={len(train_panel)} test rows={len(test_panel)}")
    if len(train_panel) < 100:
        raise RuntimeError(
            f"variant {variant}: insufficient training data ({len(train_panel)})"
        )

    clf = HMMRegimeClassifier(
        n_states=3, feature_names=tuple(features), random_state=42,
    )
    artifact = clf.fit(
        train_panel, train_start=train_start, train_end=train_end
    )

    # Persist model artifact.
    model_path = (
        ROOT / "engines" / "engine_e_regime" / "models"
        / f"hmm_minimal_{variant}_v1.pkl"
    )
    model_path.parent.mkdir(parents=True, exist_ok=True)
    with open(model_path, "wb") as f:
        pickle.dump(artifact, f)
    print(f"[VARIANT {variant}] persisted model -> {model_path}")

    # Predict regime states across the FULL panel (train + test). The output
    # is (idx, state_label, p_benign, p_stressed, p_crisis).
    full_panel = panel.dropna()
    proba = clf.predict_proba_sequence(full_panel)
    argmax = proba.idxmax(axis=1)
    states = pd.DataFrame({
        "regime": argmax,
        **{c: proba[c] for c in proba.columns},
    }, index=full_panel.index)
    states.index.name = "date"

    states_path = ROOT / "data" / "macro" / f"minimal_hmm_states_{variant}.parquet"
    states_path.parent.mkdir(parents=True, exist_ok=True)
    states.to_parquet(states_path)
    print(f"[VARIANT {variant}] persisted states -> {states_path}")

    # Z-scored state means
    means = clf._hmm.means_
    state_means = {
        clf._state_label_for_idx[i]: dict(zip(features, [float(x) for x in means[i]]))
        for i in range(3)
    }

    # State distribution
    counts_train = argmax.loc[train_start:train_end].value_counts().to_dict()
    counts_test = argmax.loc[test_start:test_end].value_counts().to_dict()

    summary = {
        "variant": variant,
        "features": list(features),
        "train_start": train_start,
        "train_end": train_end,
        "test_start": test_start,
        "test_end": test_end,
        "n_train_obs": int(len(train_panel)),
        "n_test_obs": int(len(test_panel)),
        "train_log_likelihood": float(artifact.train_log_likelihood),
        "state_distribution_train": {str(k): int(v) for k, v in counts_train.items()},
        "state_distribution_test": {str(k): int(v) for k, v in counts_test.items()},
        "state_means_zscored": state_means,
        "model_path": str(model_path),
        "states_path": str(states_path),
    }

    research_dir = ROOT / "data" / "research"
    research_dir.mkdir(parents=True, exist_ok=True)
    out_json = research_dir / f"hmm_minimal_{variant}_train_2026_05.json"
    out_json.write_text(json.dumps(summary, indent=2))
    print(f"[VARIANT {variant}] wrote summary -> {out_json}")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="all", choices=["A", "B", "C", "all"])
    ap.add_argument("--train-start", default="2023-10-01",
                    help="Common train window start. HY-IG OAS only has data "
                         "from ~2023-05-08, so this is the earliest practical "
                         "shared start that gives ~315 train obs.")
    ap.add_argument("--train-end", default="2024-12-31")
    ap.add_argument("--test-start", default="2025-01-01")
    ap.add_argument("--test-end", default="2025-04-30")
    args = ap.parse_args()

    variants = ["A", "B", "C"] if args.variant == "all" else [args.variant]
    summaries = {}
    for v in variants:
        summaries[v] = train_one(
            v, args.train_start, args.train_end,
            args.test_start, args.test_end,
        )

    # Write combined summary
    if args.variant == "all":
        out = ROOT / "data" / "research" / "hmm_minimal_all_variants_train_2026_05.json"
        out.write_text(json.dumps(summaries, indent=2))
        print(f"\n[ALL] wrote combined summary -> {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
