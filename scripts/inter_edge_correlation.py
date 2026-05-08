"""
Inter-edge correlation matrix on the 6 active edges + recent paused (0.25x) edges.

R1 audit punch-list item: an active ensemble whose edges are pairwise correlated >0.7
is one strategy with extra trades, not a diversified book. This script ingests recent
trade logs across 2021-2025, aggregates daily PnL per edge, computes pairwise Pearson
correlations, and writes a markdown report.

Usage: python -m scripts.inter_edge_correlation
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import date

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
TRADE_LOGS = REPO / "data" / "trade_logs"

# 6 active edges per data/governor/edges.yml at 2026-05-07
ACTIVE_EDGES = [
    "gap_fill_v1",
    "volume_anomaly_v1",
    "value_earnings_yield_v1",
    "value_book_to_market_v1",
    "accruals_inv_sloan_v1",
    "accruals_inv_asset_growth_v1",
]

# Recent multi-year trade logs (one per year, deterministic harness output)
# Identified by: largest mtime<3d trade logs spanning a single year each.
YEAR_TO_RUN: dict[int, str] = {
    2021: "90c9c89d-e36b-444b-9397-845f820cabf7",
    2022: "ba0a1d15-62f6-4a45-a7bb-6eae1a4064ef",
    2023: "d585059e-f8ad-4d59-9c1c-f98b87a70d6e",
    2024: "b6504096-9eff-4573-87af-cd7e30aad8ab",
    2025: "31be49d3-b5de-443e-84dc-f0c8495223a2",
}


def load_trades(run_id: str) -> pd.DataFrame:
    path = TRADE_LOGS / run_id / "trades.csv"
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, low_memory=False)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def daily_pnl_by_edge(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate realized PnL per edge per day. Open trades have empty pnl; we keep
    only realized (non-NaN) rows."""
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce")
    realized = df.dropna(subset=["pnl"])
    if realized.empty:
        return pd.DataFrame()
    realized["date"] = realized["timestamp"].dt.normalize()
    pivot = (
        realized.groupby(["date", "edge_id"], as_index=False)["pnl"]
        .sum()
        .pivot(index="date", columns="edge_id", values="pnl")
        .fillna(0.0)
    )
    return pivot


def compute_correlations(daily: pd.DataFrame, edges: list[str]) -> pd.DataFrame:
    """Daily-PnL Pearson correlation among the requested edges."""
    available = [e for e in edges if e in daily.columns]
    if len(available) < 2:
        return pd.DataFrame()
    sub = daily[available]
    sub = sub.loc[(sub != 0).any(axis=1)]
    return sub.corr(method="pearson")


def render_report(corr: pd.DataFrame, n_days: int, edges_seen: list[str]) -> str:
    lines = [
        "# Inter-Edge Correlation Matrix — 6 Active Edges",
        f"\n**Generated:** {date.today().isoformat()}",
        "**Source:** trade-level realized PnL aggregated daily across 2021-2025 from the most recent multi-year trade logs (5 single-year runs).",
        f"**Days with realized PnL:** {n_days}",
        f"**Edges with realized PnL ≥1 day:** {len(edges_seen)} of {len(ACTIVE_EDGES)}",
        "",
        "## Why this matters",
        "An ensemble of edges whose daily PnL is pairwise correlated >0.7 is one strategy with extra trades, not a diversified book. R1's audit-week-of punch-list flagged this as the cheapest sanity check on whether the 6 active edges are actually distinct, or are 6 names for the same exposure.",
        "",
        "## Correlation matrix (Pearson, daily PnL, 2021-2025 union)",
        "",
    ]
    if corr.empty:
        lines.append("_Insufficient overlap — fewer than 2 edges have realized PnL in the loaded runs._")
        return "\n".join(lines)

    cols = list(corr.columns)
    header = "| edge | " + " | ".join(cols) + " |"
    sep = "|" + "|".join(["---"] * (len(cols) + 1)) + "|"
    lines.append(header)
    lines.append(sep)
    for r in cols:
        row = [f"`{r}`"] + [f"{corr.loc[r, c]:+.3f}" for c in cols]
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # Flag concerning pairs
    high_pairs: list[tuple[str, str, float]] = []
    moderate_pairs: list[tuple[str, str, float]] = []
    for i, a in enumerate(corr.columns):
        for b in corr.columns[i + 1:]:
            v = float(corr.loc[a, b])
            if abs(v) >= 0.7:
                high_pairs.append((a, b, v))
            elif abs(v) >= 0.4:
                moderate_pairs.append((a, b, v))

    lines.append("## Interpretation")
    lines.append("")
    if high_pairs:
        lines.append("### HIGH (|ρ| ≥ 0.7) — these edges are functionally one strategy")
        for a, b, v in high_pairs:
            lines.append(f"- `{a}` vs `{b}`: **{v:+.3f}**")
        lines.append("")
    else:
        lines.append("### HIGH (|ρ| ≥ 0.7) — none. Active set is not collinear at the daily level.")
        lines.append("")
    if moderate_pairs:
        lines.append("### MODERATE (0.4 ≤ |ρ| < 0.7) — overlap, but not collapse")
        for a, b, v in moderate_pairs:
            lines.append(f"- `{a}` vs `{b}`: **{v:+.3f}**")
        lines.append("")
    else:
        lines.append("### MODERATE (0.4 ≤ |ρ| < 0.7) — none.")
        lines.append("")

    lines.append("## Caveats")
    lines.append("")
    lines.append("- Daily aggregation. Intra-day overlap (signal correlation) is not measured here; only realized PnL co-movement.")
    lines.append("- Trade logs include paused-at-0.25× edges; this matrix filters to the 6 active edges only.")
    lines.append("- Realized-only PnL means closed-trade days. Edges with very long hold horizons can show artificially low correlation if they exit on different cadences.")
    lines.append("- 2021-2025 union; per-regime correlation may differ. Bear/bull regimes can converge or diverge correlations meaningfully.")
    lines.append("")
    lines.append("## What's NOT here (yet)")
    lines.append("")
    lines.append("- Signal-level correlation (raw edge scores per ticker per day) — would require re-running with edge-output capture; deferred.")
    lines.append("- Regime-conditional correlation matrix — split by regime label in the trade log; future enhancement.")
    return "\n".join(lines)


def main() -> int:
    frames: list[pd.DataFrame] = []
    for year, run_id in YEAR_TO_RUN.items():
        df = load_trades(run_id)
        if df.empty:
            print(f"[warn] {year} run {run_id}: no trades loaded", file=sys.stderr)
            continue
        daily = daily_pnl_by_edge(df)
        if not daily.empty:
            frames.append(daily)
            print(f"[ok] {year}: {len(daily)} trading days, edges={list(daily.columns)}", file=sys.stderr)

    if not frames:
        print("No trade-log frames loaded; aborting.", file=sys.stderr)
        return 1

    daily_all = pd.concat(frames, axis=0).sort_index()
    daily_all = daily_all.groupby(daily_all.index).sum()

    edges_seen = [e for e in ACTIVE_EDGES if e in daily_all.columns]
    corr = compute_correlations(daily_all, ACTIVE_EDGES)
    n_days = int((daily_all[edges_seen] != 0).any(axis=1).sum()) if edges_seen else 0

    report = render_report(corr, n_days, edges_seen)
    out_dir = REPO / "docs" / "Measurements" / "2026-05"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / "inter_edge_correlation_2026_05_07.md"
    out_md.write_text(report)

    if not corr.empty:
        out_csv = out_dir / "inter_edge_correlation_2026_05_07.csv"
        corr.to_csv(out_csv)
        print(f"Wrote {out_md} and {out_csv}")
    else:
        print(f"Wrote {out_md} (correlation matrix empty — see report)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
