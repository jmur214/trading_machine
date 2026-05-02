"""
macro_features — regime-input features for HMMRegimeClassifier.

Replaces the four macro_*_edge.py edges as architectural alpha sources.
The same FRED-derived computations they performed (BAA-AAA spread,
real rate level, dollar trend, unemployment momentum) are exposed here
as features that feed Engine E's regime detection rather than directly
generating per-ticker tilts.

This is the architectural fix called out by the 2026-05-01 reviewer:
> "Macro signals are deployed as edges, not as regime inputs.
>  Architectural mis-classification."

The four reclassified macros and their roles here:
  - BAA10Y - AAA10Y      → credit_spread_baa_aaa  (level + 5y rolling z)
  - DFII10                → real_rate_level
  - DTWEXBGS              → dollar_ret_63d  (3m return)
  - UNRATE                → unemployment_momentum_3m  (3-month change)

Plus features that were always regime inputs (yield curve, VIX, equity/
bond returns) consolidated here so the HMM has a single feature builder.

Caching: all FRED series go through MacroDataManager (data/macro/*.parquet
on the filesystem). On a fresh clone with no cache, this module returns
features as NaN rows; HMMRegimeClassifier treats NaN as low confidence.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

log = logging.getLogger("MacroFeatures")


# Canonical feature columns produced by build_feature_panel
FEATURE_COLUMNS = [
    "spy_ret_5d",
    "spy_vol_20d",
    "tlt_ret_20d",
    "vix_level",
    "yield_curve_spread",
    "credit_spread_baa_aaa",
    "dollar_ret_63d",
]

# Optional auxiliary columns (not used by default 7-feature HMM but
# computed and exposed for downstream consumers / multi-resolution
# extensions).
AUX_COLUMNS = [
    "real_rate_level",
    "unemployment_momentum_3m",
    "credit_spread_z_5y",  # rolling z-score of BAA-AAA over 5y
    "spy_log_return",
    "tlt_log_return",
]


def _safe_load_fred(series_id: str) -> Optional[pd.Series]:
    """Load a FRED series via MacroDataManager. Return None if missing."""
    try:
        from engines.data_manager import MacroDataManager
    except Exception as exc:
        log.debug(f"MacroDataManager import failed: {exc}")
        return None
    try:
        mgr = MacroDataManager()
        df = mgr.load_cached(series_id)
    except Exception as exc:
        log.debug(f"FRED cache load failed for {series_id}: {exc}")
        return None
    if df is None or df.empty:
        log.debug(f"FRED cache empty for {series_id}")
        return None

    if "value" in df.columns:
        s = df["value"].dropna()
    else:
        numeric = df.select_dtypes(include=[np.number]).columns
        if len(numeric) == 0:
            return None
        s = df[numeric[0]].dropna()
    try:
        s.index = pd.to_datetime(s.index).tz_localize(None)
    except (TypeError, AttributeError):
        try:
            s.index = pd.to_datetime(s.index)
        except Exception:
            pass
    return s.sort_index()


def _safe_load_price_csv(ticker: str, root: Path) -> Optional[pd.Series]:
    """Load Close-price column from data/processed/<ticker>_1d.csv."""
    p = root / "data" / "processed" / f"{ticker}_1d.csv"
    if not p.exists():
        log.debug(f"price csv missing: {p}")
        return None
    try:
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        if "Close" not in df.columns:
            return None
        s = df["Close"].dropna().astype(float)
        try:
            s.index = pd.to_datetime(s.index).tz_localize(None)
        except (TypeError, AttributeError):
            pass
        return s.sort_index()
    except Exception as exc:
        log.debug(f"failed to load {p}: {exc}")
        return None


def build_feature_panel(
    root: Optional[Path] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    include_aux: bool = False,
) -> pd.DataFrame:
    """Build the daily feature panel for HMM regime detection.

    Args:
        root: Repo root (auto-detect if None).
        start / end: Optional date bounds. If None, returns full available range.
        include_aux: If True, include auxiliary columns (real_rate_level,
            unemployment_momentum_3m, etc.) for downstream consumers.

    Returns:
        DataFrame indexed by daily date. Columns = FEATURE_COLUMNS [+ AUX_COLUMNS].
        Rows with insufficient history will contain NaN values; callers
        (HMMRegimeClassifier) handle NaN gracefully.
    """
    if root is None:
        root = Path(__file__).resolve().parents[2]

    # --- Equity/bond price series ---
    spy = _safe_load_price_csv("SPY", root)
    tlt = _safe_load_price_csv("TLT", root)

    # --- FRED series ---
    vix = _safe_load_fred("VIXCLS")
    t10y2y = _safe_load_fred("T10Y2Y")
    baa = _safe_load_fred("BAA10Y")
    aaa = _safe_load_fred("AAA10Y")
    dollar = _safe_load_fred("DTWEXBGS")
    real_rate = _safe_load_fred("DFII10")
    unrate = _safe_load_fred("UNRATE")

    # Build a daily index from SPY (the most reliable trading-day calendar)
    if spy is None or spy.empty:
        log.warning("SPY price series missing — feature panel will be empty")
        return pd.DataFrame(columns=FEATURE_COLUMNS)

    daily_idx = spy.index
    if start is not None:
        daily_idx = daily_idx[daily_idx >= pd.Timestamp(start)]
    if end is not None:
        daily_idx = daily_idx[daily_idx <= pd.Timestamp(end)]

    out = pd.DataFrame(index=daily_idx)

    # --- spy_ret_5d, spy_vol_20d ---
    spy_log = np.log(spy).diff()
    out["spy_log_return"] = spy_log.reindex(daily_idx)
    out["spy_ret_5d"] = spy_log.rolling(5).sum().reindex(daily_idx)
    out["spy_vol_20d"] = spy_log.rolling(20).std(ddof=0).reindex(daily_idx)

    # --- tlt_ret_20d ---
    if tlt is not None and not tlt.empty:
        tlt_log = np.log(tlt).diff()
        out["tlt_log_return"] = tlt_log.reindex(daily_idx)
        out["tlt_ret_20d"] = tlt_log.rolling(20).sum().reindex(daily_idx)
    else:
        out["tlt_log_return"] = np.nan
        out["tlt_ret_20d"] = np.nan

    # --- vix_level (FRED VIXCLS, forward-fill to daily) ---
    if vix is not None and not vix.empty:
        out["vix_level"] = vix.reindex(daily_idx, method="ffill")
    else:
        out["vix_level"] = np.nan

    # --- yield_curve_spread (FRED T10Y2Y, ffill) ---
    if t10y2y is not None and not t10y2y.empty:
        out["yield_curve_spread"] = t10y2y.reindex(daily_idx, method="ffill")
    else:
        out["yield_curve_spread"] = np.nan

    # --- credit_spread_baa_aaa (BAA10Y - AAA10Y, ffill) ---
    if baa is not None and aaa is not None and not baa.empty and not aaa.empty:
        joined = pd.concat([baa.rename("baa"), aaa.rename("aaa")], axis=1, join="inner")
        joined = joined.dropna()
        spread = (joined["baa"] - joined["aaa"]).sort_index()
        out["credit_spread_baa_aaa"] = spread.reindex(daily_idx, method="ffill")
    else:
        out["credit_spread_baa_aaa"] = np.nan

    # --- dollar_ret_63d (DTWEXBGS 3m return) ---
    if dollar is not None and not dollar.empty:
        dollar_aligned = dollar.reindex(daily_idx, method="ffill")
        out["dollar_ret_63d"] = np.log(dollar_aligned).diff(63)
    else:
        out["dollar_ret_63d"] = np.nan

    # --- Auxiliary columns ---
    if include_aux:
        # real_rate_level (DFII10)
        if real_rate is not None and not real_rate.empty:
            out["real_rate_level"] = real_rate.reindex(daily_idx, method="ffill")
        else:
            out["real_rate_level"] = np.nan

        # unemployment_momentum_3m (UNRATE 3-month change)
        if unrate is not None and not unrate.empty:
            unrate_aligned = unrate.reindex(daily_idx, method="ffill")
            out["unemployment_momentum_3m"] = unrate_aligned.diff(63)
        else:
            out["unemployment_momentum_3m"] = np.nan

        # credit_spread_z_5y (1825-day rolling z-score)
        if "credit_spread_baa_aaa" in out.columns:
            cs = out["credit_spread_baa_aaa"]
            mean_5y = cs.rolling("1825D", min_periods=252).mean()
            std_5y = cs.rolling("1825D", min_periods=252).std(ddof=0)
            out["credit_spread_z_5y"] = (cs - mean_5y) / std_5y.replace(0.0, np.nan)
        else:
            out["credit_spread_z_5y"] = np.nan

    # --- Return only canonical columns (or canonical + aux) ---
    cols = list(FEATURE_COLUMNS)
    if include_aux:
        cols += [c for c in AUX_COLUMNS if c in out.columns]
    return out[cols]


def latest_feature_row(
    panel: pd.DataFrame, as_of: pd.Timestamp
) -> Optional[pd.Series]:
    """Return the feature row at or before `as_of` (no look-ahead)."""
    if panel is None or panel.empty:
        return None
    try:
        ts = pd.Timestamp(as_of)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
    except Exception:
        return None
    valid = panel.index[panel.index <= ts]
    if len(valid) == 0:
        return None
    return panel.loc[valid[-1]]


# ----------------------------------------------------------------------
# Multi-resolution resampling (Workstream C, slice 2 — 2026-05)
# ----------------------------------------------------------------------
#
# Aggregation contract per column type:
#   - log returns (spy_log_return, tlt_log_return, spy_ret_5d, tlt_ret_20d,
#     dollar_ret_63d): SUM over the resample window (log returns are additive)
#   - realized vol (spy_vol_20d): take the LAST value at the bar boundary
#     (the rolling 20d vol snapshot at week/month end), since
#     window-summed daily-vol is not interpretable
#   - level series (vix_level, yield_curve_spread, credit_spread_baa_aaa,
#     real_rate_level, unemployment_momentum_3m, credit_spread_z_5y): take
#     the LAST value at the bar boundary
#
# Both weekly and monthly use right-anchored (label='right'), end-of-window
# stamps so the resampled bar's timestamp is the LAST trading day in the
# window — preserves no-look-ahead at inference time.

# Columns that are sums of log returns over the resample window.
_RETURN_COLUMNS = {
    "spy_log_return",
    "tlt_log_return",
}
# Columns that are point-in-time levels (take last value at window close).
_LEVEL_COLUMNS = {
    "spy_vol_20d",  # rolling-vol level snapshot
    "vix_level",
    "yield_curve_spread",
    "credit_spread_baa_aaa",
    "real_rate_level",
    "unemployment_momentum_3m",
    "credit_spread_z_5y",
    # rolling-window returns are levels too — they were already smoothed
    # at daily cadence, taking the last value at the new bar boundary
    # gives the right semantics.
    "spy_ret_5d",
    "tlt_ret_20d",
    "dollar_ret_63d",
}


def resample_feature_panel(
    daily_panel: pd.DataFrame, cadence: str
) -> pd.DataFrame:
    """Aggregate a daily feature panel to a slower cadence.

    Args:
        daily_panel: DataFrame indexed by daily date with FEATURE_COLUMNS
            (and optionally AUX_COLUMNS).
        cadence: One of {"W", "M"} — pandas resample rule. "W" yields
            week-ending bars; "M" yields month-end bars.

    Returns:
        Resampled DataFrame at the requested cadence. Bar timestamp is the
        last trading day in each window (no look-ahead).
    """
    if cadence not in ("W", "M"):
        raise ValueError(f"cadence must be 'W' or 'M', got {cadence!r}")
    if daily_panel is None or daily_panel.empty:
        return pd.DataFrame(columns=daily_panel.columns if daily_panel is not None else [])

    df = daily_panel.copy()
    df.index = pd.to_datetime(df.index)

    rule = "W-FRI" if cadence == "W" else "ME"
    resampler = df.resample(rule, label="right", closed="right")

    out = {}
    for col in df.columns:
        if col in _RETURN_COLUMNS:
            agg = resampler[col].sum(min_count=1)
        elif col in _LEVEL_COLUMNS:
            agg = resampler[col].last()
        else:
            # Unknown column — default to last (safe, level-like)
            agg = resampler[col].last()
        out[col] = agg

    result = pd.DataFrame(out)
    # Drop fully-empty rows that emerge before any source data is available
    result = result.dropna(how="all")
    # Re-stamp index to the LAST observed daily timestamp inside each
    # window — keeps inference no-look-ahead. resample(label='right')
    # uses the period boundary; we want the actual trading-day boundary.
    last_ts_per_bar = resampler.apply(
        lambda g: g.index.max() if len(g) else pd.NaT
    )
    if isinstance(last_ts_per_bar, pd.DataFrame):
        # When resampler.apply returns a DataFrame, the inner timestamps
        # appear as values — pull the first column (any column's bar
        # boundary is the same).
        last_ts_per_bar = last_ts_per_bar.iloc[:, 0]
    last_ts_per_bar = last_ts_per_bar.dropna()
    # Align result to where we have a real last-timestamp; reindex
    common = result.index.intersection(last_ts_per_bar.index)
    result = result.loc[common]
    result.index = pd.DatetimeIndex(last_ts_per_bar.loc[common].values)
    result = result.sort_index()
    return result


def build_multires_panels(
    root: Optional[Path] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    include_aux: bool = False,
) -> Dict[str, pd.DataFrame]:
    """Build daily, weekly, and monthly feature panels.

    Convenience wrapper around build_feature_panel + resample_feature_panel.

    Returns:
        {"daily": daily_panel, "weekly": weekly_panel, "monthly": monthly_panel}
    """
    daily = build_feature_panel(
        root=root, start=start, end=end, include_aux=include_aux
    )
    weekly = resample_feature_panel(daily, "W")
    monthly = resample_feature_panel(daily, "M")
    return {"daily": daily, "weekly": weekly, "monthly": monthly}
