"""Regime-conditional inter-edge correlation matrix.

Companion to ``scripts/inter_edge_correlation.py`` which computed the
unconditional correlation. This script splits the matrix by regime
label so we can see whether edges decorrelate under stress (good — real
diversification when you need it) or correlate (bad — diversification
disappears in the crisis exactly when it would matter).

Usage: python -m scripts.inter_edge_correlation_regime

The 6 active edges (per data/governor/edges.yml at 2026-05-08):
  gap_fill_v1, volume_anomaly_v1, value_earnings_yield_v1,
  value_book_to_market_v1, accruals_inv_sloan_v1,
  accruals_inv_asset_growth_v1
"""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import date
from typing import Dict, List, Optional

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

# Same 5 yearly runs the unconditional script used.
YEAR_TO_RUN: Dict[int, str] = {
    2021: "90c9c89d-e36b-444b-9397-845f820cabf7",
    2022: "ba0a1d15-62f6-4a45-a7bb-6eae1a4064ef",
    2023: "d585059e-f8ad-4d59-9c1c-f98b87a70d6e",
    2024: "b6504096-9eff-4573-87af-cd7e30aad8ab",
    2025: "31be49d3-b5de-443e-84dc-f0c8495223a2",
}

# Engine E's 5-state HMM emits these labels (per regime_detector). The
# regime_label column on trades.csv is the per-trade label captured at
# entry time. We bucket into BENIGN (expansionary) vs ADVERSE (anything
# stressed) so the matrix has enough sample per cell.
BENIGN_REGIMES = {"robust_expansion", "emerging_expansion"}
ADVERSE_REGIMES = {"cautious_decline", "market_turmoil", "transitional"}


def load_trades(run_id: str) -> pd.DataFrame:
    p = TRADE_LOGS / run_id / "trades.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p, low_memory=False)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def daily_pnl_by_edge(df: pd.DataFrame) -> pd.DataFrame:
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


def daily_regime_per_date(df: pd.DataFrame) -> pd.Series:
    """Return the dominant (mode) regime label per trading day. When a
    day spans multiple regime states (rare; intra-day regime updates),
    take the most-frequent label."""
    if df.empty:
        return pd.Series(dtype=str)
    df = df.copy()
    df["date"] = df["timestamp"].dt.normalize()
    by_date = df.groupby("date")["regime_label"].agg(
        lambda s: s.mode().iloc[0] if not s.mode().empty else "unknown"
    )
    return by_date


def bucket_regimes(labels: pd.Series) -> pd.Series:
    """Map per-day regime labels into {benign, adverse, other}."""
    def _bucket(s: str) -> str:
        if s in BENIGN_REGIMES:
            return "benign"
        if s in ADVERSE_REGIMES:
            return "adverse"
        return "other"
    return labels.apply(_bucket)


def correlation_for_bucket(
    daily: pd.DataFrame,
    regime_buckets: pd.Series,
    bucket: str,
    edges: List[str],
) -> Optional[pd.DataFrame]:
    if daily.empty or regime_buckets.empty:
        return None
    available = [e for e in edges if e in daily.columns]
    if len(available) < 2:
        return None
    # Inner-join daily PnL with regime buckets on date
    aligned = daily[available].join(regime_buckets.rename("bucket"), how="inner")
    sub = aligned[aligned["bucket"] == bucket].drop(columns=["bucket"])
    sub = sub.loc[(sub != 0).any(axis=1)]
    if len(sub) < 12:  # need ≥12 days for a meaningful correlation
        return None
    return sub.corr(method="pearson")


def render_md_table(corr: pd.DataFrame) -> str:
    cols = list(corr.columns)
    lines = ["| edge | " + " | ".join(cols) + " |"]
    lines.append("|" + "|".join(["---"] * (len(cols) + 1)) + "|")
    for r in cols:
        row = [f"`{r}`"] + [f"{corr.loc[r, c]:+.3f}" for c in cols]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def render_report(
    corr_benign: Optional[pd.DataFrame],
    corr_adverse: Optional[pd.DataFrame],
    corr_unconditional: Optional[pd.DataFrame],
    n_days_benign: int,
    n_days_adverse: int,
    n_days_other: int,
) -> str:
    lines = [
        "# Regime-Conditional Inter-Edge Correlation — 6 Active Edges",
        f"\n**Generated:** {date.today().isoformat()}",
        "**Source:** trade-level realized PnL from 5 deterministic-harness multi-year runs (2021-2025), bucketed by regime_label (Engine E HMM).",
        "",
        "## Bucketing",
        "",
        "- **benign** = `robust_expansion ∪ emerging_expansion` (expansionary regimes)",
        "- **adverse** = `cautious_decline ∪ market_turmoil ∪ transitional`",
        "- **other** = unmapped or unknown",
        "",
        f"| bucket | trading days |",
        f"|---|---:|",
        f"| benign | {n_days_benign} |",
        f"| adverse | {n_days_adverse} |",
        f"| other | {n_days_other} |",
        "",
        "## Why this matters",
        "",
        "An ensemble whose edges decorrelate ONLY in benign regimes is fake diversification. The crisis is exactly when correlations spike (everything sells off together) and you actually need uncorrelated bets. Splitting the inter-edge correlation matrix by regime tells us whether the 6-active set holds together when it matters.",
        "",
    ]

    if corr_unconditional is not None:
        lines.append("## Unconditional (all-regime) correlation matrix — for reference")
        lines.append("")
        lines.append(render_md_table(corr_unconditional))
        lines.append("")

    if corr_benign is not None:
        lines.append("## Benign-regime correlation matrix")
        lines.append("")
        lines.append(render_md_table(corr_benign))
        lines.append("")
    else:
        lines.append("## Benign-regime correlation matrix — INSUFFICIENT DATA")
        lines.append("")

    if corr_adverse is not None:
        lines.append("## Adverse-regime correlation matrix")
        lines.append("")
        lines.append(render_md_table(corr_adverse))
        lines.append("")
    else:
        lines.append("## Adverse-regime correlation matrix — INSUFFICIENT DATA")
        lines.append("")

    if corr_benign is not None and corr_adverse is not None:
        lines.append("## Pairwise delta (adverse − benign)")
        lines.append("")
        lines.append("Positive delta = correlation INCREASES under stress (bad — diversification disappears). Negative delta = correlation DROPS under stress (good — edges become more independent). Pairs are listed only when both buckets had enough data.")
        lines.append("")
        cols = sorted(set(corr_benign.columns) & set(corr_adverse.columns))
        lines.append(f"| pair | benign ρ | adverse ρ | Δ (adv−ben) |")
        lines.append(f"|---|---:|---:|---:|")
        deltas = []
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                rb = float(corr_benign.loc[a, b])
                ra = float(corr_adverse.loc[a, b])
                d = ra - rb
                deltas.append((a, b, rb, ra, d))
        deltas.sort(key=lambda t: t[4], reverse=True)
        for a, b, rb, ra, d in deltas:
            arrow = "↑" if d > 0.05 else ("↓" if d < -0.05 else "·")
            lines.append(f"| `{a}` × `{b}` | {rb:+.3f} | {ra:+.3f} | {d:+.3f} {arrow} |")
        lines.append("")

        # Honest caveats
        lines.append("## Caveats")
        lines.append("")
        lines.append("- Adverse-regime sample is small (Engine E's 5-state HMM rarely fires `market_turmoil`; per-day count is much smaller than benign). Per-pair correlation under adverse can be a 30-100 day estimate vs 600+ days for benign — wide CIs.")
        lines.append("- The regime label is the LABEL AT ENTRY of the trade. PnL realizes later when the trade closes; if regime flipped between entry and exit, the per-day attribution may not perfectly match the regime that produced the day's actual mark-to-market.")
        lines.append("- Daily realized PnL only — same caveat as the unconditional matrix. Intra-day signal correlation is not measured here.")
    return "\n".join(lines)


def main() -> int:
    frames: list = []
    regime_frames: list = []
    for year, run_id in YEAR_TO_RUN.items():
        df = load_trades(run_id)
        if df.empty:
            continue
        daily = daily_pnl_by_edge(df)
        regime = daily_regime_per_date(df)
        if not daily.empty:
            frames.append(daily)
        if not regime.empty:
            regime_frames.append(regime)

    if not frames or not regime_frames:
        print("[error] no data loaded", file=sys.stderr)
        return 1

    daily_all = pd.concat(frames, axis=0).sort_index()
    daily_all = daily_all.groupby(daily_all.index).sum()

    regime_all = pd.concat(regime_frames, axis=0).sort_index()
    # Dedupe by date (taking first label per date — should already be unique-per-year)
    regime_all = regime_all[~regime_all.index.duplicated(keep="first")]
    bucketed = bucket_regimes(regime_all)

    # Unconditional matrix for reference
    available_edges = [e for e in ACTIVE_EDGES if e in daily_all.columns]
    if len(available_edges) < 2:
        print("[error] fewer than 2 active edges have realized PnL", file=sys.stderr)
        return 1
    sub = daily_all[available_edges]
    sub = sub.loc[(sub != 0).any(axis=1)]
    corr_unconditional = sub.corr(method="pearson")

    # Per-bucket
    corr_benign = correlation_for_bucket(daily_all, bucketed, "benign", ACTIVE_EDGES)
    corr_adverse = correlation_for_bucket(daily_all, bucketed, "adverse", ACTIVE_EDGES)

    # Day counts per bucket (only days with ≥1 realized-PnL on any active edge)
    aligned = daily_all[available_edges].join(bucketed.rename("bucket"), how="inner")
    aligned = aligned.loc[(aligned[available_edges] != 0).any(axis=1)]
    bucket_counts = aligned["bucket"].value_counts().to_dict()
    n_benign = int(bucket_counts.get("benign", 0))
    n_adverse = int(bucket_counts.get("adverse", 0))
    n_other = int(bucket_counts.get("other", 0))

    report = render_report(
        corr_benign=corr_benign,
        corr_adverse=corr_adverse,
        corr_unconditional=corr_unconditional,
        n_days_benign=n_benign,
        n_days_adverse=n_adverse,
        n_days_other=n_other,
    )

    out_dir = REPO / "docs" / "Measurements" / "2026-05"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_md = out_dir / "inter_edge_correlation_regime_2026_05_08.md"
    out_md.write_text(report)

    if corr_benign is not None:
        corr_benign.to_csv(out_dir / "inter_edge_correlation_regime_benign_2026_05_08.csv")
    if corr_adverse is not None:
        corr_adverse.to_csv(out_dir / "inter_edge_correlation_regime_adverse_2026_05_08.csv")

    print(f"[ok] wrote {out_md}")
    print(f"     benign days={n_benign}, adverse days={n_adverse}, other={n_other}")
    if corr_benign is not None and corr_adverse is not None:
        # Headline: average pairwise correlation in each bucket
        cols = sorted(set(corr_benign.columns) & set(corr_adverse.columns))
        ben_off = []
        adv_off = []
        for i, a in enumerate(cols):
            for b in cols[i + 1:]:
                ben_off.append(float(corr_benign.loc[a, b]))
                adv_off.append(float(corr_adverse.loc[a, b]))
        if ben_off and adv_off:
            print(f"     mean off-diag ρ: benign={sum(ben_off)/len(ben_off):+.3f} adverse={sum(adv_off)/len(adv_off):+.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
