"""
scripts/run_discovery_diagnostic_standalone.py
==============================================
Tight standalone variant of the discovery diagnostic.

Skips the in-sample backtest + hunt phase (TreeScanner) entirely. Loads a
slim universe of cached price data and runs `DiscoveryEngine.generate_candidates`
followed by per-candidate validate_candidate, capturing the per-gate jsonl
that the audit doc consumes.

Why not the full pipeline: under prod-109 + full hunt, TreeScanner alone
runs ~20+ minutes silently before any candidate is validated. For "where
do candidates die?", template-mutation + GA-random candidates are
representative of the gauntlet's typical input. Hunt-rule candidates
share the same Gate 1 path; their expected outcome is documented as
"all fail Gate 1 due to RuleBasedEdge feature-engineering bug" in
docs/Audit/health_check.md. We capture the rest.

Usage:
    PYTHONHASHSEED=0 python scripts/run_discovery_diagnostic_standalone.py \\
        --tickers 30 --window 2024H2 --batch 15 --timeout 1500
"""
from __future__ import annotations

import argparse
import json
import os
import random
import signal
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _reexec_if_hashseed_unset() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(sys.executable, [sys.executable, *sys.argv])


WINDOWS = {
    "2024H2": ("2024-07-01", "2024-12-31"),
    "2024H1": ("2024-01-01", "2024-06-30"),
    "2024Q4": ("2024-10-01", "2024-12-31"),
}


def load_data_map(n_tickers: int, start: str, end: str) -> Dict[str, pd.DataFrame]:
    """Load slim ticker set from data/processed/*_1d.csv.

    Warmup: pulls 365 days before `start`.
    """
    proc = ROOT / "data" / "processed"
    universe_path = ROOT / "config" / "backtest_settings.json"
    with universe_path.open() as f:
        cfg = json.load(f)
    tickers_all = cfg.get("tickers", [])
    # Take the first N tickers for determinism (seeded sample would be ok too).
    chosen = tickers_all[:n_tickers]
    fetch_start = (pd.to_datetime(start) - pd.Timedelta(days=365)).strftime("%Y-%m-%d")

    dm: Dict[str, pd.DataFrame] = {}
    for tk in chosen:
        p = proc / f"{tk}_1d.csv"
        if not p.exists():
            continue
        try:
            df = pd.read_csv(p, index_col=0, parse_dates=True)
            df = df.loc[(df.index >= fetch_start) & (df.index <= end)]
            if len(df) >= 100:
                dm[tk] = df
        except Exception as e:
            print(f"[DIAG] could not load {tk}: {e}")
    print(f"[DIAG] loaded {len(dm)} tickers ({fetch_start} → {end})")
    return dm


def emit_timeout(jsonl_path: Path, cand: dict, t_start: float) -> None:
    rec = {
        "candidate_id": cand.get("edge_id", "?"),
        "module": cand.get("module", "?"),
        "class": cand.get("class", "?"),
        "category": cand.get("category", "?"),
        "origin": cand.get("origin", "?"),
        "wall_seconds_total": round(time.time() - t_start, 3),
        "first_failed_gate": "timeout",
        "error": "timeout",
        "metrics": {},
        "gate_passed": {},
        "passed_all_gates": False,
    }
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with jsonl_path.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def main() -> int:
    _reexec_if_hashseed_unset()
    random.seed(0)

    parser = argparse.ArgumentParser()
    parser.add_argument("--tickers", type=int, default=30,
                        help="Slim universe size (first N from prod backtest_settings).")
    parser.add_argument("--window", choices=sorted(WINDOWS.keys()), default="2024H2")
    parser.add_argument("--batch", type=int, default=15)
    parser.add_argument("--timeout", type=int, default=1500)
    parser.add_argument("--n-mutations", type=int, default=2,
                        help="Per-template mutation count. Total candidates ≈ 9 * n_mutations + N_ga.")
    parser.add_argument("--out-dir", default="docs/Audit")
    args = parser.parse_args()

    start, end = WINDOWS[args.window]
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / f"discovery_diagnostic_run_2026_05_{timestamp}.jsonl"

    print(f"[DIAG] window: {start} → {end}")
    print(f"[DIAG] tickers: {args.tickers}")
    print(f"[DIAG] batch cap: {args.batch}")
    print(f"[DIAG] per-candidate timeout: {args.timeout}s")
    print(f"[DIAG] out: {jsonl_path}")

    dm = load_data_map(args.tickers, start, end)
    if not dm:
        print("[DIAG] empty data_map — abort")
        return 2

    from engines.engine_d_discovery.discovery import DiscoveryEngine
    eng = DiscoveryEngine(
        registry_path=str(ROOT / "data" / "governor" / "edges.yml"),
        processed_data_dir=str(ROOT / "data" / "processed"),
    )

    candidates = eng.generate_candidates(n_mutations=args.n_mutations)
    print(f"[DIAG] generated {len(candidates)} candidates (template mutations + GA composite)")

    batch = candidates[:args.batch]
    print(f"[DIAG] running {len(batch)} (cap={args.batch})\n")

    n_done = 0
    n_passed = 0
    n_timeout = 0
    n_error = 0

    for i, cand in enumerate(batch, 1):
        cand_id = cand.get("edge_id", f"unknown_{i}")
        cand_class = cand.get("class", "?")
        print(f"[DIAG] [{i}/{len(batch)}] {cand_id}  ({cand_class})")
        t0 = time.time()
        timed_out = False

        def _to_handler(_signum, _frame):
            raise TimeoutError(f"validate_candidate exceeded {args.timeout}s")

        prev = signal.signal(signal.SIGALRM, _to_handler) if args.timeout > 0 else None
        if args.timeout > 0:
            signal.alarm(args.timeout)
        try:
            res = eng.validate_candidate(
                cand, dm,
                significance_threshold=None,
                diagnostic_log_path=str(jsonl_path),
            )
            if res.get("sharpe", 0.0) > 0 and res.get("robustness_survival", 0.0) >= 0.7:
                # Best-guess "passed" — full gate check is at validate_candidate's tail.
                n_passed += int(bool(res.get("passed_all_gates", False)))
        except TimeoutError as toe:
            timed_out = True
            n_timeout += 1
            print(f"[DIAG]   TIMEOUT: {toe}")
            emit_timeout(jsonl_path, cand, t0)
        except Exception as ex:
            n_error += 1
            print(f"[DIAG]   ERROR: {type(ex).__name__}: {ex}")
        finally:
            if args.timeout > 0:
                signal.alarm(0)
                if prev is not None:
                    signal.signal(signal.SIGALRM, prev)
        elapsed = time.time() - t0
        n_done += 1
        if not timed_out:
            print(f"[DIAG]   done in {elapsed:.1f}s")

    n_lines = sum(1 for _ in jsonl_path.open()) if jsonl_path.exists() else 0
    print(f"\n[DIAG] {n_done} candidates run | {n_passed} passed | {n_timeout} timeout | {n_error} error")
    print(f"[DIAG] jsonl records: {n_lines}")
    print(f"[DIAG] jsonl: {jsonl_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
