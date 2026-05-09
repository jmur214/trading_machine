"""
scripts/substrate_arms_analytics.py
====================================
Analytics + audit-doc renderer for the substrate-honest two-arm
re-measurement (T-2026-05-08-002).

Reads JSON results produced by `scripts/run_substrate_arms.py` and:
  - Aggregates per-arm headline metrics (mean Sharpe / Sortino / MDD /
    win-rate across years; first-rep bitwise canon-md5 verification)
  - Bootstrap 95% CIs on Sharpe and Sortino, computed on
    daily-returns concatenated across all 5 years from rep-1 of each year
  - Per-edge realized PnL contribution (per arm, per year) from trades.csv
  - Inter-edge daily-PnL correlation matrix per arm
  - Cross-arm comparison + verdict-bucket assignment per spec

Writes:
  - docs/Measurements/2026-05/multi_year_substrate_honest_2026_05_08.md
  - docs/Measurements/2026-05/multi_year_substrate_honest_2026_05_08.json

Re-runnable: rerunning with the same JSON inputs deterministically
produces the same outputs (bootstrap RNG seeded).

Usage:
  python -m scripts.substrate_arms_analytics
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.metrics_engine import MetricsEngine  # noqa: E402

RESULTS_DIR = ROOT / "data" / "measurements" / "substrate_2026_05_08"
TRADE_LOGS = ROOT / "data" / "trade_logs"
OUT_DIR = ROOT / "docs" / "Measurements" / "2026-05"
OUT_MD = OUT_DIR / "multi_year_substrate_honest_2026_05_08.md"
OUT_JSON = OUT_DIR / "multi_year_substrate_honest_2026_05_08.json"

ARM1_EDGES = [
    "gap_fill_v1",
    "volume_anomaly_v1",
    "value_earnings_yield_v1",
    "value_book_to_market_v1",
    "accruals_inv_sloan_v1",
    "accruals_inv_asset_growth_v1",
]
ARM2_EDGES = [
    "gap_fill_v1",
    "volume_anomaly_v1",
    "value_book_to_market_v1",
    "accruals_inv_sloan_v1",
]


def load_records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def _snapshot_path(run_id: str) -> Optional[Path]:
    p1 = TRADE_LOGS / run_id / "portfolio_snapshots.csv"
    p2 = TRADE_LOGS / run_id / f"portfolio_snapshots_{run_id}.csv"
    return p1 if p1.exists() else (p2 if p2.exists() else None)


def _trades_path(run_id: str) -> Optional[Path]:
    p1 = TRADE_LOGS / run_id / "trades.csv"
    p2 = TRADE_LOGS / run_id / f"trades_{run_id}.csv"
    return p1 if p1.exists() else (p2 if p2.exists() else None)


def daily_returns_for_run(run_id: str) -> Optional[pd.Series]:
    path = _snapshot_path(run_id)
    if path is None:
        return None
    try:
        df = pd.read_csv(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").set_index("timestamp")
        eq = pd.to_numeric(df["equity"], errors="coerce").dropna()
        rets = eq.pct_change().dropna()
        return rets
    except Exception:
        return None


def concat_arm_returns(records: list[dict]) -> pd.Series:
    """Concatenate daily returns from rep 1 of each year for an arm.

    Reps within a year are bitwise-identical under the determinism
    harness (verified by canon-md5 unique=1), so any single rep gives
    the same daily-returns series.
    """
    series_list = []
    seen_years = set()
    for r in sorted(records, key=lambda x: (x.get("year", 0), x.get("rep", 0))):
        if not r.get("ok"):
            continue
        year = r.get("year")
        if year in seen_years:
            continue
        if r.get("rep") != 1:
            continue
        run_id = r.get("run_id")
        if not run_id or run_id == "?":
            continue
        rets = daily_returns_for_run(run_id)
        if rets is None or rets.empty:
            continue
        series_list.append(rets)
        seen_years.add(year)
    if not series_list:
        return pd.Series(dtype=float)
    return pd.concat(series_list).sort_index()


def per_arm_headline(records: list[dict]) -> dict:
    by_year: Dict[int, list[dict]] = {}
    for r in records:
        if not r.get("ok"):
            continue
        by_year.setdefault(r["year"], []).append(r)

    rows = []
    sharpes = []
    sortinos = []
    mdds = []
    win_rates = []
    for year in sorted(by_year):
        reps = by_year[year]
        rep_sharpes = [r.get("sharpe") for r in reps if r.get("sharpe") is not None]
        rep_sortinos = [r.get("sortino") for r in reps if r.get("sortino") is not None]
        rep_mdds = [r.get("max_drawdown_pct") for r in reps if r.get("max_drawdown_pct") is not None]
        rep_wrs = [r.get("win_rate_pct") for r in reps if r.get("win_rate_pct") is not None]
        canons = [r.get("trades_canon_md5", "(missing)") for r in reps]
        canon_unique = len(set(canons))
        det_pass = (canon_unique == 1) if reps else False
        rows.append({
            "year": year,
            "n_reps": len(reps),
            "sharpe_mean": (sum(rep_sharpes) / len(rep_sharpes)) if rep_sharpes else None,
            "sharpe_reps": rep_sharpes,
            "sortino_mean": (sum(rep_sortinos) / len(rep_sortinos)) if rep_sortinos else None,
            "mdd_mean": (sum(rep_mdds) / len(rep_mdds)) if rep_mdds else None,
            "win_rate_mean": (sum(rep_wrs) / len(rep_wrs)) if rep_wrs else None,
            "trades_canon_md5_unique": canon_unique,
            "determinism_pass": det_pass,
        })
        if rep_sharpes:
            sharpes.append(sum(rep_sharpes) / len(rep_sharpes))
        if rep_sortinos:
            sortinos.append(sum(rep_sortinos) / len(rep_sortinos))
        if rep_mdds:
            mdds.append(sum(rep_mdds) / len(rep_mdds))
        if rep_wrs:
            win_rates.append(sum(rep_wrs) / len(rep_wrs))

    return {
        "per_year": rows,
        "mean_sharpe": (sum(sharpes) / len(sharpes)) if sharpes else None,
        "mean_sortino": (sum(sortinos) / len(sortinos)) if sortinos else None,
        "mean_mdd_pct": (sum(mdds) / len(mdds)) if mdds else None,
        "mean_win_rate_pct": (sum(win_rates) / len(win_rates)) if win_rates else None,
    }


def bootstrap_arm(records: list[dict]) -> dict:
    rets = concat_arm_returns(records)
    if rets.empty or len(rets) < 30:
        return {"sharpe": None, "sortino": None, "n_obs": int(len(rets))}

    sharpe_dist = MetricsEngine.bootstrap_distribution(
        rets,
        metric_fn=MetricsEngine.sharpe_ratio,
        n_iterations=1000,
        seed=0,
    )
    sortino_dist = MetricsEngine.bootstrap_distribution(
        rets,
        metric_fn=MetricsEngine.sortino_ratio,
        n_iterations=1000,
        seed=0,
    )
    return {
        "n_obs": int(len(rets)),
        "sharpe": sharpe_dist,
        "sortino": sortino_dist,
    }


def per_edge_attribution(records: list[dict], edges: list[str]) -> dict:
    """Per-arm per-edge realized PnL aggregated across years (rep 1 only,
    since reps within year are bitwise identical)."""
    by_year_edge: Dict[int, Dict[str, dict]] = {}
    seen_years = set()
    for r in sorted(records, key=lambda x: (x.get("year", 0), x.get("rep", 0))):
        if not r.get("ok") or r.get("rep") != 1:
            continue
        year = r.get("year")
        if year in seen_years:
            continue
        run_id = r.get("run_id")
        if not run_id or run_id == "?":
            continue
        seen_years.add(year)
        path = _trades_path(run_id)
        if path is None:
            continue
        try:
            df = pd.read_csv(path, low_memory=False)
            df["pnl"] = pd.to_numeric(df.get("pnl"), errors="coerce")
            realized = df.dropna(subset=["pnl"])
            year_dict: Dict[str, dict] = {}
            for eid in edges:
                sub = realized[realized.get("edge_id") == eid]
                if sub.empty:
                    year_dict[eid] = {"pnl_total": 0.0, "n_trades": 0, "win_rate": 0.0}
                    continue
                winners = sub[sub["pnl"] > 0]
                n_total = len(sub)
                year_dict[eid] = {
                    "pnl_total": float(sub["pnl"].sum()),
                    "n_trades": int(n_total),
                    "win_rate": float(len(winners) / n_total) if n_total else 0.0,
                }
            by_year_edge[year] = year_dict
        except Exception as e:
            by_year_edge[year] = {"error": str(e)}

    grand: Dict[str, dict] = {}
    for eid in edges:
        total_pnl = 0.0
        total_trades = 0
        total_winners = 0
        for year_dict in by_year_edge.values():
            ed = year_dict.get(eid, {}) if isinstance(year_dict, dict) else {}
            total_pnl += float(ed.get("pnl_total", 0.0))
            total_trades += int(ed.get("n_trades", 0))
            wr = ed.get("win_rate", 0.0)
            total_winners += int(round(wr * ed.get("n_trades", 0)))
        wr = (total_winners / total_trades) if total_trades else 0.0
        grand[eid] = {
            "pnl_total": total_pnl,
            "n_trades": total_trades,
            "win_rate": wr,
        }
    return {"per_year": by_year_edge, "grand_total": grand}


def correlation_matrix(records: list[dict], edges: list[str]) -> Optional[pd.DataFrame]:
    """Daily-PnL Pearson correlation matrix using rep-1 of each year, concatenated."""
    daily_list = []
    seen_years = set()
    for r in sorted(records, key=lambda x: (x.get("year", 0), x.get("rep", 0))):
        if not r.get("ok") or r.get("rep") != 1:
            continue
        year = r.get("year")
        if year in seen_years:
            continue
        run_id = r.get("run_id")
        if not run_id or run_id == "?":
            continue
        seen_years.add(year)
        path = _trades_path(run_id)
        if path is None:
            continue
        try:
            df = pd.read_csv(path, low_memory=False)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df["pnl"] = pd.to_numeric(df.get("pnl"), errors="coerce")
            realized = df.dropna(subset=["pnl"])
            if realized.empty:
                continue
            realized = realized.copy()
            realized["date"] = realized["timestamp"].dt.normalize()
            pivot = (
                realized.groupby(["date", "edge_id"], as_index=False)["pnl"]
                .sum()
                .pivot(index="date", columns="edge_id", values="pnl")
                .fillna(0.0)
            )
            daily_list.append(pivot)
        except Exception:
            continue
    if not daily_list:
        return None
    full = pd.concat(daily_list).sort_index()
    available = [e for e in edges if e in full.columns]
    if len(available) < 2:
        return None
    sub = full[available]
    sub = sub.loc[(sub != 0).any(axis=1)]
    return sub.corr(method="pearson")


def verdict_bucket(arm1_sharpe: Optional[float], arm2_sharpe: Optional[float]) -> dict:
    """Apply spec verdict framing to (Arm 1, Arm 2) headline Sharpes."""
    if arm1_sharpe is None or arm2_sharpe is None:
        return {"arm1_bucket": "MISSING", "arm2_bucket": "MISSING", "delta": None,
                "contingent_2x2": False, "summary": "headline Sharpe missing for one or both arms"}

    if arm1_sharpe >= 1.0:
        a1 = "HEALTHY (>=1.0) — substrate-honest baseline OK at current 6-active config"
    elif arm1_sharpe >= 0.5:
        a1 = "MODERATE (0.5-1.0) — pruning + HMM more important"
    else:
        a1 = "COLLAPSED (<0.5) — closure didn't recover prior universe-aware result"

    delta = arm2_sharpe - arm1_sharpe
    if delta >= 0.2:
        a2 = "LIFT MEANINGFUL (Δ>=+0.2) — recommendations worth deploying; FIRST run 2x2 attribution"
        contingent = True
    elif delta < 0:
        a2 = "REGRESSION (Δ<0) — diversification of the 2 dropped edges likely load-bearing; do NOT deploy"
        contingent = (abs(delta) >= 0.2)
    else:
        a2 = "NEUTRAL (-0.2<=Δ<0) — pruning + HMM didn't materially help"
        contingent = False

    summary = (
        f"Arm 1 mean Sharpe {arm1_sharpe:.4f} → {a1}. "
        f"Arm 2 mean Sharpe {arm2_sharpe:.4f}, Δ={delta:+.4f} → {a2}. "
        f"Contingent 2x2 decomposition: {'FIRE' if contingent else 'do NOT fire'}."
    )
    return {
        "arm1_bucket": a1,
        "arm2_bucket": a2,
        "delta": delta,
        "contingent_2x2": contingent,
        "summary": summary,
    }


def render_markdown(arm1: dict, arm2: dict, verdict: dict,
                    arm1_corr: Optional[pd.DataFrame],
                    arm2_corr: Optional[pd.DataFrame]) -> str:
    lines: list[str] = []
    lines.append("# Substrate-Honest Re-Measurement — 2026-05-08")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("Spec: `docs/Measurements/2026-05/spec_substrate_honest_remeasurement_2026_05_08.md`")
    lines.append("Task: T-2026-05-08-002")
    lines.append("")
    lines.append("Window 2021-2025, F6 historical S&P 500 universe with missing-CSV closure (d5af02e), ")
    lines.append("3 reps × 5 yearly runs per arm, journal-mode (apply_journal_at_end=True), ")
    lines.append("realistic costs ON, wash-sale OFF, lt-hold OFF.")
    lines.append("")
    lines.append("Post-fix verification: earnings_vol tz regression closed (4b7a14e). ")
    lines.append("yfinance tz audit (T-001) cleared the other 4 edges (no fixes needed).")
    lines.append("")

    lines.append("## Verdict bucket")
    lines.append("")
    lines.append(verdict["summary"])
    lines.append("")

    lines.append("## Cross-arm comparison")
    lines.append("")

    def _fmt(v, spec="{:+.4f}"):
        return spec.format(v) if isinstance(v, (int, float)) else "—"

    a1m = arm1.get("metrics", {})
    a2m = arm2.get("metrics", {})

    def _delta(a, b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return f"{b - a:+.4f}"
        return "—"

    lines.append("| Metric | Arm 1 (6 actives, HMM OFF) | Arm 2 (4 actives, HMM ON minimal_c) | Δ (A2 − A1) |")
    lines.append("|---|---:|---:|---:|")
    lines.append(f"| Mean Sharpe | {_fmt(a1m.get('mean_sharpe'))} | {_fmt(a2m.get('mean_sharpe'))} | {_delta(a1m.get('mean_sharpe'), a2m.get('mean_sharpe'))} |")
    lines.append(f"| Mean Sortino | {_fmt(a1m.get('mean_sortino'))} | {_fmt(a2m.get('mean_sortino'))} | {_delta(a1m.get('mean_sortino'), a2m.get('mean_sortino'))} |")
    lines.append(f"| Mean MDD (%) | {_fmt(a1m.get('mean_mdd_pct'), '{:+.2f}')} | {_fmt(a2m.get('mean_mdd_pct'), '{:+.2f}')} | {_delta(a1m.get('mean_mdd_pct'), a2m.get('mean_mdd_pct'))} |")
    lines.append(f"| Mean Win-Rate (%) | {_fmt(a1m.get('mean_win_rate_pct'), '{:.2f}')} | {_fmt(a2m.get('mean_win_rate_pct'), '{:.2f}')} | {_delta(a1m.get('mean_win_rate_pct'), a2m.get('mean_win_rate_pct'))} |")

    a1b = arm1.get("bootstrap", {})
    a2b = arm2.get("bootstrap", {})
    if a1b.get("sharpe") and a2b.get("sharpe"):
        a1s = a1b["sharpe"]
        a2s = a2b["sharpe"]
        lines.append(f"| Bootstrap Sharpe 95% CI | [{a1s.get('ci_low'):+.3f}, {a1s.get('ci_high'):+.3f}] | [{a2s.get('ci_low'):+.3f}, {a2s.get('ci_high'):+.3f}] | — |")
        a1so = a1b["sortino"]
        a2so = a2b["sortino"]
        lines.append(f"| Bootstrap Sortino 95% CI | [{a1so.get('ci_low'):+.3f}, {a1so.get('ci_high'):+.3f}] | [{a2so.get('ci_low'):+.3f}, {a2so.get('ci_high'):+.3f}] | — |")
    lines.append("")

    for arm_label, arm_data, edges, corr in [
        ("Arm 1", arm1, ARM1_EDGES, arm1_corr),
        ("Arm 2", arm2, ARM2_EDGES, arm2_corr),
    ]:
        lines.append(f"## {arm_label} detail")
        lines.append("")
        lines.append("### Per-year Sharpe")
        lines.append("")
        lines.append("| Year | Reps | Sharpe (mean) | Sharpe range | Canon md5 unique | Determinism |")
        lines.append("|---|---|---:|---:|---:|---|")
        for row in arm_data.get("metrics", {}).get("per_year", []):
            sharpes = row.get("sharpe_reps", [])
            srange = (max(sharpes) - min(sharpes)) if len(sharpes) >= 2 else 0.0
            sm = row.get("sharpe_mean")
            sm_str = f"{sm:.4f}" if sm is not None else "—"
            lines.append(f"| {row['year']} | {row['n_reps']} | {sm_str} | {srange:.4f} | "
                         f"{row['trades_canon_md5_unique']}/{row['n_reps']} | "
                         f"{'PASS (bitwise)' if row['determinism_pass'] else 'FAIL (drift)'} |")
        lines.append("")

        boot = arm_data.get("bootstrap", {})
        if boot.get("sharpe") and boot.get("n_obs", 0) > 30:
            sd = boot["sharpe"]
            sod = boot["sortino"]
            lines.append("### Bootstrap distribution (1000 iters, block-bootstrap)")
            lines.append("")
            lines.append(f"- N daily obs: {boot.get('n_obs')}")
            lines.append(f"- Sharpe point estimate: {sd['point_estimate']:+.4f}; "
                         f"mean {sd['mean']:+.4f}; "
                         f"95% CI [{sd['ci_low']:+.4f}, {sd['ci_high']:+.4f}]; "
                         f"P(Sharpe>0) {sd['p_above_zero']:.3f}")
            lines.append(f"- Sortino point estimate: {sod['point_estimate']:+.4f}; "
                         f"mean {sod['mean']:+.4f}; "
                         f"95% CI [{sod['ci_low']:+.4f}, {sod['ci_high']:+.4f}]; "
                         f"P(Sortino>0) {sod['p_above_zero']:.3f}")
            lines.append("")

        attr = arm_data.get("attribution", {}).get("grand_total", {})
        lines.append("### Per-edge realized PnL contribution (2021-2025)")
        lines.append("")
        lines.append("| edge | total PnL ($) | trades | win rate |")
        lines.append("|---|---:|---:|---:|")
        for eid in edges:
            ed = attr.get(eid, {})
            lines.append(f"| `{eid}` | {ed.get('pnl_total', 0):+,.0f} | "
                         f"{ed.get('n_trades', 0)} | {ed.get('win_rate', 0):.2%} |")
        lines.append("")

        lines.append("### Inter-edge correlation (Pearson, daily PnL)")
        lines.append("")
        if corr is not None and not corr.empty:
            cols = list(corr.columns)
            lines.append("| edge | " + " | ".join(cols) + " |")
            lines.append("|" + "|".join(["---"] * (len(cols) + 1)) + "|")
            for r in cols:
                row = [f"`{r}`"] + [f"{corr.loc[r, c]:+.3f}" for c in cols]
                lines.append("| " + " | ".join(row) + " |")
            high = []
            mod = []
            for i, a in enumerate(corr.columns):
                for b in corr.columns[i + 1:]:
                    v = float(corr.loc[a, b])
                    if abs(v) >= 0.7:
                        high.append((a, b, v))
                    elif abs(v) >= 0.4:
                        mod.append((a, b, v))
            lines.append("")
            if high:
                lines.append("HIGH (|ρ|≥0.7):")
                for a, b, v in high:
                    lines.append(f"- `{a}` vs `{b}`: {v:+.3f}")
            else:
                lines.append("HIGH (|ρ|≥0.7): none.")
            if mod:
                lines.append("MODERATE (0.4≤|ρ|<0.7):")
                for a, b, v in mod:
                    lines.append(f"- `{a}` vs `{b}`: {v:+.3f}")
            else:
                lines.append("MODERATE (0.4≤|ρ|<0.7): none.")
        else:
            lines.append("_Insufficient overlap or missing trade logs._")
        lines.append("")

    lines.append("## Run UUIDs (for downstream tasks)")
    lines.append("")
    for arm_label, arm_data in [("Arm 1", arm1), ("Arm 2", arm2)]:
        lines.append(f"**{arm_label}**:")
        for r in arm_data.get("records", []):
            if r.get("ok"):
                lines.append(f"- year={r['year']} rep={r['rep']}: `{r['run_id']}`")
        lines.append("")

    return "\n".join(lines)


def build(arm1_path: Path, arm2_path: Path) -> dict:
    a1_records = load_records(arm1_path)
    a2_records = load_records(arm2_path)

    arm1 = {
        "records": a1_records,
        "metrics": per_arm_headline(a1_records),
        "bootstrap": bootstrap_arm(a1_records),
        "attribution": per_edge_attribution(a1_records, ARM1_EDGES),
    }
    arm2 = {
        "records": a2_records,
        "metrics": per_arm_headline(a2_records),
        "bootstrap": bootstrap_arm(a2_records),
        "attribution": per_edge_attribution(a2_records, ARM2_EDGES),
    }

    arm1_corr = correlation_matrix(a1_records, ARM1_EDGES)
    arm2_corr = correlation_matrix(a2_records, ARM2_EDGES)

    verdict = verdict_bucket(
        arm1["metrics"].get("mean_sharpe"),
        arm2["metrics"].get("mean_sharpe"),
    )

    md = render_markdown(arm1, arm2, verdict, arm1_corr, arm2_corr)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(md)

    payload = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "verdict": verdict,
        "arm1": {**{k: v for k, v in arm1.items() if k != "records"},
                 "n_runs": len(arm1["records"])},
        "arm2": {**{k: v for k, v in arm2.items() if k != "records"},
                 "n_runs": len(arm2["records"])},
        "arm1_correlation": arm1_corr.to_dict() if arm1_corr is not None else None,
        "arm2_correlation": arm2_corr.to_dict() if arm2_corr is not None else None,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm1", type=str, default=str(RESULTS_DIR / "arm1_results.json"))
    parser.add_argument("--arm2", type=str, default=str(RESULTS_DIR / "arm2_results.json"))
    args = parser.parse_args()
    payload = build(Path(args.arm1), Path(args.arm2))
    print(f"[ANALYTICS] Wrote {OUT_MD}")
    print(f"[ANALYTICS] Wrote {OUT_JSON}")
    print(f"[ANALYTICS] Verdict: {payload['verdict']['summary']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
