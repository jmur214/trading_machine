"""
scripts/wash_sale_multi_year.py
================================
Multi-year × 2-cell × N-rep harness driver verifying the wash-sale gate's
+0.670 pre-tax Sharpe lift (memory: project_wash_sale_exposes_turnover_bug_2026_05_02.md)
generalizes across 2021-2025, not just the 2025 OOS window.

Grid:
    Years:  2021, 2022, 2023, 2024, 2025
    Cells:  A (wash_sale OFF), B (wash_sale ON)
    Reps:   3 each (bitwise determinism check per cell-year)

Total: 5 × 2 × 3 = 30 backtests.

All other config held constant: cap=0.20 (portfolio_policy.json), ML off
(alpha_settings.prod.json), floors on (governor_settings.json), all other
Path A flags OFF (lt_hold_preference.enabled=false, hrp method=weighted_sum,
turnover-penalty as configured on main).

Each backtest is wrapped in scripts.run_isolated.isolated() so governor
state is restored before+after — required for the 2026-05-01 determinism
floor under --reset-governor.

Wash-sale enabled is overridden in-process by mutating
mc.cfg_portfolio["wash_sale_avoidance"]["enabled"] AFTER ModeController
init but BEFORE mc.run_backtest() (run_backtest re-instantiates RiskEngine
each call, reading from cfg_portfolio).

Usage:
    PYTHONHASHSEED=0 python -m scripts.wash_sale_multi_year
    PYTHONHASHSEED=0 python -m scripts.wash_sale_multi_year --years 2021 2022
    PYTHONHASHSEED=0 python -m scripts.wash_sale_multi_year --reps 1     # smoke test

Output: data/research/wash_sale_multi_year_<timestamp>.json with full
per-cell-year matrix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
TRADES_DIR = ROOT / "data" / "trade_logs"
RESEARCH_DIR = ROOT / "data" / "research"


def _reexec_if_hashseed_unset() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(sys.executable, [sys.executable, "-m", "scripts.wash_sale_multi_year",
                                  *sys.argv[1:]])


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


def _find_run_id(before: set, year: int) -> Optional[str]:
    """Find the run_id created during this call.

    Trade-logs dir is symlinked across worktrees, so concurrent runs from
    OTHER worktrees can also append new dirs. We disambiguate by reading
    the trade CSV and checking that its first/last trade timestamp falls
    in our window-year. This makes detection race-safe even with parallel
    worktrees.
    """
    import pandas as pd
    after = {p.name for p in TRADES_DIR.iterdir()
             if p.is_dir() and p.name != "backup"}
    new = after - before
    if not new:
        return None
    # Multiple candidates: filter by window year (read first row's date).
    # Most-recent-mtime is the tiebreaker if multiple match (e.g. concurrent
    # runs in the same window, which our other worktrees aren't doing).
    matched: list = []
    for run_id in new:
        p = TRADES_DIR / run_id / f"trades_{run_id}.csv"
        if not p.exists():
            continue
        try:
            df = pd.read_csv(p, nrows=5)
            if df.empty or "timestamp" not in df.columns:
                continue
            # Trade timestamps fall inside our backtest window iff the year
            # column-extract matches.
            ts0 = pd.to_datetime(df["timestamp"].iloc[0])
            if ts0.year == year:
                matched.append((p.parent, p.parent.stat().st_mtime))
        except Exception:
            continue
    if not matched:
        return None
    matched.sort(key=lambda x: x[1], reverse=True)
    return matched[0][0].name


def _run_one(year: int, wash_sale_on: bool, rep: int) -> Dict[str, Any]:
    """One isolated backtest for (year, wash_sale flag).

    Imports ModeController fresh each call so cached state from prior
    invocation can't leak. Override the wash_sale flag by mutating
    cfg_portfolio AFTER init but BEFORE run_backtest (run_backtest
    re-instantiates RiskEngine so the override propagates).
    """
    from scripts.run_isolated import isolated
    from orchestration.mode_controller import ModeController

    start = f"{year}-01-01"
    end = f"{year}-12-31"
    label = f"{year}/{'B-ON' if wash_sale_on else 'A-OFF'}/rep{rep}"
    print(f"\n----- CELL {label} : window {start} → {end} -----")
    t0 = time.time()
    before = {p.name for p in TRADES_DIR.iterdir()
              if p.is_dir() and p.name != "backup"}

    with isolated():
        mc = ModeController(ROOT, env="prod")
        # Override wash-sale flag in the in-process config dict before
        # run_backtest constructs its RiskEngine. Belt-and-suspenders:
        # ensure the block exists, then set enabled.
        ws_block = mc.cfg_portfolio.setdefault("wash_sale_avoidance", {})
        ws_block["enabled"] = bool(wash_sale_on)
        # Defensive: ensure other Path A flag stays off (we want isolation).
        lt_block = mc.cfg_portfolio.setdefault("lt_hold_preference", {})
        lt_block["enabled"] = False
        # Defensive: ensure HRP composition stays off (weighted_sum is the
        # default on main, but be explicit).
        opt_block = mc.cfg_portfolio.setdefault("portfolio_optimizer", {})
        if opt_block.get("method") not in (None, "weighted_sum"):
            print(f"[WARN] portfolio_optimizer.method={opt_block.get('method')} "
                  f"— forcing to weighted_sum for isolation")
            opt_block["method"] = "weighted_sum"

        summary = mc.run_backtest(
            mode="prod",
            fresh=False,
            no_governor=False,
            reset_governor=True,
            alpha_debug=False,
            override_start=start,
            override_end=end,
        )

    run_id = _find_run_id(before, year) or "?"
    elapsed = time.time() - t0
    record = {
        "year": year,
        "cell": "B" if wash_sale_on else "A",
        "wash_sale_on": bool(wash_sale_on),
        "rep": rep,
        "window_start": start,
        "window_end": end,
        "run_id": run_id,
        "sharpe": summary.get("Sharpe Ratio"),
        "cagr_pct": summary.get("CAGR (%)"),
        "mdd_pct": summary.get("Max Drawdown (%)"),
        "vol_pct": summary.get("Volatility (%)"),
        "trades_canon_md5": _trades_canon_md5(run_id) if run_id != "?" else "(no run_id)",
        "elapsed_sec": round(elapsed, 1),
    }
    print(f"  Sharpe={record['sharpe']}  CAGR%={record['cagr_pct']}  "
          f"MDD%={record['mdd_pct']}  canon_md5={record['trades_canon_md5'][:10]}  "
          f"({elapsed:.0f}s)")
    return record


def _summarize(results: List[Dict[str, Any]], reps: int) -> Dict[str, Any]:
    """Aggregate per-year-cell stats and the cross-year Δ summary."""
    by_yc: Dict[str, List[Dict[str, Any]]] = {}
    for r in results:
        key = f"{r['year']}/{r['cell']}"
        by_yc.setdefault(key, []).append(r)

    per_cell: List[Dict[str, Any]] = []
    for key, recs in sorted(by_yc.items()):
        sharpes = [r["sharpe"] for r in recs if r["sharpe"] is not None]
        canons = [r["trades_canon_md5"] for r in recs]
        unique_canons = sorted(set(canons))
        sharpe_range = (max(sharpes) - min(sharpes)) if sharpes else 0.0
        mean_sharpe = sum(sharpes) / len(sharpes) if sharpes else None
        per_cell.append({
            "key": key,
            "year": recs[0]["year"],
            "cell": recs[0]["cell"],
            "n_reps": len(recs),
            "mean_sharpe": round(mean_sharpe, 4) if mean_sharpe is not None else None,
            "sharpe_range": round(sharpe_range, 6),
            "n_unique_canon_md5": len(unique_canons),
            "canon_md5_first": unique_canons[0] if unique_canons else "(none)",
            # Determinism: primary check is Sharpe range (in-process, race-immune).
            # canon md5 is also reported but trade-logs dir is symlinked across
            # worktrees so concurrent runs from OTHER agents can race the
            # diff; we trust Sharpe for the gate.
            "deterministic_within_cell": sharpe_range <= 0.001,
            "cagr_pct": round(sum(r["cagr_pct"] for r in recs) / len(recs), 4),
            "mdd_pct": round(sum(r["mdd_pct"] for r in recs) / len(recs), 4),
        })

    by_year: Dict[int, Dict[str, Optional[float]]] = {}
    for c in per_cell:
        y = c["year"]
        cell = c["cell"]
        by_year.setdefault(y, {"A": None, "B": None})
        by_year[y][cell] = c["mean_sharpe"]

    deltas: List[Dict[str, Any]] = []
    for y in sorted(by_year):
        a = by_year[y].get("A")
        b = by_year[y].get("B")
        delta = (b - a) if (a is not None and b is not None) else None
        deltas.append({
            "year": y,
            "cell_A_mean_sharpe": a,
            "cell_B_mean_sharpe": b,
            "delta_B_minus_A": round(delta, 4) if delta is not None else None,
        })

    delta_vals = [d["delta_B_minus_A"] for d in deltas
                  if d["delta_B_minus_A"] is not None]
    if delta_vals:
        n = len(delta_vals)
        mean_d = sum(delta_vals) / n
        var_d = sum((x - mean_d) ** 2 for x in delta_vals) / n if n > 1 else 0.0
        std_d = var_d ** 0.5
        min_d = min(delta_vals)
        max_d = max(delta_vals)
        all_positive = all(d > 0 for d in delta_vals)
    else:
        mean_d = std_d = min_d = max_d = None
        all_positive = False

    # Pass/fail per task spec
    if mean_d is None:
        verdict = "ERROR — no valid deltas"
    elif mean_d >= 0.30 and all_positive:
        verdict = "PASS — wash-sale gate generalizes; recommend default-on"
    elif mean_d >= 0.30:
        worst = [d for d in deltas if d["delta_B_minus_A"] is not None
                 and d["delta_B_minus_A"] <= 0]
        verdict = (f"CONDITIONAL — mean Δ {mean_d:.3f} ≥ 0.30 but "
                   f"{len(worst)} year(s) non-positive: {[d['year'] for d in worst]}")
    else:
        verdict = (f"FAIL — mean Δ {mean_d:.3f} < 0.30 — 2025 OOS lift was "
                   f"window-fortunate; do NOT flip default-on")

    return {
        "per_cell": per_cell,
        "deltas_per_year": deltas,
        "delta_stats": {
            "mean": round(mean_d, 4) if mean_d is not None else None,
            "std": round(std_d, 4) if std_d is not None else None,
            "min": round(min_d, 4) if min_d is not None else None,
            "max": round(max_d, 4) if max_d is not None else None,
            "n_years_positive": sum(1 for d in delta_vals if d > 0) if delta_vals else 0,
            "n_years_total": len(delta_vals),
        },
        "verdict": verdict,
        "reps_per_cell": reps,
    }


def main() -> int:
    _reexec_if_hashseed_unset()
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, nargs="+",
                        default=[2021, 2022, 2023, 2024, 2025])
    parser.add_argument("--reps", type=int, default=3,
                        help="Reps per cell (3 for determinism check, 1 for smoke).")
    parser.add_argument("--out",
                        default=None,
                        help="Output JSON path (default: data/research/wash_sale_multi_year_<ts>.json)")
    args = parser.parse_args()

    print(f"[WASH-MULTI] years={args.years}  reps={args.reps}")
    print(f"[WASH-MULTI] grid: {len(args.years)} years × 2 cells × {args.reps} reps "
          f"= {len(args.years) * 2 * args.reps} backtests")

    results: List[Dict[str, Any]] = []
    grid_t0 = time.time()
    grid_failures: List[str] = []

    for year in args.years:
        for wash_sale_on in [False, True]:
            for rep in range(1, args.reps + 1):
                cell_t0 = time.time()
                try:
                    rec = _run_one(year, wash_sale_on, rep)
                    results.append(rec)
                    if (time.time() - cell_t0) > 1800:
                        msg = (f"Year {year} Cell {'B' if wash_sale_on else 'A'} "
                               f"rep {rep} exceeded 30 min "
                               f"({time.time() - cell_t0:.0f}s) — flagging.")
                        print(f"[WARN] {msg}")
                        grid_failures.append(msg)
                except Exception as e:
                    err = f"Year {year} Cell {'B' if wash_sale_on else 'A'} rep {rep} FAILED: {e!r}"
                    print(f"[ERROR] {err}")
                    grid_failures.append(err)
                    # Persist a failure stub so summarize sees the gap
                    results.append({
                        "year": year, "cell": "B" if wash_sale_on else "A",
                        "wash_sale_on": bool(wash_sale_on), "rep": rep,
                        "error": repr(e), "sharpe": None,
                        "trades_canon_md5": "(error)",
                    })

    summary = _summarize(results, reps=args.reps)
    summary["raw"] = results
    summary["grid_failures"] = grid_failures
    summary["grid_elapsed_sec"] = round(time.time() - grid_t0, 1)
    summary["timestamp"] = datetime.utcnow().isoformat() + "Z"

    out_path = (Path(args.out) if args.out
                else RESEARCH_DIR / f"wash_sale_multi_year_"
                                    f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"\n========== WASH-SALE MULTI-YEAR REPORT ==========")
    for c in summary["per_cell"]:
        det = "✓" if c["deterministic_within_cell"] else "✗"
        print(f"  {c['key']:>9}  Sharpe={c['mean_sharpe']:>7.4f}  "
              f"range={c['sharpe_range']:.4f}  uniq_canon={c['n_unique_canon_md5']} {det}")
    print(f"\n----- Δ B−A per year -----")
    for d in summary["deltas_per_year"]:
        print(f"  {d['year']}  A={d['cell_A_mean_sharpe']}  B={d['cell_B_mean_sharpe']}  "
              f"Δ={d['delta_B_minus_A']}")
    print(f"\n----- Δ Aggregate across {summary['delta_stats']['n_years_total']} years -----")
    print(f"  mean Δ:   {summary['delta_stats']['mean']}")
    print(f"  std  Δ:   {summary['delta_stats']['std']}")
    print(f"  min  Δ:   {summary['delta_stats']['min']}")
    print(f"  max  Δ:   {summary['delta_stats']['max']}")
    print(f"  positive: {summary['delta_stats']['n_years_positive']} / {summary['delta_stats']['n_years_total']}")
    print(f"\nVERDICT: {summary['verdict']}")
    if grid_failures:
        print(f"\n[WARN] {len(grid_failures)} grid issue(s):")
        for f in grid_failures:
            print(f"   - {f}")
    print(f"\nFull JSON: {out_path}")
    print(f"Total grid wall: {summary['grid_elapsed_sec']:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
