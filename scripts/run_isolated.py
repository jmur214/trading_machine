"""
scripts/run_isolated.py
=======================
Determinism floor for backtests under --reset-governor.

The pre-existing `scripts/run_deterministic.py` was built for the
2026-04-23 Phase 0 floor when the only mutable governor state was
`edge_weights.json` and `regime_edge_performance.json`, and it relied
on `--no-governor` to suppress end-of-run writes. Phase 2.10d Task A
(autonomous lifecycle triggers) added end-of-run writes to:
  - `data/governor/edges.yml`           (status changes per
                                          lifecycle_manager.evaluate)
  - `data/governor/lifecycle_history.csv` (audit-trail append)
  - `data/governor/edges.yml`           (also tier reclassification
                                          via evaluate_tiers)

After Phase 2.10d, `--reset-governor` no longer makes a run independent
of prior runs: the prior run's lifecycle pass has mutated edges.yml,
which the next run reads at startup. The result is intra-worktree
Sharpe variance up to ±1.4 across same-config runs (round-3 ship
blocker, `path1_ship_validation_2026_05.md`).

This wrapper restores the *full* `data/governor/` directory from an
anchor before each run AND restores it back after. End-of-run lifecycle
writes still happen as designed (so the lifecycle observability stays
intact in production), but each measurement run starts and ends in
the anchored state.

Usage:
  # 1. Take a snapshot of the current governor state as the anchor
  python -m scripts.run_isolated --save-anchor

  # 2. Single isolated run (any sweep / validation harness wrapping
  #    ModeController.run_backtest inherits the isolation)
  PYTHONHASHSEED=0 python -m scripts.run_isolated --task q1

  # 3. Multi-run determinism check
  PYTHONHASHSEED=0 python -m scripts.run_isolated --runs 3 --task q1
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


ROOT = Path(__file__).resolve().parents[1]
GOV_DIR = ROOT / "data" / "governor"
ISOLATED_ANCHOR = GOV_DIR / "_isolated_anchor"
TRADES_DIR = ROOT / "data" / "trade_logs"


def _reexec_if_hashseed_unset() -> None:
    """Re-exec ourselves with PYTHONHASHSEED=0 if it isn't set yet.

    Python randomizes string hash seeds per-process by default, which
    leaks into `set()` iteration order and breaks bit-for-bit
    determinism. The 04-23 floor required this; we keep it. Called only
    from `__main__` so importing the module (e.g. from tests) does
    not trigger a re-exec.
    """
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(sys.executable, [sys.executable, "-m", "scripts.run_isolated", *sys.argv[1:]])


# Files in data/governor/ that mutate end-of-run under any non-no-governor
# code path. Snapshotting just these keeps the harness fast (skip the
# meta-learner pickles etc., which only change when the trainer runs).
ISOLATED_FILES = [
    "edges.yml",
    "edge_weights.json",
    "regime_edge_performance.json",
    "lifecycle_history.csv",
]


def _md5(path: Path) -> str:
    if not path.exists():
        return "(missing)"
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def save_anchor() -> int:
    """Snapshot `data/governor/<file>` for every name in ISOLATED_FILES."""
    ISOLATED_ANCHOR.mkdir(parents=True, exist_ok=True)
    saved = []
    for name in ISOLATED_FILES:
        src = GOV_DIR / name
        if src.exists():
            shutil.copy(src, ISOLATED_ANCHOR / name)
            saved.append(name)
    print(f"[ISOLATED] Anchor saved at {ISOLATED_ANCHOR}: {saved}")
    return 0


def restore_anchor() -> None:
    """Restore the full set of governor files from the anchor.

    For files that exist in the anchor: copy over current.
    For files that DO NOT exist in the anchor (e.g. lifecycle_history.csv
    when the anchor was taken before any lifecycle event fired): DELETE
    the live file so the run starts from the same empty-history state.
    Without this, lifecycle_history.csv accumulates mutations in the live
    tree even when not present in the anchor, causing drift on the
    audit-trail divergence-check side.
    """
    if not ISOLATED_ANCHOR.exists():
        raise RuntimeError(
            f"No anchor at {ISOLATED_ANCHOR}; run with --save-anchor first."
        )
    for name in ISOLATED_FILES:
        src = ISOLATED_ANCHOR / name
        dst = GOV_DIR / name
        if src.exists():
            shutil.copy(src, dst)
        elif dst.exists():
            dst.unlink()


@contextmanager
def isolated() -> Iterator[None]:
    """Context manager: restore anchor on entry, restore again on exit.

    Restoring on exit (not just entry) means a sequence of isolated runs
    leaves the worktree in the same anchored state regardless of whether
    each run mutated. This is what lets repeated invocations be
    bit-comparable downstream.
    """
    restore_anchor()
    try:
        yield
    finally:
        restore_anchor()


def _print_state(label: str) -> None:
    print(f"[ISOLATED] {label} governor hashes:")
    for name in ISOLATED_FILES:
        print(f"  {name}: {_md5(GOV_DIR / name)}")


def _run_q1_inside_context() -> dict:
    """Run a 2025 OOS Q1 backtest (the canonical validation case)."""
    from orchestration.mode_controller import ModeController
    mc = ModeController(ROOT, env="prod")
    return mc.run_backtest(
        mode="prod", fresh=False, no_governor=False, reset_governor=True,
        alpha_debug=False,
        override_start="2025-01-01", override_end="2025-12-31",
    )


def _trades_canon_md5(run_id: str) -> str:
    p = TRADES_DIR / run_id / f"trades_{run_id}.csv"
    if not p.exists():
        return "(missing)"
    try:
        import pandas as pd
        df = pd.read_csv(p)
        for col in ("run_id", "meta"):
            if col in df.columns:
                df = df.drop(columns=[col])
        return hashlib.md5(
            pd.util.hash_pandas_object(df, index=False).values.tobytes()
        ).hexdigest()
    except Exception as e:
        return f"(error: {e})"


def _find_run_id(before: set[str]) -> str | None:
    after = {p.name for p in TRADES_DIR.iterdir() if p.is_dir() and p.name != "backup"}
    new = after - before
    if not new:
        return None
    if len(new) == 1:
        return next(iter(new))
    candidates = [(p, p.stat().st_mtime) for p in TRADES_DIR.iterdir() if p.name in new]
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0].name


def main() -> int:
    _reexec_if_hashseed_unset()
    parser = argparse.ArgumentParser()
    parser.add_argument("--save-anchor", action="store_true",
                        help="Snapshot current governor state as anchor and exit.")
    parser.add_argument("--runs", type=int, default=1,
                        help="Number of isolated runs to perform (each "
                             "restores from the anchor first).")
    parser.add_argument("--task", choices=["q1"], default="q1",
                        help="Backtest task to run inside the isolation.")
    parser.add_argument("--show-hashes", action="store_true",
                        help="Print pre/post governor hashes per run.")
    args = parser.parse_args()

    if args.save_anchor:
        return save_anchor()

    if not ISOLATED_ANCHOR.exists():
        print("[ISOLATED] No anchor found. Run with --save-anchor first.",
              file=sys.stderr)
        return 1

    results = []
    for i in range(args.runs):
        print(f"\n===== ISOLATED RUN {i + 1} / {args.runs} =====")
        if args.show_hashes:
            _print_state("PRE  ANCHOR")
        before = {p.name for p in TRADES_DIR.iterdir()
                  if p.is_dir() and p.name != "backup"}
        with isolated():
            if args.show_hashes:
                _print_state("PRE  RUN  ")
            summary = _run_q1_inside_context()
            if args.show_hashes:
                _print_state("POST RUN  ")
        if args.show_hashes:
            _print_state("POST RESTORE")

        run_id = _find_run_id(before) or "?"
        record = {
            "run_id": run_id,
            "sharpe": summary.get("Sharpe Ratio"),
            "cagr_pct": summary.get("CAGR (%)"),
            "trades_canon_md5": _trades_canon_md5(run_id) if run_id != "?" else "(no run_id)",
        }
        results.append(record)
        print(f"  Sharpe: {record['sharpe']}")
        print(f"  CAGR%:  {record['cagr_pct']}")
        print(f"  run_id: {record['run_id']}")
        print(f"  trades_canon_md5: {record['trades_canon_md5']}")

    if args.runs > 1:
        sharpes = [r["sharpe"] for r in results]
        canons = [r["trades_canon_md5"] for r in results]
        sharpe_range = (max(sharpes) - min(sharpes)) if sharpes else 0
        canon_unique = len(set(canons))
        print("\n===== DETERMINISM REPORT =====")
        print(f"Sharpes:          {sharpes}")
        print(f"Sharpe range:     {sharpe_range:.4f}")
        print(f"Canon md5 unique: {canon_unique} / {len(canons)}")
        if sharpe_range <= 0.02 and canon_unique == 1:
            print("[RESULT] PASS — Sharpe within ±0.02 AND bitwise-identical canon md5")
            return 0
        if sharpe_range <= 0.02:
            print("[RESULT] PARTIAL — Sharpes converge but trade-log canon md5s differ.")
            print("                  Likely residual non-determinism (trade order, "
                  "timestamp serialization). Investigate before claiming the floor.")
            return 1
        print("[RESULT] FAIL — same-config runs produce >0.02 Sharpe spread.")
        print(f"                Spread {sharpe_range:.4f} indicates governor-state drift "
              "is not fully bounded by the harness.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
