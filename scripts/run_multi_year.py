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
      --output docs/Measurements/2026-05/multi_year_foundation_measurement.md

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


def _run_year(year: int, use_historical_universe: bool = False) -> dict:
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
        use_historical_universe=use_historical_universe,
    )


def _safe_extended_metrics(run_id: str) -> dict | None:
    """
    Best-effort load of extended metrics (PSR, IR, Calmar, etc.) for a run_id.
    Returns None on any failure — the caller should fall back to the headline-
    Sharpe-only path so the report still writes. Added 2026-05-09 evening per
    the metric-framework upgrade.
    """
    try:
        from core.measurement_reporter import compute_extended_metrics
        return compute_extended_metrics(run_id)
    except Exception:
        return None


def _format_markdown_report(
    results: list[dict],
    output_path: Path,
    use_historical_universe: bool = False,
) -> None:
    """Write a human-readable summary to docs/Measurements/<year-month>/."""
    by_year: dict[int, list[dict]] = {}
    for r in results:
        by_year.setdefault(r["year"], []).append(r)

    # Compute extended metrics (PSR / IR / Calmar / Sortino / Tail / Skew /
    # Kurt / Ulcer) per (year, rep) using the first rep as the
    # representative — within-year reps are bitwise-identical under
    # determinism, so any single rep gives the same extended metrics.
    extended_by_year: dict[int, dict] = {}
    for year, reps in by_year.items():
        for r in reps:
            rid = r.get("run_id") or "?"
            if rid != "?":
                ext = _safe_extended_metrics(rid)
                if ext is not None:
                    extended_by_year[year] = ext
                    break

    lines: list[str] = []
    lines.append("# Multi-Year Foundation Measurement")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"Universe mode: "
                 f"{'historical (survivorship-aware S&P 500)' if use_historical_universe else 'static (config/backtest_settings.json tickers)'}")
    lines.append(f"Total runs: {len(results)} ({len(by_year)} years × {len(next(iter(by_year.values())))} reps)")
    lines.append("")
    lines.append("## Per-year results")
    lines.append("")
    if extended_by_year:
        lines.append("| Year | Sharpe | PSR(>0) | Sortino | Calmar | IR vs SPY | Skew | Kurt | Tail | Ulcer | MDD% | Determinism |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    else:
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
        sharpe_range = max(sharpes) - min(sharpes)
        canon_unique = len(set(canons))
        det_pass = (sharpe_range <= 0.02 and canon_unique == 1)
        det_str = "PASS (bitwise)" if det_pass else (
            "PARTIAL (canon drift)" if sharpe_range <= 0.02 else "FAIL (Sharpe drift)"
        )
        cagr_mean = sum(cagrs) / len(cagrs) if cagrs else float("nan")
        sharpe_mean = sum(sharpes) / len(sharpes)
        year_means.append((year, sharpe_mean))
        ext = extended_by_year.get(year)
        if ext is not None:
            lines.append(
                f"| {year} | {sharpe_mean:.4f} | {ext['PSR']:.3f} | "
                f"{ext['Sortino']:.3f} | {ext['Calmar']:.3f} | "
                f"{ext['Information Ratio']:.3f} | "
                f"{ext['Skewness']:.3f} | {ext['Excess Kurtosis']:.3f} | "
                f"{ext['Tail Ratio']:.3f} | {ext['Ulcer Index']:.2f} | "
                f"{ext['Max Drawdown %']:.2f} | {det_str} |"
            )
        else:
            sharpe_str = ", ".join(f"{s:.4f}" for s in sharpes)
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

    # Extended-metric aggregate (PSR / IR median across years)
    if extended_by_year:
        lines.append("")
        lines.append("## Extended metric framework (2026-05-09 upgrade)")
        lines.append("")
        psrs = [ext["PSR"] for ext in extended_by_year.values()]
        irs = [ext["Information Ratio"] for ext in extended_by_year.values()]
        calmars = [ext["Calmar"] for ext in extended_by_year.values()]
        skews = [ext["Skewness"] for ext in extended_by_year.values()]
        if psrs:
            lines.append(f"- **PSR(SR>0) median across years: {statistics.median(psrs):.3f}** "
                         f"(min {min(psrs):.3f}, max {max(psrs):.3f})")
            lines.append("  Interpretation: probability the true Sharpe is > 0 in each year. "
                         "PSR ≥ 0.95 = strong evidence of skill; ≥ 0.80 = moderate; < 0.50 = no evidence.")
        if irs:
            lines.append(f"- **IR vs SPY median: {statistics.median(irs):.3f}** "
                         f"(positive = beating SPY on tracking error; negative = underperforming)")
        if calmars:
            lines.append(f"- Calmar median: {statistics.median(calmars):.3f}  "
                         f"(drawdown-adjusted; relevant for Goal A — compound)")
        if skews:
            avg_skew = statistics.mean(skews)
            lines.append(f"- Skewness mean: {avg_skew:.3f}  "
                         f"({'right-skewed (asymmetric upside)' if avg_skew > 0.2 else 'left-skewed (negative tail risk)' if avg_skew < -0.2 else 'roughly symmetric'})")
        lines.append("")
        lines.append("**Headline metric (per 2026-05-09 framework upgrade):** PSR median, not Sharpe mean. "
                     "Sharpe mean kept above for backward compatibility.")

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
                        default="docs/Measurements/2026-05/multi_year_foundation_measurement.md",
                        help="Markdown summary path (relative to repo root).")
    parser.add_argument("--json-output", type=str,
                        default="docs/Measurements/2026-05/multi_year_foundation_measurement.json",
                        help="Raw JSON results path.")
    parser.add_argument("--use-historical-universe", action="store_true",
                        help="Resolve survivorship-bias-aware S&P 500 union "
                             "for the backtest window instead of the static "
                             "ticker list. Requires "
                             "data/universe/sp500_membership.parquet.")
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
                    summary = _run_year(year, use_historical_universe=args.use_historical_universe)
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
    _format_markdown_report(
        [r for r in results if r.get("ok")],
        md_path,
        use_historical_universe=args.use_historical_universe,
    )
    print(f"\n[MULTI-YEAR] Done in {(time.time()-t_start)/60:.1f}m")
    print(f"[MULTI-YEAR] JSON: {ROOT / args.json_output}")
    print(f"[MULTI-YEAR] Markdown summary: {md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
