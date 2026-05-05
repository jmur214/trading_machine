"""
scripts/factor_decomposition_baseline.py
=========================================
Phase 0.3 of the v2 forward plan: factor-decomposition baseline diagnostic.

Regresses every active edge's daily return stream on Fama-French 5
factors + momentum (Ken French data library). Reports per-edge:

  * raw Sharpe (Sharpe of the edge's return stream)
  * alpha-Sharpe (Sharpe of the regression intercept)
  * alpha annualized (intercept × 252)
  * alpha t-stat (significance)
  * R² (factor explanation share)

What we're measuring:
  Most retail "alpha" is factor beta in disguise. An edge that loads
  +1.5 on momentum and +0.5 on small-cap during a momentum/small-cap
  regime LOOKS like alpha but is rentable for 15bps via MTUM/IWM.
  The intercept (alpha) is the part NOT explained by factors. If
  intercept t-stat < 2 or alpha annualized < 2%, the edge is buying
  factor beta with extra steps.

Read-only diagnostic. Does NOT modify any code. Output goes to
``docs/Measurements/2026-04/factor_decomposition_baseline.md``.

Usage:
  PYTHONPATH=. python scripts/factor_decomposition_baseline.py
  PYTHONPATH=. python scripts/factor_decomposition_baseline.py --run-id <uuid>

First run downloads Ken French FF5 daily + Momentum CSVs (~1 MB each)
from Dartmouth's public FTP and caches them at
``data/research/ff5_daily.csv`` and ``data/research/mom_daily.csv``.
Subsequent runs use the cache.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from core.factor_decomposition import (
    DEFAULT_FACTOR_COLS,
    FactorDecomp,
    load_factor_data,
    regress_returns_on_factors,
)

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Per-edge return-stream construction
# ---------------------------------------------------------------------------

def find_latest_trade_log(run_id: Optional[str] = None) -> Path:
    if run_id:
        path = ROOT / "data" / "trade_logs" / run_id / "trades.csv"
        if not path.exists():
            raise FileNotFoundError(path)
        return path
    candidates = list((ROOT / "data" / "trade_logs").glob("*/trades.csv"))
    if not candidates:
        raise FileNotFoundError("No trade logs found")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def edge_daily_returns(trades: pd.DataFrame, initial_capital: float = 100_000.0) -> Dict[str, pd.Series]:
    """Group trades by edge_id and compute a daily return stream per edge.

    Approach: for each edge, sum its realized PnL by date and divide by
    initial_capital to get a daily return stream proxy. This is a
    simplification — a true per-edge equity curve would track positions
    + mark-to-market separately for each edge — but for factor
    decomposition the daily realized PnL stream is sufficient.
    """
    if "pnl" not in trades.columns:
        raise ValueError("trades.csv has no 'pnl' column — cannot compute returns")
    if "edge" not in trades.columns:
        raise ValueError("trades.csv has no 'edge' column")

    trades = trades.copy()
    trades["date"] = pd.to_datetime(trades["timestamp"]).dt.normalize()
    trades["pnl"] = pd.to_numeric(trades["pnl"], errors="coerce").fillna(0.0)

    streams: Dict[str, pd.Series] = {}
    for edge_name, group in trades.groupby("edge"):
        if not isinstance(edge_name, str) or not edge_name or edge_name == "Unknown":
            continue
        daily_pnl = group.groupby("date")["pnl"].sum()
        if len(daily_pnl) < 30:
            continue  # not enough observations for a useful regression
        daily_ret = daily_pnl / initial_capital
        streams[edge_name] = daily_ret
    return streams


# ---------------------------------------------------------------------------
# OLS regression — see core/factor_decomposition.py for the actual logic
# ---------------------------------------------------------------------------

# Thin wrapper preserving the script's original local function name in case
# anything else imports it. Delegates to the shared module.
def regress_edge_on_factors(
    edge_returns: pd.Series,
    factors: pd.DataFrame,
    factor_cols: List[str],
) -> Optional[FactorDecomp]:
    """OLS: edge_excess_return ~ alpha + sum(beta_i * factor_i).

    Thin wrapper around `core.factor_decomposition.regress_returns_on_factors`
    preserving the original argument shape used by this script.
    """
    edge_name = str(edge_returns.name) if edge_returns.name else "?"
    return regress_returns_on_factors(
        returns=edge_returns,
        factors=factors,
        factor_cols=factor_cols,
        edge_name=edge_name,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_report(
    decomps: List[FactorDecomp],
    factor_cols: List[str],
    trades_path: Path,
    out_path: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    lines.append("# Factor Decomposition Baseline")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"Trade log: `{trades_path.relative_to(ROOT)}`")
    lines.append(f"Factor model: FF5 (Mkt-RF, SMB, HML, RMW, CMA) + Momentum (Mom)")
    lines.append(f"Edges analyzed: **{len(decomps)}**")
    lines.append("")
    lines.append("## What this measures")
    lines.append("")
    lines.append("For each edge, regress its daily return stream on Fama-French 5")
    lines.append("factors + momentum. The intercept (alpha) is the part not")
    lines.append("explained by factor exposures. If intercept t-stat < 2 OR alpha")
    lines.append("annualized < 2%, the edge is reproducible by holding cheap factor")
    lines.append("ETFs (MTUM, IWM, VLUE, QUAL, USMV) and isn't real alpha.")
    lines.append("")
    lines.append("**Phase 1 implication:** edges with significant intercept become")
    lines.append("Tier-A standalone alphas; edges without become Tier-B features")
    lines.append("(useful inputs to the meta-learner but not direct trade signals).")
    lines.append("")

    # --- Sorted summary table
    lines.append("## Summary table (sorted by alpha t-stat, descending)")
    lines.append("")
    lines.append("| Edge | N obs | Raw Sharpe | Alpha (annualized) | Alpha t-stat | R² | Verdict |")
    lines.append("|------|-------|------------|--------------------|--------------|-----|---------|")
    decomps_sorted = sorted(decomps, key=lambda d: d.alpha_tstat, reverse=True)
    for d in decomps_sorted:
        verdict = "🟢 alpha" if (d.alpha_tstat > 2 and d.alpha_annualized > 0.02) \
            else ("🟡 marginal" if d.alpha_tstat > 1 else "🔴 factor beta")
        lines.append(
            f"| `{d.edge}` | {d.n_obs} | {d.raw_sharpe:.2f} | "
            f"{100 * d.alpha_annualized:+.1f}% | {d.alpha_tstat:+.2f} | "
            f"{d.r_squared:.2f} | {verdict} |"
        )
    lines.append("")

    # --- Per-edge factor loadings
    lines.append("## Per-edge factor loadings")
    lines.append("")
    lines.append(f"| Edge | {' | '.join(factor_cols)} |")
    lines.append("|------|" + "|".join(["----"] * len(factor_cols)) + "|")
    for d in decomps_sorted:
        loadings = " | ".join(f"{d.betas.get(f, 0.0):+.2f}" for f in factor_cols)
        lines.append(f"| `{d.edge}` | {loadings} |")
    lines.append("")

    # --- Verdict counts
    n_alpha = sum(1 for d in decomps if d.alpha_tstat > 2 and d.alpha_annualized > 0.02)
    n_marginal = sum(1 for d in decomps if 1 < d.alpha_tstat <= 2)
    n_beta = len(decomps) - n_alpha - n_marginal

    lines.append("## Interpretation")
    lines.append("")
    lines.append(f"- **{n_alpha} edges produce real alpha** (t-stat > 2 AND alpha > 2% annualized).")
    lines.append(f"- **{n_marginal} edges are marginal** (1 < t-stat ≤ 2). Possibly real, possibly noise.")
    lines.append(f"- **{n_beta} edges are factor beta in disguise** (t-stat ≤ 1). These can be")
    lines.append(f"  reproduced by holding factor ETFs at lower cost.")
    lines.append("")
    if n_alpha == 0:
        lines.append("**No edge passes the alpha bar.** This validates v2's framing:")
        lines.append("the system's apparent Sharpe is mostly factor exposure. The")
        lines.append("Phase 1 meta-learner is not the right next move until at least")
        lines.append("one tier-A standalone alpha exists; until then, the combiner")
        lines.append("would just be combining factor beta. Direction: build new")
        lines.append("uncorrelated edges (per Phase 2 plan) rather than scale the")
        lines.append("combiner over factor-replicating signals.")
    elif n_alpha >= 3:
        lines.append("**Multiple genuine alphas detected.** Phase 1 meta-learner can")
        lines.append("now operate over a real signal mix. Tier-A vs Tier-B")
        lines.append("classification should follow the verdict column above.")
    else:
        lines.append(f"**{n_alpha} genuine alpha detected.** The Phase 1 meta-learner")
        lines.append("has at least one real signal to work with, but the feature pool")
        lines.append("is thin. Continue Phase 2 edge discovery in parallel with the")
        lines.append("combiner build.")
    lines.append("")
    lines.append("## Caveats")
    lines.append("")
    lines.append("- Per-edge return stream is approximated by daily realized PnL /")
    lines.append("  initial capital. Exits attributed via the post-fix `edge` field")
    lines.append("  on each trade (not the legacy 'Unknown' bucket).")
    lines.append("- Edges with fewer than 30 daily observations are excluded — the")
    lines.append("  regression has too few degrees of freedom to be meaningful.")
    lines.append("- This decomposition uses raw daily returns, not vol-adjusted or")
    lines.append("  capital-efficiency-adjusted. An edge with low standalone alpha")
    lines.append("  may still earn its spot in the portfolio for diversification or")
    lines.append("  drawdown-control reasons that aren't captured here.")

    out_path.write_text("\n".join(lines))
    print(f"[FACTOR] Report written to: {out_path.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Factor decomposition baseline diagnostic")
    parser.add_argument("--run-id", default=None,
                        help="Specific trade-log UUID (default: most recent)")
    parser.add_argument("--initial-capital", type=float, default=100_000.0,
                        help="Initial capital (used to scale per-edge PnL into returns)")
    parser.add_argument("--output", default=None,
                        help="Output markdown path (default: docs/Measurements/2026-04/factor_decomposition_baseline.md)")
    args = parser.parse_args()

    # 1) Load factor data (downloads on first run)
    factors = load_factor_data()
    factor_cols = ["MktRF", "SMB", "HML", "RMW", "CMA", "Mom"]
    available = [c for c in factor_cols if c in factors.columns]
    if not available:
        raise RuntimeError(f"No factor columns found. Got: {list(factors.columns)}")
    print(f"[FACTOR] Loaded factor data: {factors.index.min().date()} → {factors.index.max().date()}, "
          f"{len(factors)} rows, factors={available}")

    # 2) Load trades + group into per-edge return streams
    trades_path = find_latest_trade_log(args.run_id)
    print(f"[FACTOR] Loading trade log: {trades_path.relative_to(ROOT)}")
    trades = pd.read_csv(trades_path)
    print(f"[FACTOR] {len(trades)} fills loaded")
    streams = edge_daily_returns(trades, initial_capital=args.initial_capital)
    print(f"[FACTOR] {len(streams)} edges have ≥30 daily observations")

    # 3) Regress each
    decomps: List[FactorDecomp] = []
    for edge_name, ret_series in streams.items():
        ret_series.name = edge_name
        d = regress_edge_on_factors(ret_series, factors, available)
        if d is None:
            continue
        decomps.append(d)
    print(f"[FACTOR] {len(decomps)} regressions completed")

    # 4) Write report
    out_path = Path(args.output) if args.output else (
        ROOT / "docs" / "Audit" / "factor_decomposition_baseline.md"
    )
    write_report(decomps, available, trades_path, out_path)

    # 5) Console summary
    print()
    print("--- per-edge alpha t-stats ---")
    for d in sorted(decomps, key=lambda x: x.alpha_tstat, reverse=True):
        print(f"  {d.edge:30s}  raw_sharpe={d.raw_sharpe:+.2f}  "
              f"alpha_ann={100*d.alpha_annualized:+5.1f}%  t={d.alpha_tstat:+5.2f}  "
              f"R²={d.r_squared:.2f}  n={d.n_obs}")


if __name__ == "__main__":
    main()
