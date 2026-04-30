"""Phase 2.10c diagnostic: per-edge per-year PnL attribution across the
in-sample anchor (UUID abf68c8e..., 2021-2024) and the 2025 OOS run
(UUID 72ec531d...). Pure pandas — no new backtests.

Question: which edges are stable across years vs regime-conditional vs
noise vs paused-but-actually-consistent?

Approach
--------
1. Concatenate `trades.csv` from both runs.
2. PnL lives on `exit` / `stop` / `take_profit` rows; entries have NaN.
   Attribute exit-row PnL to the year of the exit timestamp.
3. Per (edge, year) compute:
     - sum_pnl ($)
     - annualized contribution (% of $100k starting capital)
     - Sharpe-style (daily PnL / std × √252, where daily PnL is the
       per-day sum of attributed exits for that edge)
     - fill_count_entries (number of entry events that year)
4. Pivot into the headline tables and write to
   docs/Audit/per_edge_per_year_attribution_2026_04.md.

Run:
    python scripts/per_edge_per_year_attribution.py [--out PATH]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
ANCHOR_UUID = "abf68c8e-1384-4db4-822c-d65894af70a1"  # 2021-2024 in-sample
OOS_UUID = "72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34"     # 2025 OOS
INITIAL_CAPITAL = 100_000.0
TRADING_DAYS = 252


def _load_trades() -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    for uuid_ in (ANCHOR_UUID, OOS_UUID):
        p = ROOT / "data" / "trade_logs" / uuid_ / "trades.csv"
        df = pd.read_csv(
            p,
            usecols=[
                "timestamp", "ticker", "side", "qty", "fill_price",
                "pnl", "edge", "trigger", "regime_label",
            ],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["run_uuid"] = uuid_
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    out["year"] = out["timestamp"].dt.year
    return out


def _load_lifecycle_status() -> Dict[str, Dict[str, str]]:
    """Map edge_id -> {status, tier} from the registry."""
    data = yaml.safe_load((ROOT / "data" / "governor" / "edges.yml").read_text())
    return {
        e["edge_id"]: {"status": e.get("status", "?"),
                       "tier": e.get("tier", "?")}
        for e in data.get("edges", [])
    }


def _per_edge_per_year_pnl(trades: pd.DataFrame) -> pd.DataFrame:
    """$ PnL summed per (edge, year). Only exit rows carry PnL."""
    exits = trades.loc[
        trades.trigger.isin(["exit", "stop", "take_profit"])
        & trades.pnl.notna()
    ].copy()
    exits["edge"] = exits["edge"].fillna("Unknown")
    return (
        exits.groupby(["edge", "year"])["pnl"]
        .sum()
        .unstack("year")
        .fillna(0.0)
    )


def _per_edge_per_year_sharpe(trades: pd.DataFrame) -> pd.DataFrame:
    """Sharpe-style metric per (edge, year):
        annualized return / annualized vol
    where the daily series is the sum of exit-row PnL on that day,
    normalized by the $100k starting capital so it's a pseudo-return.

    Days with no exits are filled with 0 (the edge contributed nothing).
    Vol is computed only over actual trading days in the year (not all
    365 calendar days), so the normalization across years is fair.

    NaN where the edge had no fills that year, or vol == 0 (single trade)."""
    exits = trades.loc[
        trades.trigger.isin(["exit", "stop", "take_profit"])
        & trades.pnl.notna()
    ].copy()
    exits["date"] = exits["timestamp"].dt.normalize()
    exits["edge"] = exits["edge"].fillna("Unknown")

    daily = (
        exits.groupby(["edge", "year", "date"])["pnl"]
        .sum()
        .reset_index()
    )
    daily["ret"] = daily["pnl"] / INITIAL_CAPITAL

    # For vol denominator we want all trading days in that year, not just
    # days the edge fired. Build a per-year trading-day count from the
    # union of exit dates across all edges (this approximates the
    # backtest's open-market days).
    all_dates_per_year = (
        exits.groupby("year")["date"].nunique().to_dict()
    )

    rows = []
    for (edge, year), g in daily.groupby(["edge", "year"]):
        n_days = max(int(all_dates_per_year.get(year, 0)), 1)
        # Pad days the edge didn't trade with zero return.
        daily_returns = np.zeros(n_days, dtype=float)
        # Place observed returns into the head; we don't have a full
        # date axis here, but for vol/mean Sharpe purposes the order
        # doesn't matter — what matters is mean & std over n_days.
        observed = g["ret"].values
        daily_returns[: len(observed)] = observed
        mean_d = daily_returns.mean()
        std_d = daily_returns.std(ddof=1)
        if std_d == 0 or len(observed) < 2:
            sharpe = np.nan
        else:
            sharpe = (mean_d / std_d) * np.sqrt(TRADING_DAYS)
        rows.append({"edge": edge, "year": year, "sharpe_like": sharpe})

    return (
        pd.DataFrame(rows)
        .pivot(index="edge", columns="year", values="sharpe_like")
    )


def _per_edge_per_year_fillcount(trades: pd.DataFrame) -> pd.DataFrame:
    """Number of ENTRY events per (edge, year). Distinguishes 'low PnL
    because it rarely fires' from 'fires often, loses on average'."""
    entries = trades.loc[trades.trigger == "entry"].copy()
    entries["edge"] = entries["edge"].fillna("Unknown")
    return (
        entries.groupby(["edge", "year"])
        .size()
        .unstack("year")
        .fillna(0)
        .astype(int)
    )


def _classify(
    pnl_pct: pd.DataFrame,  # already normalized to % of $100k
) -> pd.DataFrame:
    """Per-edge classification:
       - stable:          positive in ≥ 4 of 5 years AND mean > 0.5%
       - noise/decay:     mean ≤ 0 OR negative in ≥ 3 of 5 years
       - regime-cond.:    mixed (both ≥1 clearly positive AND ≥1 clearly
                          negative year, magnitude > 0.5% on each side)
       - sparse:          fired in fewer than 2 years
    We compute on *years where the edge fired* — a year of literal zero
    PnL (no fills) doesn't count as "negative."
    """
    rows = []
    years = sorted(pnl_pct.columns)
    for edge, row in pnl_pct.iterrows():
        nonzero = row[row != 0]
        n_years_active = (nonzero != 0).sum()
        if n_years_active < 2:
            cls = "sparse"
        else:
            n_pos = (nonzero > 0.5).sum()    # > 0.5% return contribution
            n_neg = (nonzero < -0.5).sum()
            mean_pct = float(row.mean())  # mean across all 5 years (zeros count)
            mean_active = float(nonzero.mean())
            if n_pos >= 4 and mean_pct > 0.5:
                cls = "stable"
            elif n_pos >= 1 and n_neg >= 1:
                cls = "regime-conditional"
            elif mean_active <= 0 or n_neg >= 3:
                cls = "noise"
            else:
                cls = "weak-positive"
        rows.append({
            "edge": edge,
            "n_years_active": int(n_years_active),
            "mean_pct_all_years": float(row.mean()),
            "mean_pct_active_years": float(nonzero.mean()) if n_years_active else 0.0,
            "min_year_pct": float(row.min()),
            "max_year_pct": float(row.max()),
            "n_pos_years": int((row > 0.5).sum()),
            "n_neg_years": int((row < -0.5).sum()),
            "classification": cls,
        })
    return pd.DataFrame(rows).set_index("edge")


def _md_table_pct(df: pd.DataFrame, ndp: int = 2) -> str:
    """Render a numeric DataFrame as a markdown table with % suffix."""
    cols = list(df.columns)
    header = "| edge | " + " | ".join(str(c) for c in cols) + " |"
    sep = "| --- | " + " | ".join(["---:"] * len(cols)) + " |"
    lines = [header, sep]
    for edge, row in df.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if pd.isna(v):
                cells.append("—")
            else:
                cells.append(f"{v:+.{ndp}f}%")
        lines.append(f"| `{edge}` | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _md_table_sharpe(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    header = "| edge | " + " | ".join(str(c) for c in cols) + " |"
    sep = "| --- | " + " | ".join(["---:"] * len(cols)) + " |"
    lines = [header, sep]
    for edge, row in df.iterrows():
        cells = []
        for c in cols:
            v = row[c]
            if pd.isna(v):
                cells.append("—")
            else:
                cells.append(f"{v:+.2f}")
        lines.append(f"| `{edge}` | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _md_table_int(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    header = "| edge | " + " | ".join(str(c) for c in cols) + " |"
    sep = "| --- | " + " | ".join(["---:"] * len(cols)) + " |"
    lines = [header, sep]
    for edge, row in df.iterrows():
        cells = [str(int(row[c])) if not pd.isna(row[c]) else "0"
                 for c in cols]
        lines.append(f"| `{edge}` | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="docs/Audit/per_edge_per_year_attribution_2026_04.md")
    ap.add_argument("--csv-out", default="data/research/per_edge_per_year_2026_04.csv")
    args = ap.parse_args()

    print(f"[ATTRIB] Loading trade logs: {ANCHOR_UUID} + {OOS_UUID}")
    trades = _load_trades()
    print(f"[ATTRIB] Loaded {len(trades):,} rows, "
          f"years {sorted(trades.year.unique().tolist())}")

    pnl = _per_edge_per_year_pnl(trades)
    pnl_pct = pnl / INITIAL_CAPITAL * 100  # % of starting capital
    sharpe = _per_edge_per_year_sharpe(trades)
    fills = _per_edge_per_year_fillcount(trades)

    # Reindex all three on the union of edges (some may have no exits)
    all_edges = sorted(set(pnl_pct.index) | set(sharpe.index) | set(fills.index))
    pnl_pct = pnl_pct.reindex(all_edges).fillna(0.0)
    sharpe = sharpe.reindex(all_edges)
    fills = fills.reindex(all_edges).fillna(0).astype(int)

    # Drop pseudo-edge "Unknown" if present (untracked / regime overlay)
    for tab in (pnl_pct, sharpe, fills):
        if "Unknown" in tab.index:
            tab.drop("Unknown", inplace=True)

    # Year columns: 2021..2025
    year_cols = [2021, 2022, 2023, 2024, 2025]
    for col in year_cols:
        if col not in pnl_pct.columns:
            pnl_pct[col] = 0.0
        if col not in sharpe.columns:
            sharpe[col] = np.nan
        if col not in fills.columns:
            fills[col] = 0
    pnl_pct = pnl_pct[year_cols]
    sharpe = sharpe[year_cols]
    fills = fills[year_cols]

    cls = _classify(pnl_pct)
    status_map = _load_lifecycle_status()

    # Sort by mean PnL across years for readability (descending)
    order = pnl_pct.mean(axis=1).sort_values(ascending=False).index.tolist()
    pnl_pct = pnl_pct.loc[order]
    sharpe = sharpe.loc[order]
    fills = fills.loc[order]
    cls = cls.loc[order]

    # ---- write CSV with everything for downstream use ----
    out_csv = ROOT / args.csv_out
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    combined = pnl_pct.copy()
    combined.columns = [f"pnl_pct_{c}" for c in combined.columns]
    sharpe2 = sharpe.copy()
    sharpe2.columns = [f"sharpe_{c}" for c in sharpe2.columns]
    fills2 = fills.copy()
    fills2.columns = [f"fills_{c}" for c in fills2.columns]
    combined = combined.join(sharpe2).join(fills2).join(cls)
    combined["lifecycle_status"] = [
        status_map.get(e, {}).get("status", "?") for e in combined.index
    ]
    combined["lifecycle_tier"] = [
        status_map.get(e, {}).get("tier", "?") for e in combined.index
    ]
    combined.to_csv(out_csv)
    print(f"[ATTRIB] Wrote raw CSV → {out_csv}")

    # ---- write markdown ----
    out_md = ROOT / args.out
    out_md.parent.mkdir(parents=True, exist_ok=True)

    parts: List[str] = []
    parts.append("# Per-Edge Per-Year PnL Attribution — Phase 2.10c")
    parts.append("")
    parts.append(f"Generated: {pd.Timestamp.now().isoformat(timespec='seconds')}")
    parts.append("")
    parts.append("**Source data** (no new backtests):")
    parts.append(f"- In-sample anchor `{ANCHOR_UUID}` "
                 f"(2021-01-05 → 2024-12-31, Sharpe 1.063)")
    parts.append(f"- 2025 OOS `{OOS_UUID}` "
                 f"(2025-01-03 → 2025-12-31, Sharpe -0.049)")
    parts.append("")
    parts.append(
        "**Method:** PnL is materialized only on exit/stop/take_profit "
        "rows. Each closed trade is attributed to the year of its exit "
        "timestamp. Per-edge per-year columns sum those exits. Annualized "
        "contribution is expressed as % of the $100k starting capital. "
        "The Sharpe-like metric is per-day attributed PnL / starting "
        "capital, with vol normalized by the count of trading days in "
        "that year (not just days the edge fired)."
    )
    parts.append("")
    parts.append("**Edge universe:** 16 unique edges fired across the two "
                 "runs (excluding the pseudo-edge `Unknown`). The director "
                 "task framed this as ~18; the missing ones (e.g. "
                 "`rsi_bounce_v1`, `bollinger_reversion_v1`, "
                 "`earnings_vol_v1`, `insider_cluster_v1`, "
                 "`macro_real_rate_v1`, `macro_unemployment_momentum_v1`) "
                 "are registered active/paused but produced zero fills "
                 "in either run, which itself is a finding (see §6).")
    parts.append("")

    # ----- §1 PnL table -----
    parts.append("## 1. Per-edge per-year PnL contribution (% of $100k)")
    parts.append("")
    parts.append(_md_table_pct(pnl_pct, ndp=2))
    parts.append("")
    parts.append("Sum row (column means × 5 / 5):")
    yearly_sum = pnl_pct.sum(axis=0)
    parts.append("| year | aggregate edge contribution |")
    parts.append("| --- | ---: |")
    for y in year_cols:
        parts.append(f"| {y} | {yearly_sum[y]:+.2f}% |")
    parts.append("")
    parts.append("(Aggregate ≠ portfolio return — risk sizing, leverage, "
                 "and overlapping-position effects mean the portfolio's "
                 "actual annual return differs from the simple sum of "
                 "edge contributions.)")
    parts.append("")

    # ----- §2 Sharpe-like -----
    parts.append("## 2. Per-edge per-year Sharpe-like metric")
    parts.append("")
    parts.append("Annualized mean / annualized vol of each edge's daily "
                 "attributed PnL. Distinguishes consistent low-magnitude "
                 "contributors from lottery-ticket high-vol edges. "
                 "`—` = edge had < 2 fills that year.")
    parts.append("")
    parts.append(_md_table_sharpe(sharpe))
    parts.append("")

    # ----- §3 fill counts -----
    parts.append("## 3. Per-edge per-year entry-fill count")
    parts.append("")
    parts.append("Companion to §1 — separates 'low PnL because rarely "
                 "fires' from 'fires often, loses on average'.")
    parts.append("")
    parts.append(_md_table_int(fills))
    parts.append("")

    # ----- §4 classification -----
    parts.append("## 4. Edge classification (data-driven, NOT from `tier`)")
    parts.append("")
    parts.append("Buckets:")
    parts.append("- **stable** = ≥ 4 of 5 years with > +0.5% AND mean across all years > +0.5%")
    parts.append("- **regime-conditional** = ≥ 1 clearly positive year (> +0.5%) AND ≥ 1 clearly negative year (< -0.5%)")
    parts.append("- **noise / decay** = mean ≤ 0 across active years OR ≥ 3 negative years")
    parts.append("- **weak-positive** = barely-positive but doesn't clear the stable bar")
    parts.append("- **sparse** = fired in fewer than 2 years")
    parts.append("")
    parts.append("| edge | classification | active yrs | mean (all yrs) | mean (active yrs) | min yr | max yr | lifecycle status | tier |")
    parts.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |")
    for edge in cls.index:
        c = cls.loc[edge]
        st = status_map.get(edge, {})
        parts.append(
            f"| `{edge}` | {c['classification']} | "
            f"{int(c['n_years_active'])} | "
            f"{c['mean_pct_all_years']:+.2f}% | "
            f"{c['mean_pct_active_years']:+.2f}% | "
            f"{c['min_year_pct']:+.2f}% | "
            f"{c['max_year_pct']:+.2f}% | "
            f"{st.get('status','?')} | "
            f"{st.get('tier','?')} |"
        )
    parts.append("")

    # bucket counts
    bucket_counts = cls["classification"].value_counts().to_dict()
    parts.append("**Bucket counts:**")
    for b in ["stable", "regime-conditional", "weak-positive", "noise", "sparse"]:
        parts.append(f"- {b}: {bucket_counts.get(b, 0)}")
    parts.append("")

    # ----- §5 paused-but-actually-consistent -----
    paused_edges = [e for e in cls.index
                    if status_map.get(e, {}).get("status") == "paused"]
    paused_consistent = []
    for e in paused_edges:
        c = cls.loc[e]
        if (c["classification"] in ("stable", "weak-positive")
                or c["mean_pct_all_years"] > 0.5):
            paused_consistent.append(e)

    parts.append("## 5. Paused-but-actually-consistent (was the pause wrong?)")
    parts.append("")
    if not paused_consistent:
        parts.append("No paused edge meets the 'actually consistent' bar "
                     "(mean across years > +0.5% OR classification "
                     "stable/weak-positive). The lifecycle pause "
                     "decisions on `atr_breakout_v1`, `momentum_edge_v1`, "
                     "and `low_vol_factor_v1` are supported by this data.")
    else:
        parts.append("Edges currently paused but whose per-year contribution "
                     "looks decent in retrospect:")
        for e in paused_consistent:
            c = cls.loc[e]
            parts.append(
                f"- `{e}`: classification={c['classification']}, "
                f"mean={c['mean_pct_all_years']:+.2f}%, "
                f"min year={c['min_year_pct']:+.2f}%"
            )
    parts.append("")
    parts.append("**Per-paused-edge breakdown:**")
    for e in paused_edges:
        if e not in cls.index:
            continue
        c = cls.loc[e]
        parts.append(f"- `{e}` ({status_map.get(e,{}).get('tier','?')}): "
                     f"{c['classification']}, mean {c['mean_pct_all_years']:+.2f}%, "
                     f"min year {c['min_year_pct']:+.2f}%, "
                     f"max year {c['max_year_pct']:+.2f}%")
    parts.append("")

    # ----- §6 commentary scaffold (filled in below) -----
    parts.append("## 6. Commentary")
    parts.append("")
    parts.append("(See markdown commentary appended below the auto-generated "
                 "tables — written after the numbers were known.)")
    parts.append("")

    # ----- §7 raw artifacts -----
    parts.append("## 7. Raw artifacts")
    parts.append("")
    parts.append(f"- CSV with all metrics: `{args.csv_out}`")
    parts.append(f"- Source trade logs: `data/trade_logs/{ANCHOR_UUID}/trades.csv`, "
                 f"`data/trade_logs/{OOS_UUID}/trades.csv`")
    parts.append(f"- Driver: `scripts/per_edge_per_year_attribution.py`")
    parts.append("")

    out_md.write_text("\n".join(parts))
    print(f"[ATTRIB] Wrote markdown → {out_md}")

    # also dump bucket counts to stdout for the director
    print()
    print("=== BUCKET COUNTS ===")
    for b in ["stable", "regime-conditional", "weak-positive", "noise", "sparse"]:
        print(f"{b}: {bucket_counts.get(b, 0)}")
    print()
    print("=== PAUSED-BUT-CONSISTENT ===")
    if paused_consistent:
        for e in paused_consistent:
            print(f"  {e}")
    else:
        print("  (none)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
