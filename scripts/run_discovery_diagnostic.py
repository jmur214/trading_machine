"""
scripts/run_discovery_diagnostic.py
===================================
Discovery-cycle diagnostic harness for the discovery-diagnostic branch.

Runs a deliberately-tight Discovery cycle (cap 15 candidates, 1-year window,
per-candidate wall-time timeout) under the determinism harness, capturing
per-candidate per-gate jsonl. The downstream audit doc (D3) reads the jsonl
and produces the histogram of where candidates die.

NOT for production use. Lives only on the discovery-diagnostic branch and
is intended to inform the next-fix-target decision for Engine D.

Usage:
    PYTHONHASHSEED=0 python -m scripts.run_discovery_diagnostic
    PYTHONHASHSEED=0 python -m scripts.run_discovery_diagnostic --window 2024
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_isolated import (
    isolated,
    save_anchor,
    ISOLATED_ANCHOR,
)


def _reexec_if_hashseed_unset() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(sys.executable, [sys.executable, "-m", "scripts.run_discovery_diagnostic", *sys.argv[1:]])


WINDOWS = {
    "2024": ("2024-01-01", "2024-12-31"),
    "2023": ("2023-01-01", "2023-12-31"),
    "2024H2": ("2024-07-01", "2024-12-31"),
    "2024H1": ("2024-01-01", "2024-06-30"),
}


def main() -> int:
    _reexec_if_hashseed_unset()

    parser = argparse.ArgumentParser()
    parser.add_argument("--window", choices=sorted(WINDOWS.keys()), default="2024",
                        help="Backtest+gate window. 2024=full year, 2024H2=last 6 months.")
    parser.add_argument("--batch", type=int, default=15,
                        help="Cap on candidate count for the diagnostic cycle.")
    parser.add_argument("--timeout", type=int, default=1800,
                        help="Per-candidate wall-time timeout in seconds (0=disabled).")
    parser.add_argument("--out-dir", default="docs/Audit",
                        help="Directory for the per-candidate jsonl emission.")
    parser.add_argument("--no-isolated", action="store_true",
                        help="Skip the determinism harness (only for debugging the script itself).")
    args = parser.parse_args()

    start, end = WINDOWS[args.window]
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / f"discovery_diagnostic_run_2026_05_{timestamp}.jsonl"

    print(f"[DIAG] window: {start} → {end}")
    print(f"[DIAG] candidate cap: {args.batch}")
    print(f"[DIAG] per-candidate timeout: {args.timeout}s")
    print(f"[DIAG] output jsonl: {jsonl_path}")

    if not args.no_isolated and not ISOLATED_ANCHOR.exists():
        print("[DIAG] No anchor at data/governor/_isolated_anchor — saving one now.")
        save_anchor()

    # Hand instrumentation flags to ModeController via env (avoids changing
    # the public run_backtest signature for diagnostic-only knobs).
    os.environ["DISCOVERY_DIAG_LOG"] = str(jsonl_path)
    os.environ["DISCOVERY_DIAG_BATCH"] = str(args.batch)
    os.environ["DISCOVERY_DIAG_TIMEOUT_SEC"] = str(args.timeout)

    from orchestration.mode_controller import ModeController
    mc = ModeController(ROOT, env="prod")

    def _do_run() -> dict:
        return mc.run_backtest(
            mode="prod",
            fresh=False,
            no_governor=False,
            reset_governor=True,
            alpha_debug=False,
            override_start=start,
            override_end=end,
            discover=True,
        )

    t0 = time.time()
    if args.no_isolated:
        summary = _do_run()
    else:
        with isolated():
            summary = _do_run()
    elapsed = time.time() - t0

    print(f"\n[DIAG] backtest+discovery complete in {elapsed/60:.1f} min")
    if jsonl_path.exists():
        n_lines = sum(1 for _ in jsonl_path.open())
        print(f"[DIAG] jsonl records: {n_lines}")
    print(f"[DIAG] summary keys: {sorted(list((summary or {}).keys()))[:10]}")
    print(f"[DIAG] jsonl: {jsonl_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
