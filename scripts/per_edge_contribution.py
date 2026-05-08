"""Per-edge contribution analysis on the 6 active edges.

Companion to the inter-edge correlation matrix scripts. Where the
correlation matrices answer "do these edges move together?", this
script answers "which edges actually CONTRIBUTE to the bottom line?".

For each of the 6 active edges, computes:
  - Total realized PnL across 2021-2025
  - Per-year breakdown
  - Trade count + win rate
  - Average winning vs losing trade
  - Per-edge "share of ensemble PnL" so we can see whether 1-2 edges
    carry the book or whether contribution is balanced

Headline question this answers: of the 6 actives, are any pure
dilution (zero or negative contribution) and we should consider
pausing them via the lifecycle gauntlet?

Usage: python -m scripts.per_edge_contribution
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import date
from typing import Dict, List

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
TRADE_LOGS = REPO / "data" / "trade_logs"

ACTIVE_EDGES = [
    "gap_fill_v1",
    "volume_anomaly_v1",
    "value_earnings_yield_v1",
    "value_book_to_market_v1",
    "accruals_inv_sloan_v1",
    "accruals_inv_asset_growth_v1",
]

YEAR_TO_RUN: Dict[int, str] = {
    2021: "90c9c89d-e36b-444b-9397-845f820cabf7",
    2022: "ba0a1d15-62f6-4a45-a7bb-6eae1a4064ef",
    2023: "d585059e-f8ad-4d59-9c1c-f98b87a70d6e",
    2024: "b6504096-9eff-4573-87af-cd7e30aad8ab",
    2025: "31be49d3-b5de-443e-84dc-f0c8495223a2",
}


def load_trades(run_id: str) -> pd.DataFrame:
    p = TRADE_LOGS / run_id / "trades.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p, low_memory=False)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce")
    return df


def per_edge_year_stats(df: pd.DataFrame, year: int) -> Dict[str, Dict[str, float]]:
    """Per-edge stats for one year. Returns {edge_id: {pnl, n_trades, ...}}."""
    realized = df.dropna(subset=["pnl"])
    if realized.empty:
        return {}
    out: Dict[str, Dict[str, float]] = {}
    for eid in ACTIVE_EDGES:
        sub = realized[realized["edge_id"] == eid]
        if sub.empty:
            out[eid] = {
                "year": year, "pnl_total": 0.0, "n_trades": 0,
                "n_winners": 0, "n_losers": 0, "win_rate": 0.0,
                "avg_winner": 0.0, "avg_loser": 0.0,
                "best_trade": 0.0, "worst_trade": 0.0,
            }
            continue
        winners = sub[sub["pnl"] > 0]["pnl"]
        losers = sub[sub["pnl"] < 0]["pnl"]
        n_total = len(sub)
        out[eid] = {
            "year": year,
            "pnl_total": float(sub["pnl"].sum()),
            "n_trades": int(n_total),
            "n_winners": int(len(winners)),
            "n_losers": int(len(losers)),
            "win_rate": float(len(winners) / n_total) if n_total else 0.0,
            "avg_winner": float(winners.mean()) if not winners.empty else 0.0,
            "avg_loser": float(losers.mean()) if not losers.empty else 0.0,
            "best_trade": float(sub["pnl"].max()),
            "worst_trade": float(sub["pnl"].min()),
        }
    return out


def render_report(per_year: Dict[int, Dict[str, Dict[str, float]]]) -> str:
    years = sorted(per_year.keys())
    lines = [
        "# Per-Edge Contribution — 6 Active Edges (2021-2025)",
        f"\n**Generated:** {date.today().isoformat()}",
        "**Source:** trade-level realized PnL from the 5 deterministic-harness yearly runs.",
        "",
        "## Why this matters",
        "",
        "Inter-edge correlation tells us whether edges move together. This script tells us whether each edge is actually contributing to the bottom line — distinct from co-movement. An edge that's well-decorrelated from the rest but produces zero or negative PnL is pure noise; an edge that's correlated with the others but carries most of the realized PnL is the load-bearing alpha.",
        "",
        "## Headline: total realized PnL by edge, 2021-2025",
        "",
    ]
    totals: List[tuple] = []
    grand_total = 0.0
    for eid in ACTIVE_EDGES:
        total_pnl = 0.0
        total_trades = 0
        total_winners = 0
        for y in years:
            s = per_year[y].get(eid, {})
            total_pnl += float(s.get("pnl_total", 0.0))
            total_trades += int(s.get("n_trades", 0))
            total_winners += int(s.get("n_winners", 0))
        win_rate = total_winners / total_trades if total_trades else 0.0
        totals.append((eid, total_pnl, total_trades, win_rate))
        grand_total += total_pnl

    # Sort by absolute contribution descending
    totals.sort(key=lambda t: t[1], reverse=True)

    lines.append("| edge | total PnL ($) | share of ensemble | trades | win rate |")
    lines.append("|---|---:|---:|---:|---:|")
    for eid, pnl, n, wr in totals:
        share = pnl / grand_total if grand_total != 0 else 0.0
        lines.append(f"| `{eid}` | {pnl:+,.0f} | {share:+.1%} | {n} | {wr:.2%} |")
    lines.append(f"| **ensemble total** | {grand_total:+,.0f} | 100.0% | — | — |")
    lines.append("")

    # Per-year breakdown
    lines.append("## Per-year PnL by edge")
    lines.append("")
    header = "| edge |" + "".join(f" {y} |" for y in years) + " total |"
    sep = "|---|" + "---:|" * (len(years) + 1)
    lines.append(header)
    lines.append(sep)
    for eid in ACTIVE_EDGES:
        row = [f"`{eid}`"]
        total = 0.0
        for y in years:
            s = per_year[y].get(eid, {})
            v = float(s.get("pnl_total", 0.0))
            row.append(f"{v:+,.0f}")
            total += v
        row.append(f"**{total:+,.0f}**")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # Per-year ensemble totals (across all 6)
    lines.append("## Per-year ensemble totals (across 6 active edges only)")
    lines.append("")
    lines.append("| year | ensemble PnL ($) | n trades |")
    lines.append("|---|---:|---:|")
    for y in years:
        ypnl = sum(per_year[y].get(e, {}).get("pnl_total", 0.0) for e in ACTIVE_EDGES)
        ytrades = sum(per_year[y].get(e, {}).get("n_trades", 0) for e in ACTIVE_EDGES)
        lines.append(f"| {y} | {ypnl:+,.0f} | {ytrades} |")
    lines.append("")

    # Win rate + winners/losers
    lines.append("## Trade quality per edge (lifetime 2021-2025)")
    lines.append("")
    lines.append("| edge | trades | win rate | avg winner ($) | avg loser ($) | best ($) | worst ($) |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for eid in ACTIVE_EDGES:
        all_trades_for_edge = []
        n_total = 0
        n_winners = 0
        # Reconstruct numeric stats from per-year (sum is fine for n; for averages we recompute by re-aggregating)
        winners_pnl_sum = 0.0
        losers_pnl_sum = 0.0
        n_w = 0
        n_l = 0
        best = -float("inf")
        worst = float("inf")
        for y in years:
            s = per_year[y].get(eid, {})
            n_total += int(s.get("n_trades", 0))
            yw = int(s.get("n_winners", 0))
            yl = int(s.get("n_losers", 0))
            n_w += yw
            n_l += yl
            n_winners += yw
            winners_pnl_sum += float(s.get("avg_winner", 0.0)) * yw
            losers_pnl_sum += float(s.get("avg_loser", 0.0)) * yl
            best = max(best, float(s.get("best_trade", -float("inf"))))
            worst = min(worst, float(s.get("worst_trade", float("inf"))))
        wr = n_winners / n_total if n_total else 0.0
        avg_w = winners_pnl_sum / n_w if n_w else 0.0
        avg_l = losers_pnl_sum / n_l if n_l else 0.0
        if best == -float("inf"):
            best = 0.0
        if worst == float("inf"):
            worst = 0.0
        lines.append(f"| `{eid}` | {n_total} | {wr:.2%} | {avg_w:+,.2f} | {avg_l:+,.2f} | {best:+,.2f} | {worst:+,.2f} |")
    lines.append("")

    # Highlight findings
    lines.append("## Honest interpretation")
    lines.append("")
    pnl_by_edge = {eid: pnl for (eid, pnl, _, _) in totals}
    sorted_by_pnl = sorted(pnl_by_edge.items(), key=lambda kv: kv[1], reverse=True)
    top = sorted_by_pnl[0]
    second = sorted_by_pnl[1] if len(sorted_by_pnl) > 1 else (None, 0)
    bottom_negative = [(eid, pnl) for eid, pnl in sorted_by_pnl if pnl < 0]
    if top:
        lines.append(f"- **Top contributor:** `{top[0]}` with {top[1]:+,.0f} ({top[1]/grand_total:+.1%} of ensemble).")
    if second[0]:
        lines.append(f"- **Second:** `{second[0]}` with {second[1]:+,.0f} ({second[1]/grand_total:+.1%}).")
    if bottom_negative:
        lines.append(f"- **Negative contributors:** {len(bottom_negative)} edge(s) — net DRAG on ensemble:")
        for eid, pnl in bottom_negative:
            lines.append(f"  - `{eid}`: {pnl:+,.0f}")
        lines.append("  - Investigate via the lifecycle gauntlet — these are candidates for pause/retire if the negative contribution is consistent across years.")
    else:
        lines.append("- No edge has a net-negative contribution across 2021-2025 — every active edge added value.")
    lines.append("")
    lines.append("## Caveats")
    lines.append("")
    lines.append("- Contribution is realized $ PnL, not Sharpe. An edge with a small but consistently positive contribution may have a higher per-trade Sharpe than a high-PnL edge that takes on more variance to get there. Both views matter; this script is the $-attribution view.")
    lines.append("- The 5 yearly runs were separate backtests with their own governor-state. Cross-year comparison is direction-correct but absolute numbers between years embed config + universe drift.")
    lines.append("- Assumes the 6 ACTIVE_EDGES list is current. If edges have been retired or activated since this run, regenerate.")
    return "\n".join(lines)


def main() -> int:
    per_year: Dict[int, Dict[str, Dict[str, float]]] = {}
    for year, run_id in YEAR_TO_RUN.items():
        df = load_trades(run_id)
        if df.empty:
            print(f"[warn] {year}: no trades loaded", file=sys.stderr)
            continue
        per_year[year] = per_edge_year_stats(df, year)
        n_realized = df.dropna(subset=["pnl"]).shape[0]
        print(f"[ok] {year}: {n_realized} realized trades")

    if not per_year:
        print("[error] no data loaded", file=sys.stderr)
        return 1

    report = render_report(per_year)
    out_dir = REPO / "docs" / "Measurements" / "2026-05"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / "per_edge_contribution_2026_05_08.md"
    out_md.write_text(report)
    print(f"[ok] wrote {out_md}")

    # Also emit a JSON for downstream tooling
    import json
    out_json = out_dir / "per_edge_contribution_2026_05_08.json"
    out_json.write_text(json.dumps({
        "generated": date.today().isoformat(),
        "active_edges": ACTIVE_EDGES,
        "per_year": per_year,
    }, indent=2, default=str))
    print(f"[ok] wrote {out_json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
