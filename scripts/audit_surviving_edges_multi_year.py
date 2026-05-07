"""
scripts/audit_surviving_edges_multi_year.py
============================================
Substrate-honest multi-year measurement using ONLY the CONFIRMED edges
from the per-edge audit. This is the substrate-honest "real" Foundation
Gate — what the system is actually capable of on a representative
universe with the surviving edge set.

Unlike `scripts/run_multi_year.py`, this driver pins `exact_edge_ids` to
a passed list (the CONFIRMED set) AND defaults to the historical
universe.

Usage:
    PYTHONHASHSEED=0 python -m scripts.audit_surviving_edges_multi_year \\
        --years 2021,2022,2023,2024,2025 --runs 1 \\
        --edges gap_fill_v1,volume_anomaly_v1,herding_v1 \\
        --output docs/Measurements/2026-05/surviving_edges_multi_year_2026_05_<DATE>.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_isolated import (  # noqa: E402
    ISOLATED_ANCHOR,
    TRADES_DIR,
    isolated,
    _find_run_id,
    _trades_canon_md5,
)


def _reexec_if_hashseed_unset() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(
            sys.executable,
            [sys.executable, "-m", "scripts.audit_surviving_edges_multi_year", *sys.argv[1:]],
        )


def _run_year_with_edges(
    year: int,
    edges: list[str],
    use_historical_universe: bool,
) -> dict:
    from orchestration.mode_controller import ModeController

    mc = ModeController(ROOT, env="prod")
    return mc.run_backtest(
        mode="prod",
        fresh=False,
        no_governor=False,
        reset_governor=True,
        alpha_debug=False,
        override_start=f"{year}-01-01",
        override_end=f"{year}-12-31",
        exact_edge_ids=edges,
        use_historical_universe=use_historical_universe,
    )


def main() -> int:
    _reexec_if_hashseed_unset()
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=str, default="2021,2022,2023,2024,2025")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument(
        "--edges",
        type=str,
        required=True,
        help="Comma-separated edge_ids (CONFIRMED set from per-edge audit).",
    )
    parser.add_argument("--use-historical-universe", action="store_true", default=True,
                        help="Default True. Pass --no-... has no effect (use --static instead).")
    parser.add_argument("--static", action="store_true",
                        help="Force static-109 universe instead of historical.")
    parser.add_argument(
        "--output",
        type=str,
        default="docs/Measurements/2026-05/surviving_edges_multi_year_2026_05_09.json",
    )
    args = parser.parse_args()

    if not ISOLATED_ANCHOR.exists():
        print(f"[SURVIVING] No anchor at {ISOLATED_ANCHOR}.", file=sys.stderr)
        return 1

    use_historical = not args.static
    years = [int(y.strip()) for y in args.years.split(",") if y.strip()]
    edges = [e.strip() for e in args.edges.split(",") if e.strip()]

    print(
        f"[SURVIVING] universe={'historical' if use_historical else 'static-109'} "
        f"years={years} runs={args.runs} edges={edges}"
    )

    results: list[dict] = []
    t_start = time.time()
    n_total = len(years) * args.runs
    counter = 0

    for year in years:
        for rep in range(1, args.runs + 1):
            counter += 1
            elapsed = time.time() - t_start
            avg = elapsed / max(counter - 1, 1) if counter > 1 else 0
            eta = avg * (n_total - counter + 1)
            print(
                f"\n===== [{counter}/{n_total}] year={year} rep={rep} "
                f"elapsed={elapsed/60:.1f}m ETA={eta/60:.1f}m =====",
                flush=True,
            )

            before = {p.name for p in TRADES_DIR.iterdir() if p.is_dir() and p.name != "backup"}
            t0 = time.time()
            try:
                with isolated():
                    summary = _run_year_with_edges(year, edges, use_historical)
                run_id = _find_run_id(before) or "?"
                rec = {
                    "year": year,
                    "rep": rep,
                    "run_id": run_id,
                    "sharpe": summary.get("Sharpe Ratio"),
                    "cagr_pct": summary.get("CAGR (%)"),
                    "max_drawdown_pct": summary.get("Max Drawdown (%)"),
                    "win_rate_pct": summary.get("Win Rate (%)"),
                    "total_trades": summary.get("Total Trades"),
                    "trades_canon_md5": _trades_canon_md5(run_id) if run_id != "?" else "(no run_id)",
                    "wall_time_seconds": round(time.time() - t0, 1),
                    "ok": True,
                }
            except Exception as e:
                rec = {
                    "year": year,
                    "rep": rep,
                    "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                    "wall_time_seconds": round(time.time() - t0, 1),
                }
            results.append(rec)
            print(f"  {rec}", flush=True)
            _persist(results, args.output, edges, use_historical)

    sharpes = [r["sharpe"] for r in results if r.get("ok") and r.get("sharpe") is not None]
    summary = {}
    if sharpes:
        summary["mean_sharpe"] = sum(sharpes) / len(sharpes)
        summary["min_sharpe"] = min(sharpes)
        summary["max_sharpe"] = max(sharpes)
        summary["n_runs"] = len(sharpes)
    print("\n" + json.dumps(summary, indent=2))
    print(f"\n[SURVIVING] Done in {(time.time()-t_start)/60:.1f}m. Output: {args.output}")
    return 0


def _persist(results, out_path, edges, use_historical):
    p = ROOT / out_path
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "metadata": {
            "edges": edges,
            "use_historical_universe": use_historical,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        },
        "results": results,
    }
    p.write_text(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    sys.exit(main())
