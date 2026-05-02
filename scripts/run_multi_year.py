"""
scripts/run_multi_year.py
=========================
Multi-year Foundation Gate measurement under the determinism harness.

Wraps the same `isolated()` context manager from `run_isolated.py` so each
(year, rep) starts and ends in the anchored governor state. Every measurement
we cite is on 2025 OOS only; the wash-sale falsification (2021 Δ=-0.966)
proved 2025 is window-specific. This driver produces the honest cross-year
view: per-year Sharpe across 2021-2025 with 3 reps/year for within-year
determinism verification.

Usage:
  # Anchor must already exist (run_isolated.py --save-anchor first).
  PYTHONHASHSEED=0 python -m scripts.run_multi_year \\
      --years 2021,2022,2023,2024,2025 --runs 3 \\
      --output docs/Audit/multi_year_foundation_measurement.md

  # Smoke test on one year × 1 rep:
  PYTHONHASHSEED=0 python -m scripts.run_multi_year --years 2024 --runs 1
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Reuse all the determinism plumbing from run_isolated.py.
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
        os.execv(sys.executable, [sys.executable, "-m", "scripts.run_multi_year", *sys.argv[1:]])


def _run_year(year: int) -> dict:
    """Run a single full-calendar-year backtest under prod config."""
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
    )


def _format_markdown_report(results: list[dict], output_path: Path) -> None:
    """Write a human-readable summary to docs/Audit/."""
    by_year: dict[int, list[dict]] = {}
    for r in results:
        by_year.setdefault(r["year"], []).append(r)

    lines: list[str] = []
    lines.append("# Multi-Year Foundation Measurement")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"Total runs: {len(results)} ({len(by_year)} years × {len(next(iter(by_year.values())))} reps)")
    lines.append("")
    lines.append("## Per-year results")
    lines.append("")
    lines.append("| Year | Reps | Sharpe (rep1, rep2, rep3) | Sharpe range | CAGR%(mean) | Canon md5 unique | Determinism |")
    lines.append("|---|---|---|---:|---:|---:|---|")

    year_means: list[tuple[int, float]] = []
    for year in sorted(by_year.keys()):
        reps = by_year[year]
        sharpes = [r["sharpe"] for r in reps if r["sharpe"] is not None]
        canons = [r["trades_canon_md5"] for r in reps]
        cagrs = [r["cagr_pct"] for r in reps if r["cagr_pct"] is not None]
        if not sharpes:
            lines.append(f"| {year} | {len(reps)} | (all None) | — | — | — | FAIL |")
            continue
        sharpe_str = ", ".join(f"{s:.4f}" for s in sharpes)
        sharpe_range = max(sharpes) - min(sharpes)
        canon_unique = len(set(canons))
        det_pass = (sharpe_range <= 0.02 and canon_unique == 1)
        det_str = "PASS (bitwise)" if det_pass else (
            "PARTIAL (canon drift)" if sharpe_range <= 0.02 else "FAIL (Sharpe drift)"
        )
        cagr_mean = sum(cagrs) / len(cagrs) if cagrs else float("nan")
        sharpe_mean = sum(sharpes) / len(sharpes)
        year_means.append((year, sharpe_mean))
        lines.append(
            f"| {year} | {len(reps)} | {sharpe_str} | {sharpe_range:.4f} | "
            f"{cagr_mean:.2f} | {canon_unique}/{len(canons)} | {det_str} |"
        )

    lines.append("")
    lines.append("## Cross-year aggregate")
    lines.append("")
    if year_means:
        means = [m for _, m in year_means]
        agg_mean = statistics.mean(means)
        agg_std = statistics.stdev(means) if len(means) > 1 else 0.0
        agg_min = min(means)
        agg_max = max(means)
        lines.append(f"- **Mean Sharpe across years:** {agg_mean:.4f}")
        lines.append(f"- Std (across-year):              {agg_std:.4f}")
        lines.append(f"- Min:                            {agg_min:.4f} ({[y for y,m in year_means if m == agg_min][0]})")
        lines.append(f"- Max:                            {agg_max:.4f} ({[y for y,m in year_means if m == agg_max][0]})")
        lines.append("")
        lines.append("## Foundation Gate evaluation")
        lines.append("")
        lines.append("Gate criterion: 2025 OOS Sharpe ≥ 0.5 deterministic. Multi-year extension: **mean Sharpe across 2021-2025 ≥ 0.5**.")
        lines.append("")
        if agg_mean >= 0.5:
            lines.append(f"- **Gate status: PASS** (mean Sharpe {agg_mean:.4f} ≥ 0.5)")
        elif agg_mean >= 0.4:
            lines.append(f"- **Gate status: AMBIGUOUS** (mean Sharpe {agg_mean:.4f}, between 0.4 and 0.5)")
        else:
            lines.append(f"- **Gate status: FAIL** (mean Sharpe {agg_mean:.4f} < 0.4 — kill thesis re-engages on multi-year data)")
        worst = min(year_means, key=lambda x: x[1])
        best = max(year_means, key=lambda x: x[1])
        lines.append(f"- Worst year: {worst[0]} (Sharpe {worst[1]:.4f})")
        lines.append(f"- Best year:  {best[0]} (Sharpe {best[1]:.4f})")
        lines.append(f"- Best-vs-worst spread: {best[1] - worst[1]:.4f} (cross-year regime sensitivity)")
    lines.append("")
    lines.append("## Raw run records")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(results, indent=2, default=str))
    lines.append("```")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines))


def main() -> int:
    _reexec_if_hashseed_unset()
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=str, default="2021,2022,2023,2024,2025",
                        help="Comma-separated years to measure.")
    parser.add_argument("--runs", type=int, default=3,
                        help="Reps per year (3 = within-year determinism check).")
    parser.add_argument("--output", type=str,
                        default="docs/Audit/multi_year_foundation_measurement.md",
                        help="Markdown summary path (relative to repo root).")
    parser.add_argument("--json-output", type=str,
                        default="docs/Audit/multi_year_foundation_measurement.json",
                        help="Raw JSON results path.")
    args = parser.parse_args()

    years = [int(y.strip()) for y in args.years.split(",") if y.strip()]

    if not ISOLATED_ANCHOR.exists():
        print("[MULTI-YEAR] No anchor at "
              f"{ISOLATED_ANCHOR}. Run `python -m scripts.run_isolated --save-anchor` first.",
              file=sys.stderr)
        return 1

    results: list[dict] = []
    t_start = time.time()
    total = len(years) * args.runs
    counter = 0

    for year in years:
        for rep in range(1, args.runs + 1):
            counter += 1
            elapsed = time.time() - t_start
            avg_per_run = elapsed / max(counter - 1, 1) if counter > 1 else 0
            eta = avg_per_run * (total - counter + 1)
            print(f"\n===== YEAR {year} REP {rep}/{args.runs} "
                  f"(run {counter}/{total}, elapsed {elapsed/60:.1f}m, "
                  f"ETA {eta/60:.1f}m) =====", flush=True)

            before = {p.name for p in TRADES_DIR.iterdir()
                      if p.is_dir() and p.name != "backup"}
            t_run = time.time()
            try:
                with isolated():
                    summary = _run_year(year)
                run_id = _find_run_id(before) or "?"
                record = {
                    "year": year,
                    "rep": rep,
                    "run_id": run_id,
                    "sharpe": summary.get("Sharpe Ratio"),
                    "cagr_pct": summary.get("CAGR (%)"),
                    "max_drawdown_pct": summary.get("Max Drawdown (%)"),
                    "win_rate_pct": summary.get("Win Rate (%)"),
                    "total_trades": summary.get("Total Trades"),
                    "trades_canon_md5": _trades_canon_md5(run_id) if run_id != "?" else "(no run_id)",
                    "wall_time_seconds": round(time.time() - t_run, 1),
                    "ok": True,
                }
            except Exception as e:
                record = {
                    "year": year,
                    "rep": rep,
                    "ok": False,
                    "error": f"{type(e).__name__}: {e}",
                    "wall_time_seconds": round(time.time() - t_run, 1),
                }
            results.append(record)
            print(f"  Result: {record}")

            json_path = ROOT / args.json_output
            json_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(json.dumps(results, indent=2, default=str))

    md_path = ROOT / args.output
    _format_markdown_report([r for r in results if r.get("ok")], md_path)
    print(f"\n[MULTI-YEAR] Done in {(time.time()-t_start)/60:.1f}m")
    print(f"[MULTI-YEAR] JSON: {ROOT / args.json_output}")
    print(f"[MULTI-YEAR] Markdown summary: {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
