"""
scripts/cointegration_pair_screen.py
====================================

Cointegration screen for pairs-trading edge inventory (T-2026-05-09-017).

Procedure (Engle-Granger 2-step):
  1. Read closing prices for each candidate pair from
     ``data/processed/<TICKER>_1d.csv``.
  2. Restrict to the in-sample window (default 2021-01-01..2024-12-31).
     2025 is OOS and is NOT used for screening (avoid look-ahead in
     pair selection).
  3. OLS regression of log(Y) on log(X) → cointegration coefficient β.
  4. Engle-Granger cointegration test via ``statsmodels.tsa.stattools.coint``
     — combines OLS + ADF on the residual spread internally, returns
     p-value under the null "no cointegration".
  5. Augmented Dickey-Fuller on the residual spread directly via
     ``statsmodels.tsa.stattools.adfuller`` — explicit p-value cross-check.
  6. Half-life of mean reversion: AR(1) on Δspread vs lagged spread,
     half-life = -log(2) / log(1 + θ) where θ is the AR coefficient
     (must be negative for mean-reverting; positive θ → drifting).
  7. β stability: split in-sample window into yearly subsamples,
     recompute β per year, flag if max-min spread > 30 % of the mean β.

Acceptance criteria (any failure → drop pair):
  * Engle-Granger cointegration p-value > 0.05
  * ADF p-value on spread > 0.05 (cross-check)
  * Half-life > 60 trading days OR < 1 trading day (degenerate)
  * Max-min β spread across yearly subsamples > 30 % of mean β

Output:
  data/research/cointegrated_pairs_2026_05_09.json  — manifest of survivors
  + per-pair diagnostics for ALL candidates (failed pairs flagged) so
  the audit doc can cite numbers without re-running.

Substitutions vs the dispatchable brief:
  * QSR (Restaurant Brands) — not in F6 substrate; replaced with YUM
    (Yum! Brands; KFC/Pizza Hut/Taco Bell parent) which is a closer
    public-comp pair to MCD anyway.
  * ANTM — Anthem renamed to Elevance Health (ELV) in 2022-06; using
    ELV gives only 2.5 yr of in-sample history and beta is unstable
    across the rename. Substituted UNH/CI (Cigna), classical managed-
    care pair documented in the literature.

This script is read-only on data/processed/ and writes only to
data/research/. No engine code is modified.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from statsmodels.tsa.stattools import adfuller, coint

logger = logging.getLogger("cointegration_pair_screen")


# ---------------------------------------------------------------------------
# Candidate inventory — see module docstring for substitution rationale.
# ---------------------------------------------------------------------------
CANDIDATE_PAIRS: List[Tuple[str, str, str, str]] = [
    # (ticker_x, ticker_y, sector, rationale)
    ("KO",   "PEP",  "Beverages",         "Classic stat-arb pair, decades of literature"),
    ("MA",   "V",    "Payments",          "Highly correlated, similar business models"),
    ("MCD",  "YUM",  "Restaurants",       "MCD/QSR substituted — YUM is closer comp; both quick-service mega-caps"),
    ("HD",   "LOW",  "Home improvement",  "Duopoly, similar customer base"),
    ("CVX",  "XOM",  "Integrated oil",    "Same supercycle"),
    ("WMT",  "TGT",  "Mass retail",       "Big-box discretionary/staples overlap"),
    ("JPM",  "BAC",  "Money-center banks","Both money-center, same regulatory regime"),
    ("MSFT", "AAPL", "Mega-cap tech",     "May be too correlated to mean-revert; verify"),
    ("UNH",  "CI",   "Managed care",      "UNH/ANTM substituted — ANTM→ELV rename leaves 2.5y, CI is stable comp"),
    ("GS",   "MS",   "Investment banks",  "Both bulge-bracket, similar revenue mix"),
    ("KMI",  "OKE",  "Pipelines",         "Both midstream MLPs, similar throughput exposure"),
    ("ORCL", "IBM",  "Legacy enterprise IT", "Both legacy software/IT; MSFT is a separate cohort"),
]

DEFAULT_DATA_DIR = Path("data/processed")
DEFAULT_OUTPUT = Path("data/research/cointegrated_pairs_2026_05_09.json")


# ---------------------------------------------------------------------------
# Per-pair statistics — pure functions; deterministic given fixed inputs.
# ---------------------------------------------------------------------------

def load_close_series(ticker: str, data_dir: Path) -> Optional[pd.Series]:
    """Load adjusted closes from data/processed/<ticker>_1d.csv as a
    DatetimeIndex'd Series. Returns None if the file is missing or has
    no usable rows.
    """
    path = data_dir / f"{ticker}_1d.csv"
    if not path.exists():
        logger.warning("Missing CSV for %s at %s", ticker, path)
        return None
    df = pd.read_csv(path, parse_dates=["Date"])
    if "Close" not in df.columns:
        logger.warning("No Close column for %s", ticker)
        return None
    df = df.dropna(subset=["Date", "Close"]).sort_values("Date")
    s = pd.Series(df["Close"].astype(float).values, index=pd.DatetimeIndex(df["Date"]))
    s = s[~s.index.duplicated(keep="last")]
    return s


def aligned_log_prices(
    sx: pd.Series, sy: pd.Series, start: str, end: str,
) -> Optional[Tuple[pd.Series, pd.Series]]:
    """Restrict both series to [start, end], align on common dates,
    take logs. Returns None if fewer than 252 aligned bars.
    """
    sx_w = sx.loc[(sx.index >= start) & (sx.index <= end)]
    sy_w = sy.loc[(sy.index >= start) & (sy.index <= end)]
    common = sx_w.index.intersection(sy_w.index)
    if len(common) < 252:
        logger.warning("Too few aligned bars (%d) for window %s..%s", len(common), start, end)
        return None
    return np.log(sx_w.loc[common]), np.log(sy_w.loc[common])


def estimate_beta_ols(log_x: pd.Series, log_y: pd.Series) -> Tuple[float, float]:
    """OLS: log_y = α + β·log_x + ε. Returns (alpha, beta) via
    closed-form OLS — no statsmodels dependency for the regression
    itself (faster + deterministic).
    """
    x = log_x.values
    y = log_y.values
    x_mean = float(np.mean(x))
    y_mean = float(np.mean(y))
    cov = float(np.sum((x - x_mean) * (y - y_mean)))
    var = float(np.sum((x - x_mean) ** 2))
    if var == 0.0:
        return 0.0, 0.0
    beta = cov / var
    alpha = y_mean - beta * x_mean
    return alpha, beta


def half_life_ar1(spread: np.ndarray) -> float:
    """Estimate half-life of mean reversion via AR(1) on Δspread vs
    lagged spread. Returns +inf if the AR coefficient is non-negative
    (no mean reversion) or if regression is degenerate.
    """
    s = np.asarray(spread, dtype=float)
    if len(s) < 30:
        return float("inf")
    s_lag = s[:-1]
    ds = s[1:] - s[:-1]
    sx_mean = float(np.mean(s_lag))
    dy_mean = float(np.mean(ds))
    cov = float(np.sum((s_lag - sx_mean) * (ds - dy_mean)))
    var = float(np.sum((s_lag - sx_mean) ** 2))
    if var == 0.0:
        return float("inf")
    theta = cov / var
    if theta >= 0:
        return float("inf")  # not mean-reverting
    arg = 1.0 + theta
    if arg <= 0:
        return float("inf")  # degenerate / explosive
    return float(-np.log(2.0) / np.log(arg))


def beta_stability(
    log_x: pd.Series, log_y: pd.Series, years: List[int],
) -> Tuple[List[float], float]:
    """Compute β per yearly subsample. Returns (per_year_betas, instability_pct)
    where instability_pct = (max - min) / abs(mean) * 100. Pairs with
    instability_pct > 30 are flagged as unstable.
    """
    betas: List[float] = []
    for yr in years:
        start = f"{yr}-01-01"
        end = f"{yr}-12-31"
        x_sub = log_x.loc[(log_x.index >= start) & (log_x.index <= end)]
        y_sub = log_y.loc[(log_y.index >= start) & (log_y.index <= end)]
        if len(x_sub) < 60:
            continue
        _, beta_yr = estimate_beta_ols(x_sub, y_sub)
        betas.append(beta_yr)
    if len(betas) < 2:
        return betas, float("inf")
    mean_b = float(np.mean(betas))
    if mean_b == 0.0:
        return betas, float("inf")
    instability_pct = float((max(betas) - min(betas)) / abs(mean_b) * 100.0)
    return betas, instability_pct


# ---------------------------------------------------------------------------
# Per-pair screen
# ---------------------------------------------------------------------------

def screen_pair(
    ticker_x: str,
    ticker_y: str,
    sector: str,
    rationale: str,
    data_dir: Path,
    is_start: str,
    is_end: str,
    coint_p_max: float,
    adf_p_max: float,
    halflife_min: float,
    halflife_max: float,
    beta_instability_max_pct: float,
) -> Dict[str, object]:
    """Run the full screen on one pair. Returns a dict with diagnostics
    + a 'survives' flag + 'reason' (if dropped).
    """
    out: Dict[str, object] = {
        "ticker_x": ticker_x,
        "ticker_y": ticker_y,
        "sector": sector,
        "rationale": rationale,
        "survives": False,
        "drop_reasons": [],
    }

    sx = load_close_series(ticker_x, data_dir)
    sy = load_close_series(ticker_y, data_dir)
    if sx is None or sy is None:
        out["drop_reasons"].append(
            f"Missing CSV: {ticker_x if sx is None else ticker_y}",
        )
        return out

    aligned = aligned_log_prices(sx, sy, is_start, is_end)
    if aligned is None:
        out["drop_reasons"].append("Insufficient aligned bars in in-sample window")
        return out
    log_x, log_y = aligned
    out["n_bars_in_sample"] = int(len(log_x))

    # --- Engle-Granger cointegration test (statsmodels.coint) -------------
    # coint() runs OLS internally, then ADF on the residual; returns (t, p, cv).
    coint_t, coint_p, _ = coint(log_y.values, log_x.values, autolag="AIC")
    out["coint_t"] = float(coint_t)
    out["coint_p"] = float(coint_p)

    # --- OLS β estimate over the FULL window (used by the edge at runtime)
    alpha, beta = estimate_beta_ols(log_x, log_y)
    out["alpha"] = float(alpha)
    out["beta"] = float(beta)
    spread = log_y.values - beta * log_x.values
    out["spread_mean"] = float(np.mean(spread))
    out["spread_std"] = float(np.std(spread, ddof=1))

    # --- ADF on spread directly (cross-check) -----------------------------
    adf_stat, adf_p, *_ = adfuller(spread, autolag="AIC")
    out["adf_stat"] = float(adf_stat)
    out["adf_p"] = float(adf_p)

    # --- Half-life of mean reversion --------------------------------------
    hl = half_life_ar1(spread)
    out["half_life_days"] = float(hl) if np.isfinite(hl) else None

    # --- Beta stability across yearly subsamples --------------------------
    is_start_year = int(is_start[:4])
    is_end_year = int(is_end[:4])
    years = list(range(is_start_year, is_end_year + 1))
    yearly_betas, instability_pct = beta_stability(log_x, log_y, years)
    out["yearly_betas"] = [float(b) for b in yearly_betas]
    out["beta_instability_pct"] = (
        float(instability_pct) if np.isfinite(instability_pct) else None
    )

    # --- Decision ----------------------------------------------------------
    drops: List[str] = []
    if coint_p > coint_p_max:
        drops.append(f"coint_p={coint_p:.3f} > {coint_p_max}")
    if adf_p > adf_p_max:
        drops.append(f"adf_p={adf_p:.3f} > {adf_p_max}")
    if not np.isfinite(hl):
        drops.append("half_life=inf (no mean reversion)")
    elif hl > halflife_max:
        drops.append(f"half_life={hl:.1f}d > {halflife_max}d")
    elif hl < halflife_min:
        drops.append(f"half_life={hl:.2f}d < {halflife_min}d (degenerate)")
    if not np.isfinite(instability_pct):
        drops.append("beta unstable (degenerate)")
    elif instability_pct > beta_instability_max_pct:
        drops.append(
            f"beta_instability={instability_pct:.1f}% > {beta_instability_max_pct}%",
        )

    out["drop_reasons"] = drops
    out["survives"] = len(drops) == 0
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--is-start", default="2021-01-01")
    parser.add_argument("--is-end", default="2024-12-31")
    parser.add_argument("--coint-p-max", type=float, default=0.05)
    parser.add_argument("--adf-p-max", type=float, default=0.05)
    parser.add_argument("--halflife-min", type=float, default=1.0)
    parser.add_argument("--halflife-max", type=float, default=60.0)
    parser.add_argument("--beta-instability-max-pct", type=float, default=30.0)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    results: List[Dict[str, object]] = []
    for tx, ty, sector, rationale in CANDIDATE_PAIRS:
        print(f"[SCREEN] {tx}/{ty} ({sector})...")
        diag = screen_pair(
            ticker_x=tx,
            ticker_y=ty,
            sector=sector,
            rationale=rationale,
            data_dir=args.data_dir,
            is_start=args.is_start,
            is_end=args.is_end,
            coint_p_max=args.coint_p_max,
            adf_p_max=args.adf_p_max,
            halflife_min=args.halflife_min,
            halflife_max=args.halflife_max,
            beta_instability_max_pct=args.beta_instability_max_pct,
        )
        if diag.get("survives"):
            print(
                f"  PASS — coint_p={diag.get('coint_p'):.4f} "
                f"adf_p={diag.get('adf_p'):.4f} "
                f"half_life={diag.get('half_life_days'):.1f}d "
                f"beta={diag.get('beta'):.3f} "
                f"instability={diag.get('beta_instability_pct'):.1f}%",
            )
        else:
            print(f"  DROP — {'; '.join(diag.get('drop_reasons', []))}")
        results.append(diag)

    survivors = [r for r in results if r.get("survives")]
    print(
        f"\n[SUMMARY] {len(survivors)}/{len(results)} pairs survived the screen.",
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task_id": "T-2026-05-09-017",
        "in_sample_window": {"start": args.is_start, "end": args.is_end},
        "thresholds": {
            "coint_p_max": args.coint_p_max,
            "adf_p_max": args.adf_p_max,
            "halflife_min_days": args.halflife_min,
            "halflife_max_days": args.halflife_max,
            "beta_instability_max_pct": args.beta_instability_max_pct,
        },
        "candidates": results,
        "survivor_pair_ids": [
            f"pairs_trading_{r['ticker_x']}_{r['ticker_y']}_v1"
            for r in survivors
        ],
    }
    args.output.write_text(json.dumps(payload, indent=2, default=str))
    print(f"[SCREEN] Manifest written to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
