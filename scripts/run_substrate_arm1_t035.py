"""scripts/run_substrate_arm1_t035.py
======================================
T-2026-05-12-035: substrate-honest Arm 1 re-measurement with the
cockpit metrics-pipeline fix (T-034) applied.

T-002 reported Arm 1 mean Sharpe 0.270 (anchored as the engines-first
baseline). Director's correction in the T-034 inbox: Arm 1's per-year
cells had small MDDs, so the cockpit bug barely fires there — the
expected shift is ~0.02-0.05 from T-002's reported number, not the
much larger shift the STR 2022 cell saw.

This dispatch verifies that empirically. Single-arm (Arm 1 only) since
the question is "what's the corrected 0.270 baseline?" not Arm 1
vs Arm 2.

Reuses `scripts.run_substrate_arms._execute_grid` directly to keep
the harness contract identical to T-002. Only difference: results path
points to a fresh location so the original T-002 output is preserved.

Output:
  data/measurements/substrate_arm1_cockpit_fixed_2026_05_12/arm1_results.json
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_substrate_arms import (  # noqa: E402
    ARM1_EDGES, DEFAULT_YEARS, _execute_grid,
)

RESULTS_DIR = ROOT / "data" / "measurements" / "substrate_arm1_cockpit_fixed_2026_05_12"


def _reexec_if_hashseed_unset() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(
            sys.executable,
            [sys.executable, "-m", "scripts.run_substrate_arm1_t035", *sys.argv[1:]],
        )


def main() -> int:
    _reexec_if_hashseed_unset()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=str,
                        default=",".join(str(y) for y in DEFAULT_YEARS),
                        help="Comma-separated years (default 2021-2025).")
    parser.add_argument("--reps", type=int, default=3,
                        help="Reps per (year) (default 3).")
    args = parser.parse_args()

    years = [int(y.strip()) for y in args.years.split(",") if y.strip()]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    results_path = RESULTS_DIR / "arm1_results.json"

    print(f"[T-035] Arm 1 cockpit-fixed re-measurement", flush=True)
    print(f"[T-035] Years: {years}", flush=True)
    print(f"[T-035] Reps: {args.reps}", flush=True)
    print(f"[T-035] Edges: {ARM1_EDGES}", flush=True)
    print(f"[T-035] Output: {results_path}", flush=True)

    _execute_grid(
        arm_label="arm1",
        years=years,
        reps=args.reps,
        exact_edge_ids=ARM1_EDGES,
        hmm_on=False,
        results_path=results_path,
    )
    print(f"[T-035] Complete — see {results_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
