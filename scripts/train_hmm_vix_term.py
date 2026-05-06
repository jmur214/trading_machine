"""
train_hmm_vix_term — train a 3-state HMM on the rebuilt feature panel
(slice 1: original 7 features + 3 VIX-term-structure features).

Mirrors `scripts/train_hmm_regime.py` but flips `include_vix_term=True`
and writes a separate model artifact so the original 3-state model stays
untouched. The slice-1 model is the one fed to `scripts/validate_regime_signals_vix_term.py`.

Output:
    engines/engine_e_regime/models/hmm_3state_vix_term_v1.pkl
    data/research/hmm_kstate_vix_term_validation_2026_05.json

Usage:
    python scripts/train_hmm_vix_term.py
    python scripts/train_hmm_vix_term.py --train-start 2021-01-01 --train-end 2024-12-31
"""
from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-start", default="2021-01-01")
    parser.add_argument("--train-end", default="2024-12-31")
    parser.add_argument("--test-start", default="2025-01-01")
    parser.add_argument("--test-end", default="2025-04-30")
    parser.add_argument(
        "--out-pickle",
        default=str(ROOT / "engines/engine_e_regime/models/hmm_3state_vix_term_v1.pkl"),
    )
    parser.add_argument(
        "--validation-json",
        default=str(ROOT / "data/research/hmm_kstate_vix_term_validation_2026_05.json"),
    )
    args = parser.parse_args()

    import sys
    sys.path.insert(0, str(ROOT))
    from engines.engine_e_regime.macro_features import (
        build_feature_panel, FEATURE_COLUMNS, VIX_TERM_FEATURES,
    )
    from engines.engine_e_regime.hmm_classifier import HMMRegimeClassifier

    full_features = tuple(FEATURE_COLUMNS) + tuple(VIX_TERM_FEATURES)
    print(f"[TRAIN-VIX] feature set ({len(full_features)} features): {full_features}")

    print("[TRAIN-VIX] Building feature panel with VIX term-structure...")
    panel = build_feature_panel(
        root=ROOT, start="2020-04-01", end=args.test_end, include_vix_term=True
    )
    print(f"[TRAIN-VIX] panel shape={panel.shape}")
    print(f"[TRAIN-VIX] NaN per col:\n{panel.isna().sum()}")

    train_panel = panel.loc[args.train_start:args.train_end].dropna()
    test_panel = panel.loc[args.test_start:args.test_end].dropna()
    print(f"[TRAIN-VIX] train rows={len(train_panel)} test rows={len(test_panel)}")
    if len(train_panel) < 100:
        print(f"[TRAIN-VIX][FATAL] insufficient training data: {len(train_panel)}")
        return 1

    validation_results = {
        "train_start": args.train_start,
        "train_end": args.train_end,
        "test_start": args.test_start,
        "test_end": args.test_end,
        "n_train_obs": int(len(train_panel)),
        "n_test_obs": int(len(test_panel)),
        "feature_columns": list(full_features),
        "results_by_k": {},
    }

    for k in (2, 3, 4):
        print(f"\n[K={k}] Training {k}-state HMM with VIX term features...")
        clf = HMMRegimeClassifier(
            n_states=k, feature_names=full_features, random_state=42,
        )
        try:
            artifact = clf.fit(
                train_panel, train_start=args.train_start, train_end=args.train_end
            )
        except Exception as exc:
            print(f"[K={k}][ERR] training failed: {exc}")
            validation_results["results_by_k"][str(k)] = {"error": str(exc)}
            continue
        train_ll = artifact.train_log_likelihood
        test_ll = clf.score(test_panel)

        train_ll_per_obs = train_ll / max(1, len(train_panel))
        test_ll_per_obs = test_ll / max(1, len(test_panel))

        p = len(full_features)
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

        if k == 3:
            out_path = Path(args.out_pickle)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with open(out_path, "wb") as f:
                pickle.dump(artifact, f)
            print(f"[K={k}] persisted to {out_path}")

            train_proba = clf.predict_proba_sequence(train_panel)
            argmax_state = train_proba.idxmax(axis=1)
            counts = argmax_state.value_counts().to_dict()
            test_proba = clf.predict_proba_sequence(test_panel)
            argmax_test = test_proba.idxmax(axis=1)
            counts_test = argmax_test.value_counts().to_dict()
            print(f"[K={k}] train state distribution: {counts}")
            print(f"[K={k}] test  state distribution: {counts_test}")
            validation_results["state_distribution_train"] = {
                str(name): int(v) for name, v in counts.items()
            }
            validation_results["state_distribution_test"] = {
                str(name): int(v) for name, v in counts_test.items()
            }

            # Inspect z-scored state means for the new VIX features so we
            # can see what the HMM is using each state to summarize.
            means = clf._hmm.means_  # shape (n_states, n_features)
            print(f"[K={k}] z-scored state means by feature:")
            for state_idx in range(k):
                label = clf._state_label_for_idx[state_idx]
                row = means[state_idx]
                summary = ", ".join(
                    f"{full_features[i]}={row[i]:+.2f}" for i in range(len(full_features))
                )
                print(f"  state[{state_idx}] -> {label}: {summary}")
            validation_results["state_means_zscored"] = {
                clf._state_label_for_idx[i]: dict(zip(full_features, [float(x) for x in means[i]]))
                for i in range(k)
            }

    valid_ks = {k: r for k, r in validation_results["results_by_k"].items() if "error" not in r}
    if valid_ks:
        best_test_ll_per_obs = max(valid_ks.items(), key=lambda kv: kv[1]["test_ll_per_obs"])
        best_bic = min(valid_ks.items(), key=lambda kv: kv[1]["bic_train"])
        validation_results["best_test_ll_per_obs_k"] = best_test_ll_per_obs[0]
        validation_results["best_bic_k"] = best_bic[0]
        print(f"\n[VALIDATION] Best test LL per obs: K={best_test_ll_per_obs[0]} "
              f"({best_test_ll_per_obs[1]['test_ll_per_obs']:.3f})")
        print(f"[VALIDATION] Best BIC (train): K={best_bic[0]} "
              f"({best_bic[1]['bic_train']:.2f})")

    out_json = Path(args.validation_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    with open(out_json, "w") as f:
        json.dump(validation_results, f, indent=2)
    print(f"\n[VALIDATION] wrote {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
