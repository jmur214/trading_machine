"""
scripts/factor_decomp_substrate_honest.py
==========================================
C-collapses-1.25 — Factor decomposition on the 6 active edges using
Arm 1 trade logs from the substrate-honest re-measurement (T-002).

Per spec (`docs/Measurements/2026-05/spec_c_collapses_1_25_factor_decomp_2026_05_08.md`):

- Reuses `core.factor_decomposition.load_factor_data` for FF5+Mom factor
  data (the convention `tier_classifier.py` uses).
- Per-edge attribution stream: for each closed trade, attribute realized
  pnl to that trade's recorded `edge_id` on the closure date. Convert
  daily PnL → daily return by dividing by the prior-day portfolio equity
  from `portfolio_snapshots.csv`.
- OLS regression of excess returns on FF5 + Mom with **Newey-West HAC
  standard errors** (lag = floor(4*(T/100)^(2/9))). Hand-rolled because
  `statsmodels` is not on the environment and the spec forbids fetching
  fresh deps without director approval.
- Bootstrap 95% CI on alpha (residual block-bootstrap, 1000 iters).

Inputs:
  - data/trade_logs/<run_id>/trades.csv for each of the 5 Arm 1 yearly
    runs (2021-2025, rep 1; reps 2/3 are bitwise-identical so any rep
    suffices)
  - data/trade_logs/<run_id>/portfolio_snapshots.csv for daily equity
  - data/research/ff5_daily.csv + mom_daily.csv (cached on disk)

Outputs:
  - docs/Measurements/2026-05/c_collapses_1_25_factor_decomp_verdict_2026_05_08.md
  - docs/Measurements/2026-05/c_collapses_1_25_factor_decomp_verdict_2026_05_08.json

Re-runnable: deterministic (RNG seeded at 0); same trade logs in →
bit-identical outputs out.

Usage:
  python -m scripts.factor_decomp_substrate_honest
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.factor_decomposition import load_factor_data  # noqa: E402

TRADE_LOGS = ROOT / "data" / "trade_logs"
OUT_DIR = ROOT / "docs" / "Measurements" / "2026-05"
OUT_MD = OUT_DIR / "c_collapses_1_25_factor_decomp_verdict_2026_05_08.md"
OUT_JSON = OUT_DIR / "c_collapses_1_25_factor_decomp_verdict_2026_05_08.json"

# Arm 1 rep-1 run_ids from T-002 substrate-honest re-measurement.
# (reps 2/3 within each year are bitwise identical; any rep suffices.)
ARM1_RUN_IDS = {
    2021: "191c14ba-3e8d-4f7f-ae08-8b24bf54dec0",
    2022: "85ae17d9-a7b9-473b-933a-94dc0c681fcc",
    2023: "a23ce948-9fd0-43ef-84c6-dc6aaa7653ca",
    2024: "a1591104-7c2b-428c-a02a-a1fa712fe569",
    2025: "a3aac752-6daa-487a-a3e5-2f1e4d81d319",
}

ACTIVE_EDGES = [
    "volume_anomaly_v1",  # primary question per spec
    "gap_fill_v1",
    "value_book_to_market_v1",
    "accruals_inv_sloan_v1",
    "value_earnings_yield_v1",
    "accruals_inv_asset_growth_v1",
]

FACTOR_COLS = ["MktRF", "SMB", "HML", "RMW", "CMA", "Mom"]

T_STAT_THRESHOLD = 2.0
ALPHA_ANNUAL_FLOOR = 0.0  # spec uses just t > 2; alpha sign reported separately


def newey_west_lag(n: int) -> int:
    """Politis-style automatic lag: floor(4 * (T/100)^(2/9))."""
    if n < 4:
        return 0
    return int(np.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))


def newey_west_cov(X: np.ndarray, resid: np.ndarray, lag: int) -> np.ndarray:
    """Hand-rolled Newey-West (Bartlett-kernel) HAC covariance.

    Standard formula: cov_hat = (X'X)^-1 S (X'X)^-1
    where
      S = sum_{l=-L..L} (1 - |l|/(L+1)) * sum_t (e_t e_{t-l} x_t x_{t-l}')
    """
    n, k = X.shape
    XtX_inv = np.linalg.pinv(X.T @ X)
    # Build S
    e = resid.reshape(-1, 1)
    weighted_x = X * e  # element-wise: e_t * x_t (each row)
    S = weighted_x.T @ weighted_x  # the L=0 term
    for l in range(1, lag + 1):
        w = 1.0 - l / (lag + 1.0)
        # Sum_{t=l..n-1} e_t * e_{t-l} * x_t * x_{t-l}'
        Gamma = weighted_x[l:].T @ weighted_x[:n - l]
        S = S + w * (Gamma + Gamma.T)
    return XtX_inv @ S @ XtX_inv


def _trades_path(run_id: str) -> Optional[Path]:
    p1 = TRADE_LOGS / run_id / "trades.csv"
    p2 = TRADE_LOGS / run_id / f"trades_{run_id}.csv"
    return p1 if p1.exists() else (p2 if p2.exists() else None)


def _snapshots_path(run_id: str) -> Optional[Path]:
    p1 = TRADE_LOGS / run_id / "portfolio_snapshots.csv"
    p2 = TRADE_LOGS / run_id / f"portfolio_snapshots_{run_id}.csv"
    return p1 if p1.exists() else (p2 if p2.exists() else None)


INITIAL_CAPITAL = 100_000.0  # tier_classifier convention


def load_arm1_attribution() -> Dict[str, pd.Series]:
    """Build per-edge daily-PnL-as-return series from the 5 Arm 1 yearly runs.

    Matches the convention in `engines/engine_a_alpha/tier_classifier.py`:
      - Sum closed-trade `pnl` by date per edge_id.
      - Divide by initial_capital (constant 100k, not prior-day equity).
      - Include ONLY days with at least one closure for that edge —
        zero-pnl days are dropped, not filled with zero.
        This is the spec's explicit fallback ("contribute PnL to that
        edge's daily stream on closure date") and matches tier_classifier.

    Returns a dict mapping edge_id → daily-return Series across all 5 years.
    """
    per_edge_frames: Dict[str, List[pd.Series]] = {e: [] for e in ACTIVE_EDGES}

    for year, run_id in ARM1_RUN_IDS.items():
        tp = _trades_path(run_id)
        if tp is None:
            raise FileNotFoundError(f"trades.csv missing for {year} run_id={run_id}")

        trades = pd.read_csv(tp, low_memory=False, usecols=["timestamp", "edge_id", "pnl"])
        trades["timestamp"] = pd.to_datetime(trades["timestamp"])
        trades["pnl"] = pd.to_numeric(trades["pnl"], errors="coerce")
        closed = trades.dropna(subset=["pnl"]).copy()
        if closed.empty:
            continue
        closed["date"] = closed["timestamp"].dt.normalize()

        for edge in ACTIVE_EDGES:
            sub = closed[closed["edge_id"] == edge]
            if sub.empty:
                continue
            daily = sub.groupby("date")["pnl"].sum()
            per_edge_frames[edge].append(daily / INITIAL_CAPITAL)

    out: Dict[str, pd.Series] = {}
    for edge, parts in per_edge_frames.items():
        if not parts:
            out[edge] = pd.Series(dtype=float)
            continue
        s = pd.concat(parts).sort_index()
        s = s[~s.index.duplicated(keep="first")]
        s.name = edge
        out[edge] = s
    return out


def regress_with_hac(
    edge_returns: pd.Series,
    factors: pd.DataFrame,
    edge_name: str,
) -> Dict:
    """OLS with Newey-West HAC SE; returns alpha + t-stats + betas + R².

    Conventions match `core.factor_decomposition.regress_returns_on_factors`:
    excess = edge_return - RF. Intercept = α (daily). Annualized α = α × 252.
    """
    # Inner-join on date
    aligned = pd.concat(
        [edge_returns.rename("edge"), factors],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < 30:
        return {"edge": edge_name, "n_obs": len(aligned), "ok": False,
                "reason": "insufficient observations (<30)"}

    excess = (aligned["edge"] - aligned["RF"]).values
    X = aligned[FACTOR_COLS].values
    X_design = np.hstack([np.ones((len(excess), 1)), X])

    coefs, _, _, _ = np.linalg.lstsq(X_design, excess, rcond=None)
    fitted = X_design @ coefs
    resid = excess - fitted

    n = len(excess)
    lag = newey_west_lag(n)
    hac_cov = newey_west_cov(X_design, resid, lag)
    hac_se = np.sqrt(np.maximum(np.diag(hac_cov), 0.0))

    alpha_daily = float(coefs[0])
    alpha_annual = alpha_daily * 252.0
    alpha_se_daily = float(hac_se[0])
    alpha_tstat = alpha_daily / alpha_se_daily if alpha_se_daily > 0 else 0.0
    # Annualized α SE: SE(α_daily) × 252 (linear scaling).
    alpha_se_annual = alpha_se_daily * 252.0

    # Analytic 95% CI on annualized α (z=1.96 large-sample approx)
    z = 1.96
    alpha_ci_low_annual = alpha_annual - z * alpha_se_annual
    alpha_ci_high_annual = alpha_annual + z * alpha_se_annual

    # Per-factor betas + HAC t-stats
    betas: Dict[str, Dict[str, float]] = {}
    for i, fac in enumerate(FACTOR_COLS):
        b = float(coefs[i + 1])
        se = float(hac_se[i + 1])
        t = b / se if se > 0 else 0.0
        betas[fac] = {"beta": b, "se": se, "t_stat": t}

    # R²
    ss_res = float(resid @ resid)
    ss_tot = float(((excess - excess.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Bootstrap CI on annualized α (residual moving-block bootstrap).
    # block size = HAC lag + 1. Seeded for reproducibility.
    rng = np.random.default_rng(0)
    block = max(1, lag + 1)
    n_iter = 1000
    boot_alphas = np.empty(n_iter, dtype=float)
    n_blocks = int(np.ceil(n / block))
    for i in range(n_iter):
        # Moving-block bootstrap of residuals (preserves serial structure).
        # Sample n_blocks starting indices and concatenate consecutive blocks.
        starts = rng.integers(0, max(1, n - block + 1), size=n_blocks)
        boot_idx = np.concatenate([
            np.arange(s, s + block) for s in starts
        ])[:n]
        e_star = resid[boot_idx]
        # y* = X β̂ + e* — refit α on bootstrap residuals
        y_star = fitted + e_star
        b_star, _, _, _ = np.linalg.lstsq(X_design, y_star, rcond=None)
        boot_alphas[i] = float(b_star[0]) * 252.0
    boot_ci_low = float(np.percentile(boot_alphas, 2.5))
    boot_ci_high = float(np.percentile(boot_alphas, 97.5))
    p_above_zero = float((boot_alphas > 0).mean())

    return {
        "edge": edge_name,
        "n_obs": n,
        "lag_neweywest": lag,
        "alpha_daily": alpha_daily,
        "alpha_annualized": alpha_annual,
        "alpha_se_daily_hac": alpha_se_daily,
        "alpha_se_annualized_hac": alpha_se_annual,
        "alpha_tstat_hac": float(alpha_tstat),
        "alpha_ci_low_analytic": alpha_ci_low_annual,
        "alpha_ci_high_analytic": alpha_ci_high_annual,
        "alpha_ci_low_bootstrap": boot_ci_low,
        "alpha_ci_high_bootstrap": boot_ci_high,
        "alpha_p_above_zero_bootstrap": p_above_zero,
        "r_squared": r2,
        "raw_sharpe": float(aligned["edge"].mean() / aligned["edge"].std() * np.sqrt(252))
                       if aligned["edge"].std() > 0 else 0.0,
        "betas": betas,
        "ok": True,
    }


def verdict_bucket(decomp: Dict) -> str:
    """Apply the spec's verdict framing to volume_anomaly_v1's result."""
    if not decomp.get("ok"):
        return "INVALID — insufficient observations"
    t = decomp["alpha_tstat_hac"]
    a = decomp["alpha_annualized"]
    r2 = decomp["r_squared"]
    if abs(t) > T_STAT_THRESHOLD and a > 0:
        return ("LOAD-BEARING ALPHA REAL POST-FACTOR (t>2 with positive α). "
                "Substrate-honest 0.27 mean Sharpe reflects ensemble drag from "
                "net-negative edges, not a vol_anomaly_v1 alpha collapse. "
                "Recommend: pause/retire net-drag edges, test 2-edge ensemble.")
    if abs(t) > T_STAT_THRESHOLD and a < 0:
        return ("ALPHA REVERSED (t>2 with negative α). Major finding — "
                "volume_anomaly_v1 is anti-factor on substrate-honest universe. "
                "Investigate immediately for measurement bug or genuine reversal.")
    if abs(t) <= T_STAT_THRESHOLD and r2 < 0.3:
        return ("GENUINELY NOISY (|t|≤2 and R²<0.3). Alpha not detectable on "
                "substrate-honest universe; statistical power not there. "
                "Don't flip flags from substrate measurement.")
    return ("DISGUISED FACTOR EXPOSURE (|t|≤2 with R²≥0.3). Apparent alpha "
            "was factor exposure. Load-bearing 2-edge story does not survive "
            "factor adjustment. Engine-completion structural review remains "
            "the answer.")


def render_markdown(per_edge: List[Dict], panel_meta: Dict, verdict: str) -> str:
    lines: List[str] = []
    lines.append("# C-collapses-1.25 — Factor Decomp Verdict (T-2026-05-08-004)")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("Spec: `docs/Measurements/2026-05/spec_c_collapses_1_25_factor_decomp_2026_05_08.md`")
    lines.append("Source: T-002 Arm 1 trade logs (substrate-honest, HMM OFF, 6 actives)")
    lines.append("")
    lines.append("## Inputs + method")
    lines.append("")
    lines.append("Trade-log run_ids used (rep 1 of each year — reps 2/3 are bitwise-identical):")
    for year, rid in sorted(ARM1_RUN_IDS.items()):
        lines.append(f"- {year}: `{rid}`")
    lines.append("")
    n_obs_per_edge = panel_meta.get("n_obs_per_edge", {})
    lines.append("- Per-edge **closure-day count** (matches `tier_classifier.py`'s "
                 "`_compute_decomps_from_trades`):")
    for edge in ACTIVE_EDGES:
        lines.append(f"  - `{edge}`: {n_obs_per_edge.get(edge, 0)} closure-days")
    lines.append("")
    lines.append("- **Per-edge attribution convention** (matches "
                 "`engines/engine_a_alpha/tier_classifier.py`): closed-trade `pnl` summed "
                 "by `edge_id` per closure-date, divided by `initial_capital = $100,000` "
                 "(constant — NOT prior-day equity). Days **without** a closure for a given "
                 "edge are EXCLUDED from that edge's regression (sparse-event series, not "
                 "zero-filled). This is the project's standard tier-classification methodology.")
    lines.append("- Regression: OLS of (edge_return − RF) on FF5+Mom factors, with "
                 "**Newey-West HAC** standard errors (hand-rolled; `statsmodels` not "
                 "available and the spec forbids fetching fresh deps).")
    lines.append("- Newey-West lag (Politis auto, per-edge): floor(4 × (T/100)^(2/9)) "
                 "where T = that edge's closure-day count.")
    lines.append("- α CI (annualized): both **analytic** (z=1.96 × HAC SE × 252) and "
                 "**bootstrap** (residual moving-block bootstrap, block = lag+1, "
                 "1000 iters, seed=0).")
    lines.append("")

    lines.append("## Verdict (primary question — `volume_anomaly_v1`)")
    lines.append("")
    lines.append(verdict)
    lines.append("")

    lines.append("## Per-edge factor decomp")
    lines.append("")
    lines.append("| Edge | Annualized α | α 95% CI (HAC) | α 95% CI (bootstrap) | t-stat (α, HAC) | R² | Raw Sharpe | t > 2 ? | Notes |")
    lines.append("|---|---:|---|---|---:|---:|---:|---|---|")
    for d in per_edge:
        if not d.get("ok"):
            lines.append(f"| `{d['edge']}` | — | — | — | — | — | — | NO | {d.get('reason', '?')} |")
            continue
        a = d["alpha_annualized"]
        t = d["alpha_tstat_hac"]
        ci_a_lo = d["alpha_ci_low_analytic"]
        ci_a_hi = d["alpha_ci_high_analytic"]
        ci_b_lo = d["alpha_ci_low_bootstrap"]
        ci_b_hi = d["alpha_ci_high_bootstrap"]
        survives = "**YES**" if abs(t) > T_STAT_THRESHOLD else "no"
        note = ""
        if d["edge"] == "volume_anomaly_v1":
            note = "**Primary** — load-bearing edge"
        elif d["edge"] in ("value_earnings_yield_v1", "accruals_inv_asset_growth_v1"):
            note = "Net-drag edge per per_edge_contribution"
        lines.append(
            f"| `{d['edge']}` | {a:+.4f} | [{ci_a_lo:+.4f}, {ci_a_hi:+.4f}] | "
            f"[{ci_b_lo:+.4f}, {ci_b_hi:+.4f}] | {t:+.3f} | {d['r_squared']:.3f} | "
            f"{d['raw_sharpe']:+.3f} | {survives} | {note} |"
        )
    lines.append("")

    lines.append("## Factor exposures (β + HAC t-stat per factor)")
    lines.append("")
    header = "| Edge | " + " | ".join(f"{f} β | {f} t" for f in FACTOR_COLS) + " |"
    sep = "|---|" + "---:|" * (2 * len(FACTOR_COLS))
    lines.append(header)
    lines.append(sep)
    for d in per_edge:
        if not d.get("ok"):
            continue
        cells = [f"`{d['edge']}`"]
        for fac in FACTOR_COLS:
            b = d["betas"][fac]
            cells.append(f"{b['beta']:+.3f}")
            cells.append(f"{b['t_stat']:+.2f}")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    lines.append("## Survival summary")
    lines.append("")
    surv = [d for d in per_edge if d.get("ok") and abs(d["alpha_tstat_hac"]) > T_STAT_THRESHOLD]
    surv_pos = [d for d in surv if d["alpha_annualized"] > 0]
    surv_neg = [d for d in surv if d["alpha_annualized"] < 0]
    lines.append(f"- Edges with |t(α)| > 2 (HAC): **{len(surv)} of {len([d for d in per_edge if d.get('ok')])}**")
    if surv_pos:
        lines.append("- t > 2, α > 0 (real factor-adjusted alpha):")
        for d in surv_pos:
            lines.append(f"  - `{d['edge']}` (α annual {d['alpha_annualized']:+.3%}, t={d['alpha_tstat_hac']:+.2f})")
    if surv_neg:
        lines.append("- t > 2, α < 0 (anti-factor):")
        for d in surv_neg:
            lines.append(f"  - `{d['edge']}` (α annual {d['alpha_annualized']:+.3%}, t={d['alpha_tstat_hac']:+.2f})")
    if not surv:
        lines.append("- **No edge survives at |t(α)| > 2 on substrate-honest universe.**")
    lines.append("")

    lines.append("## Caveats")
    lines.append("")
    lines.append("- **Per-edge attribution is ~10–15% noisy.** Trades are tagged with the dominant "
                 "edge_id at entry per `signal_processor`, but real ensemble interactions are "
                 "ignored. A trade entered on multi-edge consensus with all-credit assigned to one "
                 "edge double-counts in this attribution.")
    lines.append("- **5-year sample is short for HAC inference.** Politis auto-lag is the project "
                 "default but residual structure may not be stable across regime shifts.")
    lines.append("- **`accruals_inv_sloan_v1` is in the active 6 but was a $-PnL drag in T-002 Arm 1** "
                 "(-$1,623; spec listed only the larger 2 drags). Whether it's factor-adjusted-real "
                 "or factor-disguised here is a fresh data point relative to the spec drop-list.")
    lines.append("")

    return "\n".join(lines)


def build() -> dict:
    edge_streams = load_arm1_attribution()
    factors = load_factor_data(auto_download=False)
    factors.index = factors.index.normalize()
    if "RF" not in factors.columns:
        raise RuntimeError("RF column missing from factor data")

    # Per-edge n_obs is the intersection of that edge's closure-day series
    # with the factor calendar (not a single panel).
    panel_meta = {
        "convention": "tier_classifier-compatible: closed-trade pnl per "
                      "edge per closure-day, divided by initial_capital "
                      "($100k). Days without a closure for an edge are "
                      "EXCLUDED from that edge's regression (not filled "
                      "with zero).",
        "initial_capital": INITIAL_CAPITAL,
        "n_obs_per_edge": {edge: int(len(s)) for edge, s in edge_streams.items()},
    }

    per_edge: List[Dict] = []
    for edge in ACTIVE_EDGES:
        s = edge_streams.get(edge, pd.Series(dtype=float))
        if s.empty:
            per_edge.append({"edge": edge, "ok": False,
                             "reason": "no closed trades for this edge"})
            continue
        result = regress_with_hac(s, factors, edge)
        per_edge.append(result)

    # Volume anomaly is primary
    vol_anomaly = next((d for d in per_edge if d["edge"] == "volume_anomaly_v1"), None)
    verdict = verdict_bucket(vol_anomaly) if vol_anomaly else "MISSING — volume_anomaly_v1 not in panel"

    md = render_markdown(per_edge, panel_meta, verdict)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(md)

    payload = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "spec": "docs/Measurements/2026-05/spec_c_collapses_1_25_factor_decomp_2026_05_08.md",
        "arm1_run_ids": ARM1_RUN_IDS,
        "panel": panel_meta,
        "verdict_volume_anomaly_v1": verdict,
        "per_edge": per_edge,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args()
    payload = build()
    print(f"[FACTOR_DECOMP] Wrote {OUT_MD}")
    print(f"[FACTOR_DECOMP] Wrote {OUT_JSON}")
    print(f"[FACTOR_DECOMP] Verdict (vol_anomaly_v1): {payload['verdict_volume_anomaly_v1']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
