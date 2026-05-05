"""
core/factor_decomposition.py
=============================
Fama-French 5 + Momentum factor decomposition utilities.

Used by:
- ``scripts/factor_decomposition_baseline.py`` (one-shot diagnostic over
  every active edge, output to docs/Measurements/<year-month>/...)
- ``engines/engine_d_discovery/discovery.py::validate_candidate`` Gate 6
  (per-candidate factor-significance gate)

The model: regress an edge's daily excess return on the 6 factors, treat
the intercept as the "alpha" component. If the intercept is statistically
significant AND economically meaningful, the edge is producing real alpha
that isn't replicable by holding factor ETFs cheaply (MTUM/IWM/VLUE/QUAL/USMV).

No new dependencies — uses stdlib + numpy. Avoids pulling in statsmodels
or pandas-datareader for what is fundamentally a small linear regression.
"""
from __future__ import annotations

import io
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

FF5_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
MOM_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_CSV.zip"

CACHE_DIR = ROOT / "data" / "research"
FF5_CACHE = CACHE_DIR / "ff5_daily.csv"
MOM_CACHE = CACHE_DIR / "mom_daily.csv"

# Factor columns in canonical order. The momentum file's column gets
# renamed to "Mom" in `load_factor_data` for consistency.
DEFAULT_FACTOR_COLS = ["MktRF", "SMB", "HML", "RMW", "CMA", "Mom"]

# Default Gate 6 thresholds (configurable per-call).
DEFAULT_ALPHA_TSTAT_MIN = 2.0
DEFAULT_ALPHA_ANNUAL_MIN = 0.02  # 2% annualized
DEFAULT_MIN_OBSERVATIONS = 30


@dataclass(frozen=True)
class FactorDecomp:
    """Result of regressing an edge's daily returns on FF5 + Mom factors.

    Convention: ``alpha_daily`` is the intercept of the regression on
    EXCESS returns (edge_return - RF). ``alpha_annualized`` = alpha_daily
    × 252. ``alpha_tstat`` is the t-statistic for the intercept.
    """
    edge: str
    n_obs: int
    raw_sharpe: float
    alpha_daily: float
    alpha_annualized: float
    alpha_tstat: float
    r_squared: float
    betas: Dict[str, float]


# ---------------------------------------------------------------------------
# Factor data loading
# ---------------------------------------------------------------------------

def _download_ff_csv(url: str, dest_path: Path) -> None:
    """Download a Ken French zip file, extract its single CSV, save to dest."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        zip_bytes = resp.read()
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
        if not names:
            raise RuntimeError(f"No CSV in zip from {url}")
        with zf.open(names[0]) as f:
            content = f.read()
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(content)


def _parse_ff_csv(path: Path) -> pd.DataFrame:
    """Parse a Ken French daily-frequency factor CSV.

    Format: comma-separated. Multi-line text preamble, then a header line
    starting with ``,`` (date column has no label), then YYYYMMDD,float,...
    rows, then a copyright footer.
    """
    raw = path.read_text()
    lines = raw.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith(","):
            continue
        if any(tok in stripped for tok in ["Mkt-RF", "Mkt", "Mom"]):
            header_idx = i
            break
    if header_idx is None:
        raise RuntimeError(f"No header line in {path}")
    cols = [c.strip() for c in lines[header_idx].split(",")]
    cols = ["Date" if c == "" else c for c in cols]
    data_rows: List[str] = []
    for line in lines[header_idx + 1:]:
        if "," not in line:
            if data_rows:
                break
            continue
        first_field = line.split(",", 1)[0].strip()
        if len(first_field) == 8 and first_field.isdigit():
            data_rows.append(line)
        elif data_rows:
            break
    if not data_rows:
        raise RuntimeError(f"No data rows in {path}")
    df = pd.read_csv(io.StringIO("\n".join(data_rows)), names=cols, header=None)
    df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d")
    factor_cols = [c for c in df.columns if c != "Date"]
    df[factor_cols] = df[factor_cols].astype(float) / 100.0
    return df.set_index("Date").sort_index()


def load_factor_data(
    auto_download: bool = True,
    ff5_cache: Optional[Path] = None,
    mom_cache: Optional[Path] = None,
) -> pd.DataFrame:
    """Load FF5 + Momentum into a single DataFrame indexed by Date.

    `auto_download=True` will fetch missing files from Ken French's public
    FTP. Set False in test contexts that should fail loudly when the
    cache is absent.
    """
    ff5_path = ff5_cache or FF5_CACHE
    mom_path = mom_cache or MOM_CACHE

    if not ff5_path.exists():
        if not auto_download:
            raise FileNotFoundError(f"FF5 cache missing: {ff5_path}")
        _download_ff_csv(FF5_URL, ff5_path)
    if not mom_path.exists():
        if not auto_download:
            raise FileNotFoundError(f"Momentum cache missing: {mom_path}")
        _download_ff_csv(MOM_URL, mom_path)

    ff5 = _parse_ff_csv(ff5_path)
    mom = _parse_ff_csv(mom_path)
    mom.columns = [c.strip() for c in mom.columns]
    factors = ff5.join(mom, how="inner", rsuffix="_mom")
    factors = factors.rename(columns={
        "Mkt-RF": "MktRF", "Mkt-Rf": "MktRF",
    })
    return factors


# ---------------------------------------------------------------------------
# Regression
# ---------------------------------------------------------------------------

def regress_returns_on_factors(
    returns: pd.Series,
    factors: pd.DataFrame,
    factor_cols: Optional[List[str]] = None,
    edge_name: str = "?",
    min_observations: int = DEFAULT_MIN_OBSERVATIONS,
) -> Optional[FactorDecomp]:
    """OLS regression of excess returns on factor columns.

    Returns None when overlap between `returns` and `factors` has fewer
    than `min_observations` rows, or when the regression is degenerate.

    Convention: `returns` is interpreted as the edge's daily return
    (NOT excess). RF is subtracted internally to form the regression's
    excess-return target.
    """
    if factor_cols is None:
        factor_cols = [c for c in DEFAULT_FACTOR_COLS if c in factors.columns]
    if not factor_cols:
        raise ValueError("No factor columns available in `factors`")
    if "RF" not in factors.columns:
        raise ValueError("`factors` must include a RF column (risk-free rate)")

    aligned = pd.concat(
        [returns.rename("edge"), factors],
        axis=1,
        join="inner",
    ).dropna()
    if len(aligned) < min_observations:
        return None

    excess = (aligned["edge"] - aligned["RF"]).values
    X = aligned[factor_cols].values
    X_design = np.hstack([np.ones((len(excess), 1)), X])
    coefs, _, _, _ = np.linalg.lstsq(X_design, excess, rcond=None)
    alpha = float(coefs[0])
    betas = {factor_cols[i]: float(coefs[i + 1]) for i in range(len(factor_cols))}

    fitted = X_design @ coefs
    resid = excess - fitted
    n, k = X_design.shape
    if n - k < 1:
        return None
    sigma2 = float((resid @ resid) / (n - k))
    XtX_inv = np.linalg.pinv(X_design.T @ X_design)
    var_coefs = sigma2 * np.diag(XtX_inv)
    se = np.sqrt(np.maximum(var_coefs, 0.0))
    alpha_tstat = float(alpha / se[0]) if se[0] > 0 else 0.0

    ss_res = float(resid @ resid)
    ss_tot = float(((excess - excess.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    raw_std = float(aligned["edge"].std())
    raw_sharpe = float(aligned["edge"].mean() / raw_std * np.sqrt(252)) if raw_std > 0 else 0.0

    return FactorDecomp(
        edge=edge_name,
        n_obs=len(aligned),
        raw_sharpe=raw_sharpe,
        alpha_daily=alpha,
        alpha_annualized=alpha * 252,
        alpha_tstat=alpha_tstat,
        r_squared=r2,
        betas=betas,
    )


# ---------------------------------------------------------------------------
# Gate 6 helper — used by Discovery's validate_candidate
# ---------------------------------------------------------------------------

def gate_factor_alpha(
    decomp: Optional[FactorDecomp],
    alpha_tstat_min: float = DEFAULT_ALPHA_TSTAT_MIN,
    alpha_annual_min: float = DEFAULT_ALPHA_ANNUAL_MIN,
) -> tuple[bool, str]:
    """Gate 6 decision: does the edge produce statistically and economically
    significant alpha vs FF5 + Mom?

    Returns (passed, reason). Reasons are short strings suitable for log
    output. Special-cases:
      - decomp is None: insufficient data → passed=True (don't penalize
        candidates that simply don't have enough observations yet — they
        get vetted by other gates and BY this one once they accumulate
        history). Reason "skipped: insufficient data".
      - alpha_tstat NOT > min: failed.
      - alpha_annualized NOT > min: failed (real but economically tiny).
    """
    if decomp is None:
        return (True, "skipped: insufficient data")
    if decomp.alpha_tstat <= alpha_tstat_min:
        return (
            False,
            f"alpha t-stat {decomp.alpha_tstat:+.2f} <= {alpha_tstat_min}",
        )
    if decomp.alpha_annualized <= alpha_annual_min:
        return (
            False,
            f"alpha {100 * decomp.alpha_annualized:+.1f}% <= {100 * alpha_annual_min:.1f}%",
        )
    return (
        True,
        f"alpha {100 * decomp.alpha_annualized:+.1f}% (t={decomp.alpha_tstat:+.2f})",
    )


__all__ = [
    "FactorDecomp",
    "load_factor_data",
    "regress_returns_on_factors",
    "gate_factor_alpha",
    "DEFAULT_FACTOR_COLS",
    "DEFAULT_ALPHA_TSTAT_MIN",
    "DEFAULT_ALPHA_ANNUAL_MIN",
    "DEFAULT_MIN_OBSERVATIONS",
    "FF5_CACHE",
    "MOM_CACHE",
]
