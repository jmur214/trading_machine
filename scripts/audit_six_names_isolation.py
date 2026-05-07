"""
scripts/audit_six_names_isolation.py
=====================================
Six-names substrate-bias isolation test.

Question: how much of the static-109 vs historical-S&P-500 Sharpe gap
is explained by 6 non-S&P 500 ultra-vol names in the static config?
Names: COIN, MARA, RIOT, DKNG, PLTR, SNOW.

Three universes, one calendar year, N reps each (default 3):
    A: static-109 (current default; baseline)
    B: static-109 minus the 6 non-S&P names = 103 names
    C: historical S&P 500 union (use_historical_universe=true)

Compares A vs B vs C means. If A - B ~= A - C, the 6 names are the
entire substrate-bias story. If A - B is small, the bias is diffuse.

The script atomically backs up `config/backtest_settings.json` for the
B variant (writes static-103 ticker list), restores on exit/exception.
Runs each backtest under `isolated()` so governor state is anchored
identically across variants and reps.

Usage:
    PYTHONHASHSEED=0 python -m scripts.audit_six_names_isolation \\
        --year 2024 --runs 3 \\
        --output docs/Measurements/2026-05/six_names_isolation_2026_05_<DATE>.json
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
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

NON_SP500_NAMES = ["COIN", "MARA", "RIOT", "DKNG", "PLTR", "SNOW"]
CONFIG_PATH = ROOT / "config" / "backtest_settings.json"


def _reexec_if_hashseed_unset() -> None:
    if os.environ.get("PYTHONHASHSEED") != "0":
        os.environ["PYTHONHASHSEED"] = "0"
        os.execv(
            sys.executable,
            [sys.executable, "-m", "scripts.audit_six_names_isolation", *sys.argv[1:]],
        )


def _run_year(
    year: int,
    use_historical_universe: bool = False,
) -> dict:
    """Run a single full-calendar-year backtest. Reads current config."""
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
        use_historical_universe=use_historical_universe,
    )


def _execute_variant(
    variant: str,
    year: int,
    runs: int,
    use_historical_universe: bool,
) -> list[dict]:
    """Run `runs` reps of one universe variant for the given year."""
    out: list[dict] = []
    for rep in range(1, runs + 1):
        before = {
            p.name
            for p in TRADES_DIR.iterdir()
            if p.is_dir() and p.name != "backup"
        }
        t0 = time.time()
        try:
            with isolated():
                summary = _run_year(year, use_historical_universe=use_historical_universe)
            run_id = _find_run_id(before) or "?"
            rec = {
                "variant": variant,
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
                "variant": variant,
                "year": year,
                "rep": rep,
                "ok": False,
                "error": f"{type(e).__name__}: {e}",
                "wall_time_seconds": round(time.time() - t0, 1),
            }
        out.append(rec)
        print(f"  [{variant} rep{rep}] {rec}", flush=True)
    return out


def _swap_config_drop_six_names() -> dict:
    """Mutate config/backtest_settings.json: drop the 6 non-S&P names.
    Returns the original config dict for restore.
    """
    original = json.loads(CONFIG_PATH.read_text())
    new_tickers = [t for t in original["tickers"] if t not in NON_SP500_NAMES]
    print(
        f"[6NAMES] Config swap: tickers {len(original['tickers'])} -> "
        f"{len(new_tickers)} (dropped {sorted(set(original['tickers']) - set(new_tickers))})"
    )
    new_cfg = dict(original)
    new_cfg["tickers"] = new_tickers
    CONFIG_PATH.write_text(json.dumps(new_cfg, indent=2))
    return original


def _restore_config(original: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(original, indent=2))
    print(
        f"[6NAMES] Config restored: tickers count = {len(original['tickers'])}",
        flush=True,
    )


def _summarize(results: list[dict]) -> dict:
    """Compute mean/min/max Sharpe per variant and the deltas."""
    by_variant: dict[str, list[float]] = {}
    for r in results:
        if not r.get("ok"):
            continue
        s = r.get("sharpe")
        if s is None:
            continue
        by_variant.setdefault(r["variant"], []).append(s)

    means: dict[str, float] = {}
    for v, vals in by_variant.items():
        means[v] = sum(vals) / len(vals)

    summary = {"per_variant": {}, "deltas": {}}
    for v, vals in by_variant.items():
        summary["per_variant"][v] = {
            "n_reps": len(vals),
            "sharpes": vals,
            "mean": means[v],
            "min": min(vals),
            "max": max(vals),
            "range": max(vals) - min(vals),
        }
    if "A" in means and "B" in means:
        summary["deltas"]["A_minus_B"] = means["A"] - means["B"]
    if "A" in means and "C" in means:
        summary["deltas"]["A_minus_C"] = means["A"] - means["C"]
    if "B" in means and "C" in means:
        summary["deltas"]["B_minus_C"] = means["B"] - means["C"]
    if "A_minus_B" in summary["deltas"] and "A_minus_C" in summary["deltas"]:
        a_minus_b = summary["deltas"]["A_minus_B"]
        a_minus_c = summary["deltas"]["A_minus_C"]
        if abs(a_minus_c) > 1e-9:
            summary["deltas"]["pct_of_substrate_gap_explained_by_six_names"] = (
                a_minus_b / a_minus_c
            ) * 100.0
    return summary


def main() -> int:
    _reexec_if_hashseed_unset()
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--variants", type=str, default="A,B,C",
                        help="Comma-separated subset of A,B,C to run")
    parser.add_argument(
        "--output",
        type=str,
        default="docs/Measurements/2026-05/six_names_isolation_2026_05_09.json",
    )
    args = parser.parse_args()

    if not ISOLATED_ANCHOR.exists():
        print(
            f"[6NAMES] No anchor at {ISOLATED_ANCHOR}. Run "
            "`python -m scripts.run_isolated --save-anchor` first.",
            file=sys.stderr,
        )
        return 1

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    results: list[dict] = []
    t_start = time.time()

    # Run variant A — vanilla static-109, no universe flag.
    if "A" in variants:
        print(f"\n===== VARIANT A: static-109 (baseline) | year={args.year} =====", flush=True)
        results.extend(_execute_variant("A", args.year, args.runs, use_historical_universe=False))
        _persist(results, args.output)

    # Run variant B — static-109 minus the 6 non-S&P names.
    if "B" in variants:
        print(f"\n===== VARIANT B: static-103 (drop 6 non-S&P names) | year={args.year} =====", flush=True)
        original_cfg = _swap_config_drop_six_names()
        try:
            results.extend(_execute_variant("B", args.year, args.runs, use_historical_universe=False))
        finally:
            _restore_config(original_cfg)
        _persist(results, args.output)

    # Run variant C — historical S&P 500 universe.
    if "C" in variants:
        print(f"\n===== VARIANT C: historical S&P 500 union | year={args.year} =====", flush=True)
        results.extend(_execute_variant("C", args.year, args.runs, use_historical_universe=True))
        _persist(results, args.output)

    summary = _summarize(results)

    final = {
        "metadata": {
            "year": args.year,
            "runs_per_variant": args.runs,
            "variants": variants,
            "non_sp500_names": NON_SP500_NAMES,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "wall_time_seconds": round(time.time() - t_start, 1),
        },
        "results": results,
        "summary": summary,
    }
    _persist_full(final, args.output)
    print(f"\n[6NAMES] Done in {(time.time()-t_start)/60:.1f}m. Output: {args.output}")
    print(json.dumps(summary, indent=2))
    return 0


def _persist(results: list[dict], out_path: str) -> None:
    p = ROOT / out_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"results": results}, indent=2, default=str))


def _persist_full(payload: dict, out_path: str) -> None:
    p = ROOT / out_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    sys.exit(main())
