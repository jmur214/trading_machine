"""A/B harness: weighted_sum vs HRP under run_isolated.

Runs `--runs N` of cell A (method=weighted_sum) and cell B (method=hrp),
flipping config/portfolio_settings.json between cells. The
``portfolio_settings.json`` file is *not* in the isolation anchor, so
this script restores it from a snapshot at the end.

Usage:
    PYTHONHASHSEED=0 python -m scripts.ab_engine_c_hrp --runs 3
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTFOLIO_CFG = ROOT / "config" / "portfolio_settings.json"
TRADES_DIR = ROOT / "data" / "trade_logs"


def _reexec_if_hashseed_unset() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(sys.executable, [sys.executable, "-m", "scripts.ab_engine_c_hrp", *sys.argv[1:]])


def _set_method(method: str) -> None:
    cfg = json.loads(PORTFOLIO_CFG.read_text())
    if "portfolio_optimizer" not in cfg:
        cfg["portfolio_optimizer"] = {}
    cfg["portfolio_optimizer"]["method"] = method
    PORTFOLIO_CFG.write_text(json.dumps(cfg, indent=4) + "\n")


def _run_cell(method: str, runs: int) -> list[dict]:
    """Mutate portfolio_settings.json then call run_isolated.main()."""
    _set_method(method)
    print(f"\n###### CELL: method={method} ######")

    # Re-import run_isolated to pick up fresh state. We call its
    # internals directly so we can collect Sharpe per run.
    from scripts import run_isolated as ri

    if not ri.ISOLATED_ANCHOR.exists():
        raise RuntimeError(
            f"No anchor at {ri.ISOLATED_ANCHOR}; run "
            f"`python -m scripts.run_isolated --save-anchor` first."
        )

    results = []
    for i in range(runs):
        print(f"\n===== {method} RUN {i+1}/{runs} =====")
        before = {p.name for p in TRADES_DIR.iterdir()
                  if p.is_dir() and p.name != "backup"}
        with ri.isolated():
            summary = ri._run_q1_inside_context()
        run_id = ri._find_run_id(before) or "?"
        record = {
            "method": method,
            "run_id": run_id,
            "sharpe": summary.get("Sharpe Ratio"),
            "cagr_pct": summary.get("CAGR (%)"),
            "mdd_pct": summary.get("Max Drawdown (%)"),
            "trades_canon_md5": ri._trades_canon_md5(run_id) if run_id != "?" else "(no run_id)",
        }
        results.append(record)
        print(f"  Sharpe: {record['sharpe']}")
        print(f"  CAGR%:  {record['cagr_pct']}")
        print(f"  MDD%:   {record['mdd_pct']}")
        print(f"  canon:  {record['trades_canon_md5']}")
    return results


def _summarize(label: str, runs: list[dict]) -> dict:
    sharpes = [r["sharpe"] for r in runs if r["sharpe"] is not None]
    canons = [r["trades_canon_md5"] for r in runs]
    return {
        "label": label,
        "sharpes": sharpes,
        "mean_sharpe": (sum(sharpes) / len(sharpes)) if sharpes else None,
        "sharpe_range": (max(sharpes) - min(sharpes)) if sharpes else None,
        "canon_unique": len(set(canons)),
    }


def main() -> int:
    _reexec_if_hashseed_unset()
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    args = parser.parse_args()

    snapshot = PORTFOLIO_CFG.read_text()
    try:
        a = _run_cell("weighted_sum", args.runs)
        b = _run_cell("hrp", args.runs)
    finally:
        PORTFOLIO_CFG.write_text(snapshot)

    sa = _summarize("A: weighted_sum", a)
    sb = _summarize("B: hrp", b)

    print("\n===== A/B SUMMARY =====")
    for s in (sa, sb):
        print(f"\n{s['label']}")
        print(f"  Sharpes:      {s['sharpes']}")
        print(f"  Mean Sharpe:  {s['mean_sharpe']}")
        print(f"  Sharpe range: {s['sharpe_range']}")
        print(f"  Canon unique: {s['canon_unique']} / {len(s['sharpes'])}")

    if sa["mean_sharpe"] is not None and sb["mean_sharpe"] is not None:
        delta = sb["mean_sharpe"] - sa["mean_sharpe"]
        print(f"\nDELTA (B - A): {delta:+.4f}")
        if delta >= 0.1:
            print("[VERDICT] PASS — HRP delivers ≥ +0.1 Sharpe lift over weighted_sum.")
        else:
            print("[VERDICT] FAIL — HRP does not clear the +0.1 Sharpe bar.")

    out_path = ROOT / "docs" / "Audit" / "engine_c_hrp_ab_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(
        {"cell_a": a, "cell_b": b, "summary_a": sa, "summary_b": sb}, indent=2
    ))
    print(f"\nResults written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
