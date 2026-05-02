"""
scripts/train_multires_hmm.py
=============================
Train Engine E's weekly + monthly HMM regime classifiers (Workstream C
slice 2 — 2026-05). Daily classifier already exists from slice 1
(`scripts/train_hmm_regime.py`); this script does NOT retrain or modify it.

Outputs:
  - engines/engine_e_regime/models/hmm_weekly_v1.pkl
  - engines/engine_e_regime/models/hmm_monthly_v1.pkl
  - data/research/hmm_multires_validation_2026_05.json — train + OOS LL
    comparison vs the existing daily HMM

Sample-size considerations:
  - Daily 2021-2024:    ~1005 obs → full covariance is fine
  - Weekly 2021-2024:    ~210 obs → full cov OK (3 states × 7 features)
  - Monthly 2021-2024:    ~48 obs → full cov degenerates; use diag covariance

Usage:
    python scripts/train_multires_hmm.py
    python scripts/train_multires_hmm.py --train-start 2021-01-01 --train-end 2024-12-31
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-start", default="2021-01-01")
    parser.add_argument("--train-end", default="2024-12-31")
    parser.add_argument("--test-start", default="2025-01-01")
    parser.add_argument("--test-end", default="2025-12-31")
    parser.add_argument(
        "--out-weekly",
        default=str(ROOT / "engines/engine_e_regime/models/hmm_weekly_v1.pkl"),
    )
    parser.add_argument(
        "--out-monthly",
        default=str(ROOT / "engines/engine_e_regime/models/hmm_monthly_v1.pkl"),
    )
    parser.add_argument(
        "--validation-json",
        default=str(ROOT / "data/research/hmm_multires_validation_2026_05.json"),
    )
    parser.add_argument(
        "--daily-pickle",
        default=str(ROOT / "engines/engine_e_regime/models/hmm_3state_v1.pkl"),
        help="Path to existing daily HMM (read-only — for OOS LL comparison)",
    )
    args = parser.parse_args()

    sys.path.insert(0, str(ROOT))
    from engines.engine_e_regime.macro_features import (
        build_multires_panels, FEATURE_COLUMNS,
    )
    from engines.engine_e_regime.hmm_classifier import HMMRegimeClassifier

    print("[TRAIN] Building multi-res feature panels (2018→2025)...")
    panels = build_multires_panels(
        start="2018-01-01", end=args.test_end, include_aux=False
    )
    for cad, p in panels.items():
        print(f"  {cad}: shape={p.shape}, NaN={int(p.isna().sum().sum())}")

    # Monthly cadence is data-limited: with 2021-2024 train window (= ~48 obs)
    # a 3-state, 7-feature HMM has more parameters than samples even with
    # diag covariance. We extend monthly's training horizon back to 2018-01
    # to get ~70 obs; weekly stays on 2021-2024 (~210 obs is fine for full
    # covariance). The deviation is documented in the audit doc.
    monthly_train_start = "2018-01-01"
    cadence_specs = [
        # (name, train_panel, test_panel, covariance_type, out_path, min_obs)
        (
            "weekly",
            panels["weekly"].loc[args.train_start:args.train_end].dropna(),
            panels["weekly"].loc[args.test_start:args.test_end].dropna(),
            "full",
            Path(args.out_weekly),
            100,
        ),
        (
            "monthly",
            panels["monthly"].loc[monthly_train_start:args.train_end].dropna(),
            panels["monthly"].loc[args.test_start:args.test_end].dropna(),
            "diag",  # too few obs for full covariance
            Path(args.out_monthly),
            48,  # data-limited: 7-feature HMM with diag-cov on monthly cadence
        ),
    ]

    validation = {
        "train_start": args.train_start,
        "train_end": args.train_end,
        "test_start": args.test_start,
        "test_end": args.test_end,
        "feature_columns": list(FEATURE_COLUMNS),
        "results": {},
    }

    for cad, train, test, cov, out_path, min_obs in cadence_specs:
        print(f"\n[{cad.upper()}] train rows={len(train)} test rows={len(test)} cov={cov} min_obs={min_obs}")
        if len(train) < min_obs:
            print(f"[{cad.upper()}][FATAL] insufficient training data ({len(train)} rows < {min_obs})")
            validation["results"][cad] = {"error": f"insufficient train rows: {len(train)} < {min_obs}"}
            continue

        clf = HMMRegimeClassifier(
            n_states=3, random_state=42, covariance_type=cov,
        )
        try:
            artifact = clf.fit(
                train,
                train_start=str(train.index.min().date()) if len(train) else args.train_start,
                train_end=args.train_end,
                min_obs=min_obs,
            )
        except Exception as exc:
            print(f"[{cad.upper()}][ERR] training failed: {exc}")
            validation["results"][cad] = {"error": str(exc)}
            continue

        train_ll = artifact.train_log_likelihood
        train_ll_per_obs = train_ll / max(1, len(train))
        if len(test) > 0:
            test_ll = clf.score(test)
            test_ll_per_obs = test_ll / max(1, len(test))
        else:
            test_ll = float("nan")
            test_ll_per_obs = float("nan")

        # State distribution on train + test
        train_proba = clf.predict_proba_sequence(train)
        train_dist = train_proba.idxmax(axis=1).value_counts().to_dict()
        if len(test) > 0:
            test_proba = clf.predict_proba_sequence(test)
            test_dist = test_proba.idxmax(axis=1).value_counts().to_dict()
        else:
            test_dist = {}

        print(
            f"[{cad.upper()}] train_ll={train_ll:.2f} ({train_ll_per_obs:.3f}/obs) "
            f"test_ll={test_ll:.2f} ({test_ll_per_obs:.3f}/obs)"
        )
        print(f"[{cad.upper()}] train state distribution: {train_dist}")
        print(f"[{cad.upper()}] test  state distribution: {test_dist}")

        # Persist as the standard pickle artifact (use the same on-disk
        # contract as scripts/train_hmm_regime.py — i.e. pickle the
        # HMMTrainingArtifact directly so HMMRegimeClassifier.load() works).
        out_path.parent.mkdir(parents=True, exist_ok=True)
        import pickle
        with open(out_path, "wb") as f:
            pickle.dump(artifact, f)
        print(f"[{cad.upper()}] persisted to {out_path}")

        validation["results"][cad] = {
            "covariance_type": cov,
            "n_train_obs": int(len(train)),
            "n_test_obs": int(len(test)),
            "train_log_likelihood": float(train_ll),
            "train_ll_per_obs": float(train_ll_per_obs),
            "test_log_likelihood": float(test_ll) if np.isfinite(test_ll) else None,
            "test_ll_per_obs": float(test_ll_per_obs) if np.isfinite(test_ll_per_obs) else None,
            "train_state_distribution": {str(k): int(v) for k, v in train_dist.items()},
            "test_state_distribution": {str(k): int(v) for k, v in test_dist.items()},
            "out_pickle": str(out_path.relative_to(ROOT)),
        }

    # Daily comparison row (read-only — no retrain). Score on the same
    # training and test panels used for daily slice 1.
    print("\n[DAILY] (read-only) scoring existing daily HMM for comparison...")
    daily_path = Path(args.daily_pickle)
    if daily_path.exists():
        try:
            daily_clf = HMMRegimeClassifier.load(daily_path)
            daily_train = panels["daily"].loc[args.train_start:args.train_end].dropna()
            daily_test = panels["daily"].loc[args.test_start:args.test_end].dropna()
            d_train_ll = daily_clf.score(daily_train)
            d_test_ll = daily_clf.score(daily_test)
            validation["results"]["daily"] = {
                "covariance_type": "full",
                "n_train_obs": int(len(daily_train)),
                "n_test_obs": int(len(daily_test)),
                "train_log_likelihood": float(d_train_ll),
                "train_ll_per_obs": float(d_train_ll / max(1, len(daily_train))),
                "test_log_likelihood": float(d_test_ll),
                "test_ll_per_obs": float(d_test_ll / max(1, len(daily_test))),
                "out_pickle": str(daily_path.relative_to(ROOT)),
                "note": "Pre-existing artifact from slice 1 — not retrained by this script",
            }
            print(
                f"[DAILY] train_ll={d_train_ll:.2f} "
                f"({d_train_ll / max(1, len(daily_train)):.3f}/obs) "
                f"test_ll={d_test_ll:.2f} ({d_test_ll / max(1, len(daily_test)):.3f}/obs)"
            )
        except Exception as exc:
            print(f"[DAILY] scoring failed: {exc}")
            validation["results"]["daily"] = {"error": str(exc)}
    else:
        print(f"[DAILY] artifact missing at {daily_path}; comparison skipped")

    # --- Decide tradeoff summary ---
    print("\n[SUMMARY] cadence vs OOS log-likelihood / observation:")
    print(f"  {'cadence':<10} {'cov':<8} {'n_test':>7} {'test_ll/obs':>14}")
    for cad, r in validation["results"].items():
        if "error" in r:
            print(f"  {cad:<10} ERROR: {r['error']}")
        else:
            test_ll_obs = r.get("test_ll_per_obs")
            cov = r.get("covariance_type", "?")
            n_test = r.get("n_test_obs", 0)
            test_str = f"{test_ll_obs:.3f}" if test_ll_obs is not None else "n/a"
            print(f"  {cad:<10} {cov:<8} {n_test:>7d} {test_str:>14}")

    out_json = Path(args.validation_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w") as f:
        json.dump(validation, f, indent=2)
    print(f"\n[VALIDATION] wrote {out_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
