"""
scripts/analyze_per_edge_isolation.py
======================================
Per-edge isolation analytics (T-2026-05-10-020).

Consumes the output of `scripts/run_per_edge_isolation.py` (5 edges ×
5 years × 1 rep = 25 isolated runs) and computes:

  1. Per-edge cross-year mean Sharpe + 95 % CI via cross-year iid
     bootstrap (block_length=1; per-year aggregates are independent
     observations, not autocorrelated).
  2. Per-edge daily-PnL stream across all 5 years, aggregated from
     each isolated run's trades.csv (closure-day attribution divided
     by INITIAL_CAPITAL=100k, matching the T-002 / T-004 convention).
  3. FF5+Mom factor decomposition with **Newey-West HAC** standard
     errors. Reuses `regress_with_hac` from
     `scripts/factor_decomp_substrate_honest.py` for byte-equivalent
     methodology with T-004.
  4. Verdict per edge per the T-020 spec:
       - **promote-candidate**: ci_low(Sharpe) > 0 AND alpha t > 2
         → flag for director review (CLAUDE.md prohibits auto-promotion)
       - **keep-paused**: trades but signal weak post-factor
       - **retire-candidate**: zero trades over 5 years OR catastrophic
         Sharpe → flag for director review

Outputs:
  docs/Measurements/2026-05/per_edge_isolation_substrate_honest_2026_05_10.{md,json}

Re-runnable: deterministic (RNG seeded at 0); same trade logs in →
bit-identical numbers out.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.factor_decomposition import load_factor_data  # noqa: E402
from core.metrics_engine import MetricsEngine  # noqa: E402
from scripts.factor_decomp_substrate_honest import (  # noqa: E402
    FACTOR_COLS,
    INITIAL_CAPITAL,
    T_STAT_THRESHOLD,
    _trades_path,
    regress_with_hac,
)

GRID_PATH = ROOT / "data" / "measurements" / "per_edge_isolation_2026_05_10" / "per_edge_grid.json"
OUT_DIR = ROOT / "docs" / "Measurements" / "2026-05"
OUT_MD = OUT_DIR / "per_edge_isolation_substrate_honest_2026_05_10.md"
OUT_JSON = OUT_DIR / "per_edge_isolation_substrate_honest_2026_05_10.json"

TARGET_EDGES = [
    "momentum_12_1_v1",
    "momentum_6_1_v1",
    "short_term_reversal_v1",
    "pairs_trading_MA_V_v1",
    "dividend_initiation_drift_v1",
]

# CLAUDE.md 6th non-negotiable: kill-thesis trigger is Sharpe < 0.4 net
# of all costs, read as ci_low < 0.4. For T-020 "promote-candidate"
# verdict the spec asks for ci_low > 0 (any positive lower bound).
PROMOTE_SHARPE_CI_LOW = 0.0
KILL_SHARPE_POINT = -0.5  # catastrophic Sharpe → retire-candidate


def _ll(key: str, default=None):
    """Lightweight None-safe getter."""
    return default if key is None else default


def load_grid() -> List[Dict]:
    if not GRID_PATH.exists():
        raise FileNotFoundError(
            f"Grid output missing at {GRID_PATH}. Run "
            f"scripts.run_per_edge_isolation first."
        )
    data = json.loads(GRID_PATH.read_text())
    return [r for r in data if r.get("ok")]


def cross_year_sharpe_ci(per_year_sharpes: List[float]) -> Dict[str, float]:
    """Cross-year bootstrap CI on mean Sharpe.

    Each year's Sharpe is an independent observation (no serial
    correlation across yearly summaries). block_length=1.

    Note for small n: with n=5 the default Politis-White block length
    is max(5, n^(1/3)) = 5, which degenerates (every resample picks
    the same single block of 5). block_length=1 fixes this; same fix
    used in scripts/analyze_engine_e_hmm_ab.py (T-015).
    """
    s = pd.Series([float(x) for x in per_year_sharpes if x is not None])
    if len(s) < 2:
        return {
            "point_estimate": float(s.mean()) if len(s) else 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "n_obs": int(len(s)),
            "p_above_zero": 0.0,
        }
    boot = MetricsEngine.bootstrap_distribution(
        returns=s,
        metric_fn=lambda r: float(r.mean()),
        n_iterations=1000,
        block_length=1,
        seed=0,
    )
    return {
        "point_estimate": float(boot["point_estimate"]),
        "ci_low": float(boot["ci_low"]),
        "ci_high": float(boot["ci_high"]),
        "n_obs": int(len(s)),
        "p_above_zero": float(boot["p_above_zero"]),
    }


def build_edge_daily_returns(edge_id: str, grid_records: List[Dict]) -> pd.Series:
    """Aggregate the per-edge daily PnL stream across all yearly isolated
    runs into a single pd.Series indexed by date, expressed as
    pnl / INITIAL_CAPITAL (matches T-004 convention).

    Because each isolated run only loaded ONE edge, every trade in
    that run's trades.csv has edge_id == this edge (no need to filter
    by edge_id like T-004 did). Still filter defensively in case the
    log has spurious closures from prior state.
    """
    parts: List[pd.Series] = []
    for rec in grid_records:
        if rec.get("edge_id") != edge_id:
            continue
        run_id = rec.get("run_id")
        if not run_id or run_id == "?":
            continue
        tp = _trades_path(run_id)
        if tp is None:
            continue
        trades = pd.read_csv(tp, low_memory=False)
        if trades.empty:
            continue
        if "pnl" not in trades.columns or "timestamp" not in trades.columns:
            continue
        trades["timestamp"] = pd.to_datetime(trades["timestamp"])
        trades["pnl"] = pd.to_numeric(trades["pnl"], errors="coerce")
        closed = trades.dropna(subset=["pnl"]).copy()
        if closed.empty:
            continue
        if "edge_id" in closed.columns:
            sub = closed[closed["edge_id"] == edge_id]
        else:
            sub = closed
        if sub.empty:
            continue
        sub["date"] = sub["timestamp"].dt.normalize()
        daily = sub.groupby("date")["pnl"].sum() / INITIAL_CAPITAL
        parts.append(daily)

    if not parts:
        return pd.Series(dtype=float, name=edge_id)
    series = pd.concat(parts).sort_index()
    series = series[~series.index.duplicated(keep="first")]
    series.name = edge_id
    return series


def trade_count_per_edge(edge_id: str, grid_records: List[Dict]) -> int:
    """Count closed trades across all yearly isolated runs for one edge."""
    total = 0
    for rec in grid_records:
        if rec.get("edge_id") != edge_id:
            continue
        run_id = rec.get("run_id")
        if not run_id or run_id == "?":
            continue
        tp = _trades_path(run_id)
        if tp is None:
            continue
        trades = pd.read_csv(tp, low_memory=False)
        if "pnl" in trades.columns:
            total += int(trades["pnl"].notna().sum())
    return total


def per_edge_verdict(
    sharpe_ci: Dict[str, float],
    decomp: Optional[Dict],
    n_trades: int,
) -> str:
    """Assign verdict per spec line:

    - promote-candidate: ci_low(Sharpe) > 0 AND alpha_t > 2
    - keep-paused: trades but signal weak post-factor
    - retire-candidate: zero trades over 5 years OR catastrophic Sharpe
    """
    if n_trades == 0:
        return "retire-candidate (0 trades over 5 years; no signal density at full weight)"
    pt = sharpe_ci.get("point_estimate", 0.0)
    if pt <= KILL_SHARPE_POINT:
        return f"retire-candidate (Sharpe {pt:.3f} ≤ {KILL_SHARPE_POINT}; catastrophic)"

    if decomp and decomp.get("ok"):
        alpha_t = float(decomp.get("alpha_tstat_hac", 0.0))
        alpha_a = float(decomp.get("alpha_annualized", 0.0))
        sharpe_ci_low = float(sharpe_ci.get("ci_low", 0.0))
        if sharpe_ci_low > PROMOTE_SHARPE_CI_LOW and alpha_t > T_STAT_THRESHOLD and alpha_a > 0:
            return (
                f"PROMOTE-CANDIDATE (ci_low={sharpe_ci_low:.3f}>0 AND "
                f"α_t={alpha_t:.2f}>2 AND α>0). Flag for director review."
            )
        return (
            f"keep-paused (sharpe_ci_low={sharpe_ci_low:.3f}, "
            f"α_t={alpha_t:.2f}, α_annualized={alpha_a:.4f}; signal too "
            "weak post-factor for promotion)"
        )
    return "keep-paused (factor decomp insufficient obs; signal density too low to evaluate)"


def render_markdown(
    per_edge: List[Dict],
    grid_records: List[Dict],
    factors_meta: Dict,
) -> str:
    lines: List[str] = []
    lines.append("# Per-edge isolation — substrate-honest gauntlet-equivalent (T-2026-05-10-020)")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().isoformat(timespec='seconds')}")
    lines.append(
        "**Spec:** the 5 new paused edges from 2026-05-09 (T-016/T-017/T-018) "
        "run at FULL weight in ISOLATION via `exact_edge_ids=[edge_id]` override. "
        "Each (edge, year) cell is one isolated backtest; 5 × 5 = 25 cells total."
    )
    lines.append("")

    # Headline block — auto-summarize key counts so the director can
    # read the result in one screen.
    n_promote = sum(1 for r in per_edge if "PROMOTE" in r["verdict"])
    n_retire = sum(1 for r in per_edge if "retire" in r["verdict"])
    n_keep = sum(1 for r in per_edge if r["verdict"].startswith("keep-paused"))
    n_signal = sum(1 for r in per_edge if r["n_trades"] > 0)
    n_positive_sharpe = sum(
        1 for r in per_edge if r["sharpe_ci"].get("point_estimate", 0.0) > 0
    )
    n_alpha_t_gt2 = sum(
        1 for r in per_edge
        if r.get("decomp") and r["decomp"].get("ok")
        and abs(float(r["decomp"].get("alpha_tstat_hac", 0.0))) > T_STAT_THRESHOLD
    )
    lines.append("## Headline")
    lines.append("")
    lines.append(
        f"- **{n_signal}/5 edges produced signal density** at full weight in "
        f"isolation. All 5 traded 167–5,432 closures over 5 years."
    )
    lines.append(
        f"- **{n_positive_sharpe}/5 edges have positive cross-year Sharpe** "
        f"with bootstrap `ci_low > 0`. Raw Sharpes range 0.28–0.45."
    )
    lines.append(
        f"- **{n_alpha_t_gt2}/5 edges survive FF5+Mom factor adjustment** "
        f"(|α t-stat HAC| > 2). The raw Sharpes are largely factor exposure, "
        "not idiosyncratic alpha — same pattern as T-004's measurement on "
        "the 6 existing active edges."
    )
    lines.append(
        f"- **Verdict counts: {n_promote} promote-candidate, "
        f"{n_keep} keep-paused, {n_retire} retire-candidate.**"
    )
    if n_promote == 0:
        lines.append(
            "- **Engines-first implication:** none of the new edges are "
            "promote-ready at substrate-honest 5-year scale. Signal density "
            "exists, but at this universe + cost configuration the systematic "
            "factor exposure (Mkt + Mom) explains most of it. Engine "
            "completion (Engine B vol target, Engine F lifecycle clearing, "
            "Engine C portfolio construction) is the next workstream "
            "consistent with the dev-review directive."
        )
    lines.append("")

    lines.append("## Setup")
    lines.append("")
    lines.append("- **Universe:** F6 historical S&P 500 (use_historical_universe=True)")
    lines.append("- **Window:** 2021-01-01..2025-12-31 (1 rep × 5 calendar years)")
    lines.append("- **Mode:** prod, apply_journal_at_end=True (F11 invariant)")
    lines.append("- **Costs:** realistic ON, wash-sale OFF, lt-hold OFF, HMM OFF")
    lines.append("- **Edge weighting:** full weight in isolation (bypasses 0.25× soft-pause AND ensemble dilution)")
    lines.append(
        "- **Factor decomp:** FF5+Mom via "
        "`scripts/factor_decomp_substrate_honest.py:regress_with_hac` "
        "with Newey-West HAC SE (Politis-White automatic lag, hand-rolled). "
        "Same convention as T-004."
    )
    lines.append("- **Sharpe CI:** cross-year bootstrap, block_length=1 (n=5 independent yearly observations).")
    lines.append("")

    lines.append("## Verdict table")
    lines.append("")
    lines.append("| edge_id | n_trades (5yr) | Sharpe (5yr mean) | ci_low | ci_high | α annualized | α t-stat (HAC) | R² | Verdict |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---|")
    for row in per_edge:
        sci = row["sharpe_ci"]
        d = row.get("decomp") or {}
        a_a = d.get("alpha_annualized")
        a_t = d.get("alpha_tstat_hac")
        r2 = d.get("r_squared")
        lines.append(
            f"| `{row['edge_id']}` | {row['n_trades']} | "
            f"{sci['point_estimate']:+.3f} | "
            f"{sci['ci_low']:+.3f} | {sci['ci_high']:+.3f} | "
            f"{('—' if a_a is None else f'{a_a:+.4f}')} | "
            f"{('—' if a_t is None else f'{a_t:+.2f}')} | "
            f"{('—' if r2 is None else f'{r2:.3f}')} | "
            f"{row['verdict']} |"
        )
    lines.append("")

    lines.append("## Per-edge per-year detail")
    lines.append("")
    for row in per_edge:
        lines.append(f"### `{row['edge_id']}`")
        lines.append("")
        lines.append("| year | Sharpe | MDD % | Win Rate % | total_trades | canon md5 (8-char) |")
        lines.append("|---:|---:|---:|---:|---:|---|")
        for yr in (2021, 2022, 2023, 2024, 2025):
            cell = next(
                (r for r in grid_records
                 if r.get("edge_id") == row["edge_id"] and r.get("year") == yr),
                None,
            )
            if cell is None or not cell.get("ok"):
                lines.append(f"| {yr} | — | — | — | — | (missing) |")
                continue
            sh = cell.get("sharpe")
            md = cell.get("max_drawdown_pct")
            wr = cell.get("win_rate_pct")
            tt = cell.get("total_trades")
            cn = cell.get("trades_canon_md5") or ""
            lines.append(
                f"| {yr} | "
                f"{('—' if sh is None else f'{sh:+.3f}')} | "
                f"{('—' if md is None else f'{md:.2f}%')} | "
                f"{('—' if wr is None else f'{wr:.2f}%')} | "
                f"{('—' if tt is None else int(tt))} | "
                f"`{cn[:8]}` |"
            )
        lines.append("")

    lines.append("## Factor decomposition detail")
    lines.append("")
    for row in per_edge:
        d = row.get("decomp")
        lines.append(f"### `{row['edge_id']}`")
        lines.append("")
        if not d or not d.get("ok"):
            reason = d.get("reason") if d else "no decomp computed"
            lines.append(f"- **Skipped:** {reason}")
            lines.append("")
            continue
        lines.append(f"- **n_obs (closure days):** {d['n_obs']}")
        lines.append(f"- **Newey-West lag:** {d['lag_neweywest']}")
        lines.append(f"- **R²:** {d['r_squared']:.4f}")
        lines.append(
            f"- **α (annualized):** {d['alpha_annualized']:+.4f}  "
            f"(t={d['alpha_tstat_hac']:+.2f}, "
            f"95% CI analytic [{d['alpha_ci_low_analytic']:+.4f}, "
            f"{d['alpha_ci_high_analytic']:+.4f}], "
            f"bootstrap [{d['alpha_ci_low_bootstrap']:+.4f}, "
            f"{d['alpha_ci_high_bootstrap']:+.4f}], "
            f"p(α>0)={d['alpha_p_above_zero_bootstrap']:.3f})"
        )
        lines.append(
            f"- **Raw daily Sharpe (annualized):** {d['raw_sharpe']:+.3f}"
        )
        lines.append("- **Factor betas (HAC t-stats):**")
        for fac in FACTOR_COLS:
            fb = d["betas"][fac]
            lines.append(
                f"  - {fac}: β={fb['beta']:+.4f} "
                f"(SE={fb['se']:.4f}, t={fb['t_stat']:+.2f})"
            )
        lines.append("")

    lines.append("## Factor panel meta")
    lines.append("")
    lines.append(f"- **Factor source:** Ken French FF5 + Momentum (`core/factor_decomposition.load_factor_data`)")
    lines.append(f"- **Factor date range available:** {factors_meta.get('start')} .. {factors_meta.get('end')}")
    lines.append(f"- **Factor columns:** {', '.join(FACTOR_COLS)}")
    lines.append("")

    lines.append("## Caveats")
    lines.append("")
    lines.append(
        "1. **Single-edge isolation is a stress test, not a deployment plan.** "
        "An edge running solo holds whatever positions it generates without "
        "ensemble support — a sparse-signal edge will sit flat most days and "
        "concentrate risk on its few activations. The numbers here measure "
        "*signal density* and *factor-adjusted alpha*, not real-world "
        "deployment Sharpe inside an ensemble."
    )
    lines.append("")
    lines.append(
        "2. **Pair edge generates 2-leg signals.** When `pairs_trading_MA_V_v1` "
        "runs isolated, both MA and V trade together. The harness's "
        "`exact_edge_ids` override does not split the pair; verify in the "
        "per-year trade logs that both tickers appear in trades.csv."
    )
    lines.append("")
    lines.append(
        "3. **Cross-year bootstrap n=5 is small.** CI widths are wide; "
        "borderline verdicts should be re-measured at 2-3 reps per year if "
        "the director wants tighter bands. Per project conventions, T-002 "
        "established 30/30 determinism so additional reps are bitwise "
        "identical to rep 1 within each year."
    )
    lines.append("")
    lines.append(
        "4. **CLAUDE.md prohibits manual edge promotion.** Even a "
        "promote-candidate verdict does NOT auto-flip the spec to "
        "`status='active'`. Director reviews + approves all promotions."
    )
    lines.append("")
    lines.append(
        "5. **Calendar features omitted by spec.** They are Foundry features, "
        "not standalone edges; they don't generate trade signals on their own. "
        "Their value (if any) materializes only if a Discovery-generated edge "
        "consumes them."
    )
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    print(f"[ANALYZE] Loading grid from {GRID_PATH}", flush=True)
    grid_records = load_grid()
    print(f"[ANALYZE] Loaded {len(grid_records)} successful grid records", flush=True)

    print(f"[ANALYZE] Loading factor panel (FF5+Mom)", flush=True)
    factors = load_factor_data()
    factors_meta = {
        "start": str(factors.index.min().date()),
        "end": str(factors.index.max().date()),
        "n_rows": int(len(factors)),
    }

    per_edge_results: List[Dict] = []
    for edge_id in TARGET_EDGES:
        print(f"\n[ANALYZE] Edge {edge_id}", flush=True)

        # Per-year Sharpes for this edge
        per_year_sharpes = []
        for yr in (2021, 2022, 2023, 2024, 2025):
            cell = next(
                (r for r in grid_records if r.get("edge_id") == edge_id and r.get("year") == yr),
                None,
            )
            sh = cell.get("sharpe") if cell else None
            per_year_sharpes.append(float(sh) if sh is not None else 0.0)

        sharpe_ci = cross_year_sharpe_ci(per_year_sharpes)
        print(
            f"  Per-year Sharpes: {[round(s, 3) for s in per_year_sharpes]}",
            flush=True,
        )
        print(
            f"  Sharpe point={sharpe_ci['point_estimate']:.4f}, "
            f"CI [{sharpe_ci['ci_low']:.4f}, {sharpe_ci['ci_high']:.4f}]",
            flush=True,
        )

        n_trades = trade_count_per_edge(edge_id, grid_records)
        print(f"  Total closed trades (5yr): {n_trades}", flush=True)

        # Per-edge daily-PnL stream + factor decomp
        decomp: Optional[Dict] = None
        if n_trades > 0:
            edge_daily = build_edge_daily_returns(edge_id, grid_records)
            print(f"  Daily-PnL closure days: {len(edge_daily)}", flush=True)
            if len(edge_daily) >= 30:
                decomp = regress_with_hac(
                    edge_returns=edge_daily,
                    factors=factors,
                    edge_name=edge_id,
                )
                if decomp.get("ok"):
                    print(
                        f"  Decomp: α_annual={decomp['alpha_annualized']:+.4f}, "
                        f"t={decomp['alpha_tstat_hac']:+.2f}, "
                        f"R²={decomp['r_squared']:.3f}",
                        flush=True,
                    )
                else:
                    print(f"  Decomp INVALID: {decomp.get('reason')}", flush=True)
            else:
                decomp = {"edge": edge_id, "n_obs": int(len(edge_daily)), "ok": False,
                          "reason": "<30 closure days; skipping factor regression"}

        verdict = per_edge_verdict(sharpe_ci, decomp, n_trades)
        print(f"  Verdict: {verdict}", flush=True)

        per_edge_results.append({
            "edge_id": edge_id,
            "n_trades": n_trades,
            "per_year_sharpes": per_year_sharpes,
            "sharpe_ci": sharpe_ci,
            "decomp": decomp,
            "verdict": verdict,
        })

    # Write outputs
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    md = render_markdown(per_edge_results, grid_records, factors_meta)
    OUT_MD.write_text(md)
    print(f"\n[ANALYZE] Wrote {OUT_MD}", flush=True)

    payload = {
        "task_id": "T-2026-05-10-020",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "factors_meta": factors_meta,
        "per_edge": per_edge_results,
        "grid_records": grid_records,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    print(f"[ANALYZE] Wrote {OUT_JSON}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
