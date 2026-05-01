"""
scripts/det_d1_repro.py
=======================
Determinism investigation D1: reproduce same-config Sharpe variance.

Runs the same 2025 OOS Q1 backtest N times sequentially in this worktree,
hashes all `data/governor/` state files BEFORE and AFTER each run, and
records per-run Sharpe + canon trade-log md5. Goal: confirm that running
the same nominal config repeatedly produces variable outcomes.

This script does NOT use --no-governor — that would prevent any
end-of-run mutation and trivially return the same result. We use
--reset-governor (the same flag every recent sweep used) which resets
weights at run start but allows end-of-run writes, exactly the
condition the round-3 ship blocker was measured under.

Usage:
  PYTHONHASHSEED=0 python -m scripts.det_d1_repro --runs 5
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict


ROOT = Path(__file__).resolve().parents[1]
GOV = ROOT / "data" / "governor"
TRADES_DIR = ROOT / "data" / "trade_logs"
RESEARCH_DIR = ROOT / "data" / "research"


# Files in data/governor/ that are candidate drift sources.
GOV_FILES = [
    "edges.yml",
    "edge_weights.json",
    "regime_edge_performance.json",
    "lifecycle_history.csv",
    "metalearner_balanced.pkl",
    "metalearner_growth.pkl",
    "metalearner_retiree.pkl",
]


def md5(path: Path) -> str:
    if not path.exists():
        return "(missing)"
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_governor_state() -> Dict[str, str]:
    return {name: md5(GOV / name) for name in GOV_FILES}


def file_size(path: Path) -> int:
    if not path.exists():
        return -1
    return path.stat().st_size


def gov_sizes() -> Dict[str, int]:
    return {name: file_size(GOV / name) for name in GOV_FILES}


def find_run_id(before: set[str]) -> str | None:
    after = {p.name for p in TRADES_DIR.iterdir() if p.is_dir() and p.name != "backup"}
    new = after - before
    if not new:
        return None
    if len(new) == 1:
        return next(iter(new))
    candidates = [(p, p.stat().st_mtime) for p in TRADES_DIR.iterdir() if p.name in new]
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0].name


def trades_canon_md5(run_id: str) -> str:
    """MD5 of trades.csv with run_id+meta columns dropped (mirrors
    scripts/run_deterministic.py::canonical_md5)."""
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


def run_one(start: str, end: str) -> dict:
    """Single 2025 OOS Q1-style run with --reset-governor.

    Returns dict with Sharpe, run_id, trade-canon md5, and per-file hash
    of every governor state file BEFORE and AFTER the run.
    """
    from orchestration.mode_controller import ModeController

    pre_hashes = hash_governor_state()
    pre_sizes = gov_sizes()
    before = {p.name for p in TRADES_DIR.iterdir() if p.is_dir() and p.name != "backup"}

    mc = ModeController(ROOT, env="prod")
    summary = mc.run_backtest(
        mode="prod", fresh=False, no_governor=False, reset_governor=True,
        alpha_debug=False, override_start=start, override_end=end,
    )

    post_hashes = hash_governor_state()
    post_sizes = gov_sizes()
    run_id = find_run_id(before) or "?"

    return {
        "run_id": run_id,
        "sharpe": summary.get("Sharpe Ratio"),
        "cagr_pct": summary.get("CAGR (%)"),
        "mdd_pct": summary.get("Max Drawdown (%)"),
        "vol_pct": summary.get("Volatility (%)"),
        "wr_pct": summary.get("Win Rate (%)"),
        "trades_canon_md5": trades_canon_md5(run_id) if run_id != "?" else "(no run_id)",
        "pre_hashes": pre_hashes,
        "post_hashes": post_hashes,
        "pre_sizes": pre_sizes,
        "post_sizes": post_sizes,
        "mutated": [
            n for n in GOV_FILES
            if pre_hashes.get(n) != post_hashes.get(n)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--label", default="d1")
    args = parser.parse_args()

    print(f"[D1] Repro at {args.start} -> {args.end}, {args.runs} runs, "
          f"--reset-governor each run, NO restore between runs.")
    print(f"[D1] Worktree: {ROOT}")
    results = []
    for i in range(args.runs):
        print(f"\n========== RUN {i + 1} / {args.runs} ==========")
        r = run_one(args.start, args.end)
        results.append(r)
        print(f"  Sharpe: {r['sharpe']}")
        print(f"  CAGR%:  {r['cagr_pct']}")
        print(f"  run_id: {r['run_id']}")
        print(f"  trades_canon_md5: {r['trades_canon_md5']}")
        print(f"  governor files mutated this run: {r['mutated']}")

    # Aggregate determinism report
    print("\n========== D1 SUMMARY ==========")
    sharpes = [r["sharpe"] for r in results]
    canon = [r["trades_canon_md5"] for r in results]
    print(f"Sharpes:           {sharpes}")
    print(f"Sharpe range:      {max(sharpes) - min(sharpes):.4f}")
    print(f"Canon md5 unique:  {len(set(canon))} / {len(canon)}")
    print(f"Files mutated set: {set(f for r in results for f in r['mutated'])}")

    out_path = RESEARCH_DIR / f"determinism_{args.label}_{args.runs}runs.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "label": args.label,
        "runs": args.runs,
        "window": [args.start, args.end],
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "sharpe_range": max(sharpes) - min(sharpes),
        "canon_md5_unique": len(set(canon)),
        "results": results,
    }
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"\n[D1] Saved to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
