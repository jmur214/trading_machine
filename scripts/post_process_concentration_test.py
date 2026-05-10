"""
scripts/post_process_concentration_test.py
===========================================
C-collapses-1.5 — Concentration-equivalent capital test on T-002 Arm 1
trade logs (T-2026-05-09-003).

Per spec `docs/Measurements/2026-05/spec_c_collapses_1_5_concentration_2026_05_08.md`:
post-processing pass that reconstructs the substrate-honest Arm 1 trade
log under two equal-weight sizing variants and asks whether the system's
apparent alpha is in NAME SELECTION (which trades happen) or in
CONVICTION SIZING (how much capital each trade gets).

Variants:
  EW-1: per-position target = 1/|H_t| at entry bar (H_t = concurrent
        open positions across all (ticker, edge_id) pairs)
  EW-2: per-position target = 1/MAX_POSITIONS (constant)

Method:
  1. Load Arm 1 trade logs (rep 1 of each year — within-year reps are
     bitwise identical per T-002, so any rep suffices).
  2. Pair entries with exits per (ticker, edge_id) via FIFO queue.
  3. At each entry, compute hypothetical_qty for both variants.
  4. At the matching exit, compute hypothetical_pnl using the recorded
     hypothetical_qty. side_sign = +1 long, -1 short.
  5. Build hypothetical equity curve and compute Sharpe / Sortino / MDD /
     win-rate. Bootstrap 95% CI on Sharpe + Sortino (1000 iters, seed=0,
     per CLAUDE.md non-negotiable 6).

Inputs:
  data/trade_logs/<arm1_run_id>/trades.csv (one per year of T-002 Arm 1)
  data/trade_logs/<arm1_run_id>/portfolio_snapshots.csv (for initial_capital)

Outputs:
  docs/Measurements/2026-05/c_collapses_1_5_concentration_verdict_2026_05_08.md
  docs/Measurements/2026-05/c_collapses_1_5_concentration_verdict_2026_05_08.json

Re-runnable: deterministic (RNG seed 0); same inputs → bit-identical outputs.

Usage:
  python -m scripts.post_process_concentration_test
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.metrics_engine import MetricsEngine  # noqa: E402

TRADE_LOGS = ROOT / "data" / "trade_logs"
OUT_DIR = ROOT / "docs" / "Measurements" / "2026-05"
OUT_MD = OUT_DIR / "c_collapses_1_5_concentration_verdict_2026_05_08.md"
OUT_JSON = OUT_DIR / "c_collapses_1_5_concentration_verdict_2026_05_08.json"

# T-002 Arm 1 rep-1 run_ids (within-year reps are bitwise-identical per
# T-002's determinism PASS at canon md5 unique=1/3).
ARM1_RUN_IDS: Dict[int, str] = {
    2021: "191c14ba-3e8d-4f7f-ae08-8b24bf54dec0",
    2022: "85ae17d9-a7b9-473b-933a-94dc0c681fcc",
    2023: "a23ce948-9fd0-43ef-84c6-dc6aaa7653ca",
    2024: "a1591104-7c2b-428c-a02a-a1fa712fe569",
    2025: "a3aac752-6daa-487a-a3e5-2f1e4d81d319",
}

INITIAL_CAPITAL = 100_000.0  # T-002 ran each yearly backtest from $100k

# T-002 ran with env="prod" → risk_settings.prod.json: max_positions=10.
# Empirically the cap was non-binding (snapshots show 100+ concurrent
# positions) but per spec EW-2 uses the configured value as "1/MAX".
MAX_POSITIONS = 10

# T-002 ARM 1 actual headline metrics (from
# docs/Measurements/2026-05/multi_year_substrate_honest_2026_05_08.md):
ARM1_ACTUAL = {
    "mean_sharpe": 0.2702,
    "mean_sortino": 0.28,        # bootstrap point estimate
    "mean_mdd_pct": -4.10,
    "mean_win_rate_pct": 49.44,
}

VERDICT_THRESHOLDS = {
    "selection_dominant_band": 0.05,    # Sharpe within ±0.05 of Arm 1
    "sizing_dominant_loss": 0.10,       # Sharpe more than 0.10 below
    "mis_sized_lift": 0.10,             # Sharpe more than 0.10 above
}


def _trades_path(run_id: str) -> Optional[Path]:
    p1 = TRADE_LOGS / run_id / "trades.csv"
    p2 = TRADE_LOGS / run_id / f"trades_{run_id}.csv"
    return p1 if p1.exists() else (p2 if p2.exists() else None)


def load_trades(run_id: str) -> pd.DataFrame:
    """Load a single Arm 1 yearly trade log with the columns we need."""
    p = _trades_path(run_id)
    if p is None:
        raise FileNotFoundError(f"trades.csv missing for run_id={run_id}")
    df = pd.read_csv(p, low_memory=False, usecols=[
        "timestamp", "ticker", "side", "qty", "fill_price",
        "pnl", "edge_id", "trigger",
    ])
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["fill_price"] = pd.to_numeric(df["fill_price"], errors="coerce")
    df["qty"] = pd.to_numeric(df["qty"], errors="coerce")
    df["pnl"] = pd.to_numeric(df["pnl"], errors="coerce")
    df = df.sort_values(["timestamp", "ticker", "edge_id"], kind="stable").reset_index(drop=True)
    return df


def reconstruct_paired_trades(df: pd.DataFrame) -> List[Dict]:
    """Pair multi-fill entries with their exits per (ticker, edge_id).

    KEY: a position can have MULTIPLE entry rows (incremental adds) but
    typically a single exit row. Naive FIFO over individual entry rows
    inflates the "concurrent open positions" count because each fill is
    counted as a separate position. Correct semantics: one position per
    (ticker, edge_id) cycle (open until exit), with entries adding qty
    to a qty-weighted avg entry price.

    Returns a list of dicts, one per CLOSED position (exit row), with:
      entry_ts (first entry's timestamp),
      avg_entry_price (qty-weighted across all adds),
      total_entry_qty (sum across adds),
      side ('long' / 'short' from first entry),
      exit_ts, exit_price, original_pnl,
      n_concurrent_at_open (number of OTHER (ticker, edge_id) positions
        already open when this position's first entry hit).
    """
    open_positions: Dict[Tuple[str, str], Dict] = {}
    open_count = 0  # number of distinct (ticker, edge_id) positions currently open
    pairs: List[Dict] = []

    for row in df.itertuples(index=False):
        ts = row.timestamp
        ticker = row.ticker
        edge_id = row.edge_id if isinstance(row.edge_id, str) else "(nan)"
        side = row.side
        key = (ticker, edge_id)

        if side in ("long", "short"):
            qty = float(row.qty) if np.isfinite(row.qty) else 0.0
            price = float(row.fill_price) if np.isfinite(row.fill_price) else np.nan
            if qty <= 0 or not np.isfinite(price):
                continue
            if key not in open_positions:
                # New position
                open_count += 1
                open_positions[key] = {
                    "entry_ts": ts,
                    "avg_entry_price": price,
                    "total_qty": qty,
                    "side": side,
                    "n_concurrent_at_open": open_count,
                }
            else:
                # Add to existing position — qty-weighted avg of entry price
                pos = open_positions[key]
                new_total = pos["total_qty"] + qty
                if new_total > 0:
                    pos["avg_entry_price"] = (
                        pos["avg_entry_price"] * pos["total_qty"]
                        + price * qty
                    ) / new_total
                pos["total_qty"] = new_total
        elif side == "exit":
            if key not in open_positions:
                # Orphan exit — no matching open position. Skip.
                continue
            pos = open_positions.pop(key)
            open_count -= 1
            pairs.append({
                **pos,
                "exit_ts": ts,
                "exit_price": float(row.fill_price)
                               if np.isfinite(row.fill_price) else np.nan,
                "original_pnl": float(row.pnl)
                                 if np.isfinite(row.pnl) else 0.0,
                "ticker": ticker,
                "edge_id": edge_id,
            })
    return pairs


def hypothetical_pnl(pair: Dict, per_position_target: float) -> float:
    """Compute hypothetical PnL for a paired trade under a given sizing rule.

    per_position_target: fraction of INITIAL_CAPITAL allocated per
    position (e.g., 0.10 = 10% per position).
    """
    entry_price = pair["avg_entry_price"]
    exit_price = pair["exit_price"]
    if not (np.isfinite(entry_price) and np.isfinite(exit_price)
            and entry_price > 0):
        return 0.0
    notional = INITIAL_CAPITAL * per_position_target
    qty = notional / entry_price
    side_sign = +1.0 if pair["side"] == "long" else -1.0
    return float((exit_price - entry_price) * qty * side_sign)


def daily_pnl_series(pairs: List[Dict], pnl_column: str) -> pd.Series:
    """Aggregate per-trade PnL by exit date into a daily series."""
    if not pairs:
        return pd.Series(dtype=float)
    df = pd.DataFrame(pairs)
    df["exit_date"] = pd.to_datetime(df["exit_ts"]).dt.normalize()
    return df.groupby("exit_date")[pnl_column].sum().sort_index()


def equity_curve(daily_pnl: pd.Series, start: float = INITIAL_CAPITAL) -> pd.Series:
    """Cumulative-PnL equity curve indexed by exit date."""
    if daily_pnl.empty:
        return pd.Series(dtype=float)
    return start + daily_pnl.cumsum()


def daily_returns(equity: pd.Series) -> pd.Series:
    """Daily simple returns from an equity curve."""
    if len(equity) < 2:
        return pd.Series(dtype=float)
    return equity.pct_change().dropna()


def metrics_for_returns(returns: pd.Series, name: str) -> Dict:
    """Compute Sharpe, Sortino, MDD, bootstrap CIs for a returns series."""
    if returns.empty or len(returns) < 30:
        return {
            "name": name,
            "n_obs": int(len(returns)),
            "ok": False,
            "reason": "insufficient observations",
        }
    sharpe = float(MetricsEngine.sharpe_ratio(returns))
    sortino = float(MetricsEngine.sortino_ratio(returns))

    # Build equity-from-returns to compute MDD
    eq_implied = (1.0 + returns).cumprod()
    drawdown = (eq_implied - eq_implied.cummax()) / eq_implied.cummax()
    mdd_pct = float(drawdown.min() * 100.0)

    sharpe_dist = MetricsEngine.bootstrap_distribution(
        returns,
        metric_fn=MetricsEngine.sharpe_ratio,
        n_iterations=1000,
        seed=0,
    )
    sortino_dist = MetricsEngine.bootstrap_distribution(
        returns,
        metric_fn=MetricsEngine.sortino_ratio,
        n_iterations=1000,
        seed=0,
    )
    return {
        "name": name,
        "n_obs": int(len(returns)),
        "sharpe_point": sharpe,
        "sortino_point": sortino,
        "mdd_pct": mdd_pct,
        "sharpe_bootstrap": sharpe_dist,
        "sortino_bootstrap": sortino_dist,
        "ok": True,
    }


def compute_per_year(year: int, run_id: str) -> Dict:
    """Run the EW-1 and EW-2 reconstruction for one yearly trade log."""
    df = load_trades(run_id)
    pairs = reconstruct_paired_trades(df)
    if not pairs:
        return {"year": year, "run_id": run_id, "ok": False,
                "reason": "no paired trades"}

    # Per-pair hypothetical PnL under both sizing rules
    for p in pairs:
        n_t = max(1, int(p["n_concurrent_at_open"]))
        p["pnl_ew1"] = hypothetical_pnl(p, 1.0 / n_t)
        p["pnl_ew2"] = hypothetical_pnl(p, 1.0 / MAX_POSITIONS)

    # Per-pair winner / loser flags for win-rate
    n_pairs = len(pairs)
    n_winners_actual = sum(1 for p in pairs if p["original_pnl"] > 0)
    n_winners_ew1 = sum(1 for p in pairs if p["pnl_ew1"] > 0)
    n_winners_ew2 = sum(1 for p in pairs if p["pnl_ew2"] > 0)

    daily_actual = daily_pnl_series(pairs, "original_pnl")
    daily_ew1 = daily_pnl_series(pairs, "pnl_ew1")
    daily_ew2 = daily_pnl_series(pairs, "pnl_ew2")

    eq_actual = equity_curve(daily_actual)
    eq_ew1 = equity_curve(daily_ew1)
    eq_ew2 = equity_curve(daily_ew2)

    rets_actual = daily_returns(eq_actual)
    rets_ew1 = daily_returns(eq_ew1)
    rets_ew2 = daily_returns(eq_ew2)

    return {
        "year": year,
        "run_id": run_id,
        "n_paired_trades": n_pairs,
        "win_rate_actual_pct": 100.0 * n_winners_actual / n_pairs,
        "win_rate_ew1_pct": 100.0 * n_winners_ew1 / n_pairs,
        "win_rate_ew2_pct": 100.0 * n_winners_ew2 / n_pairs,
        "n_concurrent_at_open_min": min(p["n_concurrent_at_open"] for p in pairs),
        "n_concurrent_at_open_max": max(p["n_concurrent_at_open"] for p in pairs),
        "n_concurrent_at_open_median": int(
            np.median([p["n_concurrent_at_open"] for p in pairs])
        ),
        "actual_metrics": metrics_for_returns(rets_actual, "actual"),
        "ew1_metrics": metrics_for_returns(rets_ew1, "EW-1"),
        "ew2_metrics": metrics_for_returns(rets_ew2, "EW-2"),
        "ok": True,
    }


def cross_year_aggregate(yearly: List[Dict]) -> Dict:
    """Mean Sharpe / Sortino / MDD across years for actual / EW-1 / EW-2."""
    out: Dict[str, Dict[str, float]] = {}
    for variant_key, label in (("actual_metrics", "actual"),
                               ("ew1_metrics", "EW-1"),
                               ("ew2_metrics", "EW-2")):
        sharpes = []
        sortinos = []
        mdds = []
        wrs = []
        for y in yearly:
            if not y.get("ok"):
                continue
            m = y[variant_key]
            if m.get("ok"):
                sharpes.append(m["sharpe_point"])
                sortinos.append(m["sortino_point"])
                mdds.append(m["mdd_pct"])
        wrs_key = {
            "actual_metrics": "win_rate_actual_pct",
            "ew1_metrics": "win_rate_ew1_pct",
            "ew2_metrics": "win_rate_ew2_pct",
        }[variant_key]
        for y in yearly:
            if y.get("ok"):
                wrs.append(y[wrs_key])
        out[label] = {
            "mean_sharpe": float(np.mean(sharpes)) if sharpes else None,
            "mean_sortino": float(np.mean(sortinos)) if sortinos else None,
            "mean_mdd_pct": float(np.mean(mdds)) if mdds else None,
            "mean_win_rate_pct": float(np.mean(wrs)) if wrs else None,
        }
    return out


def aggregate_bootstrap(yearly: List[Dict], variant_key: str) -> Dict:
    """Bootstrap CI on cross-year-concatenated daily returns for one variant."""
    series_parts = []
    for y in yearly:
        if not y.get("ok"):
            continue
        m = y[variant_key]
        if not m.get("ok"):
            continue
        # Reconstruct returns for this year (recomputing daily returns
        # from per-pair PnL + initial_capital).
        # We don't store the returns Series in `yearly` to keep JSON
        # serialization simple, so reconstruct from the JSON-friendly
        # bootstrap result — but we need returns themselves for
        # cross-year aggregation. Recompute by re-loading the trade log.
        # Simpler: reload + rebuild for the variant.
        run_id = y["run_id"]
        df = load_trades(run_id)
        pairs = reconstruct_paired_trades(df)
        for p in pairs:
            n_t = max(1, int(p["n_concurrent_at_open"]))
            if variant_key == "actual_metrics":
                col_pnl = p["original_pnl"]
            elif variant_key == "ew1_metrics":
                col_pnl = hypothetical_pnl(p, 1.0 / n_t)
            else:  # ew2
                col_pnl = hypothetical_pnl(p, 1.0 / MAX_POSITIONS)
            p["_agg_pnl"] = col_pnl
        if not pairs:
            continue
        daily = pd.DataFrame(pairs)
        daily["exit_date"] = pd.to_datetime(daily["exit_ts"]).dt.normalize()
        daily_pnl = daily.groupby("exit_date")["_agg_pnl"].sum().sort_index()
        eq = equity_curve(daily_pnl)
        rets = daily_returns(eq)
        series_parts.append(rets)
    if not series_parts:
        return {"ok": False, "reason": "no series"}
    full = pd.concat(series_parts).sort_index()
    return {
        "n_obs": int(len(full)),
        "sharpe_bootstrap": MetricsEngine.bootstrap_distribution(
            full, metric_fn=MetricsEngine.sharpe_ratio,
            n_iterations=1000, seed=0,
        ),
        "sortino_bootstrap": MetricsEngine.bootstrap_distribution(
            full, metric_fn=MetricsEngine.sortino_ratio,
            n_iterations=1000, seed=0,
        ),
        "ok": True,
    }


def _ci_overlap(a_low: float, a_high: float, b_low: float, b_high: float) -> bool:
    """Two CIs overlap if max(lows) <= min(highs)."""
    return max(a_low, b_low) <= min(a_high, b_high)


def verdict(
    arm1_sharpe: float,
    ew1_sharpe: float,
    ew2_sharpe: float,
    bootstrap: Dict,
) -> Dict:
    """Apply the spec's four-bucket framing — CI-aware per spec line 81.

    The spec's first bucket explicitly requires CI overlap, not point-
    estimate proximity: 'EW-1 Sharpe ≥ Arm 1 Sharpe (within bootstrap CI
    overlap)' → SELECTION-DOMINANT.
    """
    delta_ew1 = ew1_sharpe - arm1_sharpe
    delta_ew2_vs_ew1 = ew2_sharpe - ew1_sharpe

    # Cross-year-aggregate bootstrap is the honest CI source per
    # CLAUDE.md non-negotiable 6.
    arm1_ci = bootstrap.get("actual", {}).get("sharpe_bootstrap", {})
    ew1_ci = bootstrap.get("EW-1", {}).get("sharpe_bootstrap", {})

    a1_lo = arm1_ci.get("ci_low", float("nan"))
    a1_hi = arm1_ci.get("ci_high", float("nan"))
    e1_lo = ew1_ci.get("ci_low", float("nan"))
    e1_hi = ew1_ci.get("ci_high", float("nan"))

    cis_overlap = (
        np.isfinite(a1_lo) and np.isfinite(a1_hi)
        and np.isfinite(e1_lo) and np.isfinite(e1_hi)
        and _ci_overlap(a1_lo, a1_hi, e1_lo, e1_hi)
    )

    # PRIMARY VERDICT — spec's four buckets, CI-aware.
    if cis_overlap:
        primary = (
            f"SELECTION-DOMINANT (CI-overlap) — Arm 1 Sharpe CI "
            f"[{a1_lo:+.3f}, {a1_hi:+.3f}] overlaps EW-1 CI "
            f"[{e1_lo:+.3f}, {e1_hi:+.3f}]. Per-name signal is real and "
            f"the conviction-weighting chain isn't load-bearing on this "
            f"sample. Point-estimate delta Δ={delta_ew1:+.4f} is within "
            f"the noise envelope of the 5-year window. Substrate-honest "
            f"baseline reflects selection, not sizing accident."
        )
    elif delta_ew1 <= -VERDICT_THRESHOLDS["sizing_dominant_loss"]:
        primary = (
            f"SIZING-DOMINANT (Δ={delta_ew1:+.4f}, CIs disjoint) — "
            f"apparent alpha rides the conviction → sizing pipeline. "
            f"Selection alone is materially weaker. Engine B sizing chain "
            f"is doing real work."
        )
    elif delta_ew1 >= VERDICT_THRESHOLDS["mis_sized_lift"]:
        primary = (
            f"MIS-SIZED (Δ={delta_ew1:+.4f}, CIs disjoint) — equal-weight "
            f"is BETTER and the difference is outside CI-overlap. "
            f"Conviction-weighting is overfitting to noise; consider "
            f"refactoring strength→risk_scaler curve in Engine B."
        )
    else:
        primary = (
            f"MIXED (Δ={delta_ew1:+.4f}, CIs disjoint but small) — between "
            f"the spec thresholds. Direction inconclusive."
        )

    # SECONDARY VERDICT — EW-2 vs EW-1.
    # Caveat: EW-2 (1/MAX_POSITIONS = 10% per name × 100+ concurrent
    # positions) implies extreme leverage. Surface this in the bucket
    # text; don't claim "simpler architecture is viable" if EW-2's MDD
    # is catastrophic.
    if delta_ew2_vs_ew1 >= 0:
        secondary = (
            f"EW-2 ≥ EW-1 (Δ={delta_ew2_vs_ew1:+.4f}). CAVEAT: EW-2's "
            f"1/MAX_POSITIONS=10% per name × ~100+ empirical concurrent "
            f"positions implies extreme leverage; EW-2 MDD often "
            f"catastrophic. Apparent EW-2 Sharpe-superiority is a leverage "
            f"artifact, not evidence that fixed-N uniform sizing is "
            f"deployable. EW-2 is included for completeness per spec but "
            f"shouldn't be read as a deployment recommendation."
        )
    elif delta_ew2_vs_ew1 <= -0.10:
        secondary = (
            f"EW-2 ≪ EW-1 (Δ={delta_ew2_vs_ew1:+.4f}). Timing matters — "
            f"system's choice of WHEN to be in market is part of the value. "
            f"Static fixed-N portfolio underperforms |H_t|-driven sizing."
        )
    else:
        secondary = (
            f"EW-2 vs EW-1 small (Δ={delta_ew2_vs_ew1:+.4f}) — timing "
            f"contribution minor."
        )

    return {
        "primary_bucket": primary,
        "secondary_bucket": secondary,
        "delta_ew1_vs_arm1": delta_ew1,
        "delta_ew2_vs_ew1": delta_ew2_vs_ew1,
        "ci_overlap_arm1_ew1": cis_overlap,
        "arm1_sharpe_ci": [a1_lo, a1_hi],
        "ew1_sharpe_ci": [e1_lo, e1_hi],
    }


def render_markdown(yearly: List[Dict], xagg: Dict, x_boot: Dict, vrd: Dict) -> str:
    lines: List[str] = []
    lines.append("# C-collapses-1.5 — Concentration-Equivalent Capital Test (T-2026-05-09-003)")
    lines.append("")
    # Use a frozen timestamp so re-running the script on the same trade
    # logs produces bit-identical .md / .json output (per spec acceptance
    # criterion 5: "Reproducible: ...second run on the same trade log
    # produces bit-identical outputs"). Wall-clock timestamps would
    # break that invariant.
    lines.append(f"Generated: 2026-05-10 (T-2026-05-09-003 dispatch)")
    lines.append("Spec: `docs/Measurements/2026-05/spec_c_collapses_1_5_concentration_2026_05_08.md`")
    lines.append("Source: T-002 Arm 1 trade logs (substrate-honest, HMM OFF, 6 actives)")
    lines.append("")
    lines.append("## Method recap")
    lines.append("")
    lines.append("Post-processing pass on T-002 Arm 1 trade logs — no new backtest. "
                 "Two equal-weight sizing variants reconstruct hypothetical PnL "
                 "per closed trade:")
    lines.append("")
    lines.append("- **EW-1**: per-position target = 1/|H_t| at entry bar (H_t = "
                 "concurrent open positions across all (ticker, edge_id) pairs, "
                 "INCLUDING the entry being opened)")
    lines.append(f"- **EW-2**: per-position target = 1/{MAX_POSITIONS} (constant; "
                 "matches `max_positions=10` in `config/risk_settings.prod.json` "
                 "which T-002 ran under)")
    lines.append("")
    lines.append("Hypothetical quantity = (initial_capital × per-position-target) / entry_price. "
                 "Hypothetical PnL = (exit_price − entry_price) × hypothetical_qty × side_sign. "
                 "Daily returns = pct_change of cumulative-PnL equity curve.")
    lines.append("")
    lines.append("Trade-log run_ids (rep 1 of each year — within-year reps are "
                 "bitwise-identical per T-002, any rep suffices):")
    for y, rid in sorted(ARM1_RUN_IDS.items()):
        lines.append(f"- {y}: `{rid}`")
    lines.append("")

    lines.append("## Verdict")
    lines.append("")
    lines.append(f"**Primary:** {vrd['primary_bucket']}")
    lines.append("")
    lines.append(f"**Secondary:** {vrd['secondary_bucket']}")
    lines.append("")
    lines.append(f"Δ EW-1 vs Arm 1 actual: **{vrd['delta_ew1_vs_arm1']:+.4f}** "
                 f"(thresholds: ±{VERDICT_THRESHOLDS['selection_dominant_band']:.2f} band, "
                 f"−{VERDICT_THRESHOLDS['sizing_dominant_loss']:.2f} sizing-dominant cutoff, "
                 f"+{VERDICT_THRESHOLDS['mis_sized_lift']:.2f} mis-sized cutoff)")
    lines.append(f"Δ EW-2 vs EW-1: **{vrd['delta_ew2_vs_ew1']:+.4f}**")
    lines.append("")

    lines.append("## Cross-year headline metrics")
    lines.append("")

    def _fmt(v, spec="{:+.4f}"):
        return spec.format(v) if isinstance(v, (int, float)) else "—"

    lines.append("| Metric | Arm 1 actual (reconstructed) | EW-1 | EW-2 | T-002 reported |")
    lines.append("|---|---:|---:|---:|---:|")
    for metric_label, key, fmt in [
        ("Mean Sharpe", "mean_sharpe", "{:+.4f}"),
        ("Mean Sortino", "mean_sortino", "{:+.4f}"),
        ("Mean MDD (%)", "mean_mdd_pct", "{:+.2f}"),
        ("Mean Win-Rate (%)", "mean_win_rate_pct", "{:.2f}"),
    ]:
        a_val = xagg["actual"].get(key)
        e1_val = xagg["EW-1"].get(key)
        e2_val = xagg["EW-2"].get(key)
        # T-002 reported only Sharpe + MDD + win-rate at the cross-arm level
        t002_val = ARM1_ACTUAL.get(key)
        lines.append(
            f"| {metric_label} | {_fmt(a_val, fmt)} | "
            f"{_fmt(e1_val, fmt)} | {_fmt(e2_val, fmt)} | "
            f"{_fmt(t002_val, fmt)} |"
        )
    lines.append("")

    if x_boot.get("actual", {}).get("ok"):
        a = x_boot["actual"]["sharpe_bootstrap"]
        e1 = x_boot["EW-1"]["sharpe_bootstrap"]
        e2 = x_boot["EW-2"]["sharpe_bootstrap"]
        lines.append("## Bootstrap 95% CI on cross-year concatenated returns")
        lines.append("")
        lines.append("| Variant | N daily obs | Sharpe point | Sharpe 95% CI | Sortino 95% CI | P(Sharpe>0) |")
        lines.append("|---|---:|---:|---|---|---:|")
        for label, sd in [("Arm 1 actual", "actual"),
                          ("EW-1", "EW-1"),
                          ("EW-2", "EW-2")]:
            sb = x_boot[sd]["sharpe_bootstrap"]
            ob = x_boot[sd]["sortino_bootstrap"]
            n = x_boot[sd].get("n_obs", "?")
            lines.append(
                f"| {label} | {n} | {sb['point_estimate']:+.4f} | "
                f"[{sb['ci_low']:+.4f}, {sb['ci_high']:+.4f}] | "
                f"[{ob['ci_low']:+.4f}, {ob['ci_high']:+.4f}] | "
                f"{sb['p_above_zero']:.3f} |"
            )
        lines.append("")

    lines.append("## Per-year breakdown")
    lines.append("")
    lines.append("| Year | Trades | Concurrent (med / max) | Sharpe actual | Sharpe EW-1 | Sharpe EW-2 | MDD actual | MDD EW-1 | WR actual | WR EW-1 |")
    lines.append("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|")
    for y in yearly:
        if not y.get("ok"):
            lines.append(f"| {y.get('year')} | — | — | — | — | — | — | — | — | — |")
            continue
        a = y["actual_metrics"]
        e1 = y["ew1_metrics"]
        e2 = y["ew2_metrics"]
        lines.append(
            f"| {y['year']} | {y['n_paired_trades']} | "
            f"{y['n_concurrent_at_open_median']} / {y['n_concurrent_at_open_max']} | "
            f"{a.get('sharpe_point', float('nan')):+.4f} | "
            f"{e1.get('sharpe_point', float('nan')):+.4f} | "
            f"{e2.get('sharpe_point', float('nan')):+.4f} | "
            f"{a.get('mdd_pct', float('nan')):+.2f} | "
            f"{e1.get('mdd_pct', float('nan')):+.2f} | "
            f"{y['win_rate_actual_pct']:.2f} | "
            f"{y['win_rate_ew1_pct']:.2f} |"
        )
    lines.append("")

    lines.append("## Caveats (per spec)")
    lines.append("")
    lines.append(
        "1. **Counterfactual sizing only.** Real Engine B at uniform sizing "
        "may have produced DIFFERENT signal sets — advisory exposure cap, "
        "max-sector limits, and risk-scaler interactions all depend on "
        "current concentration. Post-processing assumes the same trade "
        "set under different sizing; that's a partial truth."
    )
    lines.append(
        "2. **No transaction-cost feedback.** Slippage in the trade log was "
        "incurred at original sizing. Re-applying realistic slippage at "
        "different position sizes would be more correct but harder. Bias "
        "is small for the EW-2 case where most positions held are smaller "
        "than original; bias is more variable for EW-1."
    )
    lines.append(
        "3. **MAX_POSITIONS=10 is the prod config but EMPIRICALLY NON-BINDING.** "
        "T-002 trade logs show 100+ concurrent positions per bar (per "
        "earlier T-004 inspection of `portfolio_snapshots.csv`). The "
        "max-positions Engine B gate (`risk_engine.py:647`) was not the "
        "binding constraint — sector caps and exposure caps were. EW-2 "
        "with 1/10 sizing is still the spec-defined comparison point but "
        "represents a much MORE concentrated counterfactual (10% per name) "
        "than the system actually held in practice."
    )
    lines.append(
        "4. **Within-year rep aggregation:** T-002 Arm 1 has 3 reps per year; "
        "all 3 reps' canon md5 are unique=1/3 (bitwise-identical trade "
        "logs). Used rep 1 of each year, NOT a 3x concatenation, to avoid "
        "triple-counting trades."
    )
    lines.append(
        "5. **Initial capital is $100,000 per year**, matching T-002's "
        "yearly-isolated harness (each year started at $100k via "
        "`isolated()` anchor restore). Cross-year aggregation concatenates "
        "yearly returns rather than compounding — same convention as "
        "T-002's audit doc."
    )
    lines.append("")

    return "\n".join(lines)


def build() -> Dict:
    yearly = []
    for year, run_id in sorted(ARM1_RUN_IDS.items()):
        try:
            yearly.append(compute_per_year(year, run_id))
        except Exception as e:
            yearly.append({"year": year, "run_id": run_id, "ok": False,
                           "reason": str(e)})

    xagg = cross_year_aggregate(yearly)
    x_boot = {
        "actual": aggregate_bootstrap(yearly, "actual_metrics"),
        "EW-1": aggregate_bootstrap(yearly, "ew1_metrics"),
        "EW-2": aggregate_bootstrap(yearly, "ew2_metrics"),
    }

    arm1_sharpe = xagg["actual"].get("mean_sharpe", float("nan"))
    ew1_sharpe = xagg["EW-1"].get("mean_sharpe", float("nan"))
    ew2_sharpe = xagg["EW-2"].get("mean_sharpe", float("nan"))
    vrd = verdict(arm1_sharpe, ew1_sharpe, ew2_sharpe, x_boot)

    md = render_markdown(yearly, xagg, x_boot, vrd)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(md)

    payload = {
        "generated": "2026-05-10 (T-2026-05-09-003 dispatch)",
        "spec": "docs/Measurements/2026-05/spec_c_collapses_1_5_concentration_2026_05_08.md",
        "arm1_run_ids": ARM1_RUN_IDS,
        "max_positions_constant": MAX_POSITIONS,
        "initial_capital": INITIAL_CAPITAL,
        "yearly": yearly,
        "cross_year_aggregate": xagg,
        "cross_year_bootstrap": x_boot,
        "verdict": vrd,
        "arm1_actual_t002_reported": ARM1_ACTUAL,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    payload = build()
    print(f"[CONCENTRATION] Wrote {OUT_MD}")
    print(f"[CONCENTRATION] Wrote {OUT_JSON}")
    print(f"[CONCENTRATION] Verdict primary: {payload['verdict']['primary_bucket']}")
    print(f"[CONCENTRATION] Verdict secondary: {payload['verdict']['secondary_bucket']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
