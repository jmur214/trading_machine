"""
scripts/run_deterministic.py
============================
Run backtests with pinned governor state for reproducible A/B testing.

Every normal backtest run mutates `data/governor/edge_weights.json` and
`data/governor/regime_edge_performance.json` via `governor.save_weights()`.
Back-to-back runs therefore start from different seed state and produce
different trades — even with identical code.

This wrapper:
  1. Restores governor state from anchor files before each run.
  2. Invokes the backtest with `--no-governor` so the run cannot mutate state.
  3. Computes md5 of `trades.csv` and `portfolio_snapshots.csv` after each run.
  4. In `--verify` / `--runs N` mode, reports whether all runs match.

Usage:
  # One-time: create anchors from current state
  python -m scripts.run_deterministic --save-anchor

  # Single deterministic run
  python -m scripts.run_deterministic

  # Verify determinism (2 runs, compare md5)
  python -m scripts.run_deterministic --verify

  # Multi-run A/B noise floor measurement
  python -m scripts.run_deterministic --runs 3

  # Pass-through flags
  python -m scripts.run_deterministic --env prod --mode sandbox --capital 100000
"""

import os
import sys

# Force PYTHONHASHSEED=0 before importing anything else. Python randomizes
# string hash seeds per-process by default, which makes `set()` iteration order
# non-deterministic across invocations. This re-execs ourselves once if the var
# is missing so that all downstream imports see a stable hash seed.
if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable, "-m", "scripts.run_deterministic", *sys.argv[1:]])

import argparse
import hashlib
import shutil
from pathlib import Path

from scripts.run_backtest import run_backtest_logic


ROOT = Path(__file__).resolve().parents[1]
GOV_DIR = ROOT / "data" / "governor"
WEIGHTS = GOV_DIR / "edge_weights.json"
PERF = GOV_DIR / "regime_edge_performance.json"
WEIGHTS_ANCHOR = GOV_DIR / "edge_weights.json.anchor"
PERF_ANCHOR = GOV_DIR / "regime_edge_performance.json.anchor"

TRADES_CSV = ROOT / "data" / "trade_logs" / "trades.csv"
SNAPS_CSV = ROOT / "data" / "trade_logs" / "portfolio_snapshots.csv"

# Columns to exclude from the determinism hash — these carry per-run identifiers
# (UUIDs, timestamps) that change even when trade outcomes are identical.
EXCLUDE_COLS = {"run_id", "meta"}


def md5(path: Path) -> str:
    if not path.exists():
        return "(missing)"
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_md5(path: Path) -> str:
    """MD5 of the CSV with per-run identifier columns (run_id, meta) excluded."""
    if not path.exists():
        return "(missing)"
    try:
        import pandas as pd
        df = pd.read_csv(path)
        drop = [c for c in EXCLUDE_COLS if c in df.columns]
        if drop:
            df = df.drop(columns=drop)
        return hashlib.md5(
            pd.util.hash_pandas_object(df, index=False).values.tobytes()
        ).hexdigest()
    except Exception as e:
        return f"(error: {e})"


def save_anchor():
    missing = [p for p in (WEIGHTS, PERF) if not p.exists()]
    if missing:
        print(f"[ANCHOR] Cannot save — source files missing: {missing}")
        return 1
    shutil.copy(WEIGHTS, WEIGHTS_ANCHOR)
    shutil.copy(PERF, PERF_ANCHOR)
    print(f"[ANCHOR] Saved:\n  {WEIGHTS_ANCHOR}\n  {PERF_ANCHOR}")
    return 0


def restore_anchor():
    if not WEIGHTS_ANCHOR.exists() or not PERF_ANCHOR.exists():
        print(f"[ANCHOR] Missing anchor files. Run with --save-anchor first.")
        print(f"  Expected: {WEIGHTS_ANCHOR}")
        print(f"  Expected: {PERF_ANCHOR}")
        return False
    shutil.copy(WEIGHTS_ANCHOR, WEIGHTS)
    shutil.copy(PERF_ANCHOR, PERF)
    return True


def run_once(args) -> dict:
    if not restore_anchor():
        sys.exit(1)
    stats = run_backtest_logic(
        env=args.env,
        mode=args.mode,
        fresh=args.fresh,
        no_governor=True,
        alpha_debug=False,
        override_capital=args.capital,
        discover=False,
    )
    return {
        "stats": stats,
        "trades_md5_raw": md5(TRADES_CSV),
        "trades_md5_canon": canonical_md5(TRADES_CSV),
        "snaps_md5_raw": md5(SNAPS_CSV),
        "snaps_md5_canon": canonical_md5(SNAPS_CSV),
    }


def main():
    parser = argparse.ArgumentParser(description="Run backtest with pinned governor state for deterministic A/B testing.")
    parser.add_argument("--save-anchor", action="store_true",
                        help="Snapshot current governor state to anchor files, then exit.")
    parser.add_argument("--verify", action="store_true",
                        help="Run 2 times and report whether md5s match (shorthand for --runs 2).")
    parser.add_argument("--runs", type=int, default=1,
                        help="Number of runs to perform. >1 enables determinism reporting.")
    parser.add_argument("--env", choices=["dev", "prod"], default="prod")
    parser.add_argument("--mode", choices=["sandbox", "prod"], default="prod")
    parser.add_argument("--fresh", action="store_true",
                        help="Clear prior trades/snapshots before each run.")
    parser.add_argument("--capital", type=float, default=None)
    args = parser.parse_args()

    if args.save_anchor:
        return save_anchor()

    n = 2 if args.verify else args.runs
    if n < 1:
        print("[ERROR] --runs must be >= 1")
        return 1

    results = []
    for i in range(n):
        print(f"\n===== RUN {i+1} / {n} =====")
        r = run_once(args)
        results.append(r)
        stats = r["stats"] or {}
        sharpe = stats.get("sharpe") or stats.get("Sharpe") or "?"
        cagr = stats.get("cagr") or stats.get("CAGR") or "?"
        print(f"[RUN {i+1}] Sharpe={sharpe}  CAGR={cagr}")
        print(f"[RUN {i+1}] trades.csv   raw md5:  {r['trades_md5_raw']}")
        print(f"[RUN {i+1}] trades.csv   canon md5 (sans run_id,meta): {r['trades_md5_canon']}")
        print(f"[RUN {i+1}] snapshots    raw md5:  {r['snaps_md5_raw']}")
        print(f"[RUN {i+1}] snapshots    canon md5 (sans run_id,meta): {r['snaps_md5_canon']}")

    if n > 1:
        raw_trades = {r["trades_md5_raw"] for r in results}
        raw_snaps = {r["snaps_md5_raw"] for r in results}
        canon_trades = {r["trades_md5_canon"] for r in results}
        canon_snaps = {r["snaps_md5_canon"] for r in results}
        print("\n===== DETERMINISM REPORT =====")
        print(f"trades.csv     raw:   {'MATCH' if len(raw_trades) == 1 else 'DIVERGE'}  ({len(raw_trades)} unique)")
        print(f"trades.csv     canon: {'MATCH' if len(canon_trades) == 1 else 'DIVERGE'}  ({len(canon_trades)} unique)  <- excludes run_id,meta")
        print(f"snapshots.csv  raw:   {'MATCH' if len(raw_snaps) == 1 else 'DIVERGE'}  ({len(raw_snaps)} unique)")
        print(f"snapshots.csv  canon: {'MATCH' if len(canon_snaps) == 1 else 'DIVERGE'}  ({len(canon_snaps)} unique)  <- excludes run_id,meta")

        canon_match = len(canon_trades) == 1 and len(canon_snaps) == 1
        if canon_match:
            print("\n[RESULT] PASS — trade outcomes are deterministic. Raw md5 divergence is due to")
            print("                per-run identifier columns (run_id UUID, meta), which is expected.")
            return 0
        print("\n[RESULT] FAIL — trade outcomes differ even after excluding per-run identifiers.")
        print("  unique canon trades md5s:", sorted(canon_trades))
        print("  unique canon snaps  md5s:", sorted(canon_snaps))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
