"""
scripts/train_hmm_regime.py
===========================
Train Engine E's HMM regime classifier on 2021-2024 data and persist
to engines/engine_e_regime/models/hmm_3state_v1.pkl.

Also runs k-state log-likelihood comparison (k=2, 3, 4) on a 2025
holdout to validate that 3-state is the right baseline. Writes
results to data/research/hmm_kstate_validation_2026_05.json.

Usage:
    python scripts/train_hmm_regime.py
    python scripts/train_hmm_regime.py --train-start 2021-01-01 --train-end 2024-12-31
"""
from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--out-pickle",
                        default=str(ROOT / "engines/engine_e_regime/models/hmm_3state_v1.pkl"))
    parser.add_argument("--validation-json",
                        default=str(ROOT / "data/research/hmm_kstate_validation_2026_05.json"))
    args = parser.parse_args()

    import sys
    sys.path.insert(0, str(ROOT))
    from engines.engine_e_regime.macro_features import (
        build_feature_panel, FEATURE_COLUMNS,
    )
    from engines.engine_e_regime.hmm_classifier import HMMRegimeClassifier

    print("[TRAIN] Building feature panel...")
    panel = build_feature_panel(root=ROOT, start="2018-01-01", end=args.test_end)
    print(f"[TRAIN] panel shape={panel.shape}, NaN per col:\n{panel.isna().sum()}")

    train_panel = panel.loc[args.train_start:args.train_end].dropna()
    test_panel = panel.loc[args.test_start:args.test_end].dropna()
    print(f"[TRAIN] train rows={len(train_panel)} test rows={len(test_panel)}")
    if len(train_panel) < 100:
        print(f"[TRAIN][FATAL] insufficient training data: {len(train_panel)}")
        return 1
    if len(test_panel) < 20:
        print(f"[TRAIN][WARN] sparse holdout: {len(test_panel)} — k-state validation may be noisy")

    # --- K-state validation ---
    validation_results = {
        "train_start": args.train_start,
        "train_end": args.train_end,
        "test_start": args.test_start,
        "test_end": args.test_end,
        "n_train_obs": int(len(train_panel)),
        "n_test_obs": int(len(test_panel)),
        "feature_columns": list(FEATURE_COLUMNS),
        "results_by_k": {},
    }

    for k in (2, 3, 4):
        print(f"\n[K={k}] Training {k}-state HMM...")
        clf = HMMRegimeClassifier(n_states=k, random_state=42)
        try:
            artifact = clf.fit(train_panel, train_start=args.train_start, train_end=args.train_end)
        except Exception as exc:
            print(f"[K={k}][ERR] training failed: {exc}")
            validation_results["results_by_k"][str(k)] = {"error": str(exc)}
            continue
        train_ll = artifact.train_log_likelihood
        test_ll = clf.score(test_panel)

        # Per-observation log-likelihood (lets us compare across k fairly,
        # though not BIC-corrected)
        train_ll_per_obs = train_ll / max(1, len(train_panel))
        test_ll_per_obs = test_ll / max(1, len(test_panel))

        # BIC = -2*ll + p*log(n) — penalizes parameter count.
        # GaussianHMM(full cov) params ~= k*(k-1) + k*p + k*p*(p+1)/2
        # where p = n_features. Use Schwarz BIC (lower is better).
        p = len(FEATURE_COLUMNS)
        n_params = k * (k - 1) + k * p + k * p * (p + 1) // 2
        bic_train = -2.0 * train_ll + n_params * np.log(len(train_panel))

        print(f"[K={k}] train_ll={train_ll:.2f} ({train_ll_per_obs:.3f}/obs) "
              f"test_ll={test_ll:.2f} ({test_ll_per_obs:.3f}/obs) "
              f"BIC_train={bic_train:.2f}")

        validation_results["results_by_k"][str(k)] = {
            "train_log_likelihood": float(train_ll),
            "test_log_likelihood": float(test_ll),
            "train_ll_per_obs": float(train_ll_per_obs),
            "test_ll_per_obs": float(test_ll_per_obs),
            "n_params": int(n_params),
            "bic_train": float(bic_train),
        }

        # Save the 3-state model as the production artifact
        if k == 3:
            out_path = Path(args.out_pickle)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            import pickle
            with open(out_path, "wb") as f:
                pickle.dump(artifact, f)
            print(f"[K={k}] persisted to {out_path}")

            # Inspect state sample distribution
            train_proba = clf.predict_proba_sequence(train_panel)
            argmax_state = train_proba.idxmax(axis=1)
            counts = argmax_state.value_counts().to_dict()
            test_proba = clf.predict_proba_sequence(test_panel)
            argmax_test = test_proba.idxmax(axis=1)
            counts_test = argmax_test.value_counts().to_dict()
            print(f"[K={k}] train state distribution: {counts}")
            print(f"[K={k}] test  state distribution: {counts_test}")
            validation_results["state_distribution_train"] = {
                str(k): int(v) for k, v in counts.items()
            }
            validation_results["state_distribution_test"] = {
                str(k): int(v) for k, v in counts_test.items()
            }

    # --- Decide which K wins ---
    # Lower BIC on train + higher per-obs LL on test = preferred
    valid_ks = {k: r for k, r in validation_results["results_by_k"].items() if "error" not in r}
    if valid_ks:
        best_test_ll_per_obs = max(valid_ks.items(), key=lambda kv: kv[1]["test_ll_per_obs"])
        best_bic = min(valid_ks.items(), key=lambda kv: kv[1]["bic_train"])
        validation_results["best_test_ll_per_obs_k"] = best_test_ll_per_obs[0]
        validation_results["best_bic_k"] = best_bic[0]
        print(f"\n[VALIDATION] Best test LL per obs: K={best_test_ll_per_obs[0]} "
              f"({best_test_ll_per_obs[1]['test_ll_per_obs']:.3f})")
        print(f"[VALIDATION] Best BIC (train): K={best_bic[0]} ({best_bic[1]['bic_train']:.2f})")

    out_json = Path(args.validation_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w") as f:
        json.dump(validation_results, f, indent=2)
    print(f"\n[VALIDATION] wrote {out_json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
