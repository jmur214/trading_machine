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

# VIX term-structure features (slice 1 of the regime-engine input panel
# rebuild — added 2026-05-06). These are forward-looking by construction:
# market-implied vol expectations across short/medium/long horizons are
# leading signals of realized drawdowns (Lai 2022; CBOE term-structure
# backwardation is the canonical "fear is concentrated NOW" signature).
#
# Slope construction notes:
#   - vix_term_spread (vix3m − vix): positive in contango (normal), negative
#     in backwardation (fear is concentrated near-term). Matches the
#     economic interpretation already used in forward_stress_detector.py.
#   - vix9d_over_vix_ratio_minus1 (vix9d/vix − 1): >0 when 9-day implied
#     vol exceeds 30-day, sharper near-term backwardation signal. Centered
#     at zero so HMM Gaussian emissions stay well-conditioned.
#   - vix_zscore_60d: level-normalized VIX over trailing 60 trading days.
#     Decouples regime-current stress from absolute VIX level (e.g. 20 in
#     2017 = elevated; 20 in 2022 = subdued).
#
# Sources: ^VIX9D / ^VIX / ^VIX3M from yfinance, cached to data/macro/
# via scripts/fetch_vix_term_structure.py.
VIX_TERM_FEATURES = [
    "vix_term_spread",          # vix3m - vix  (negative = backwardation)
    "vix9d_over_vix_ratio_minus1",  # vix9d/vix - 1 (positive = near-term spike)
    "vix_zscore_60d",           # 60d trailing z-score of VIX level
]

# E-rebuild phase-1 features (added 2026-05-07). Three candidate leading
# indicators behind opt-in flags so the default 7-feature HMM stays
# bit-identical:
#
#   - hyg_ig_oas: HY OAS minus IG OAS (FRED BAMLH0A0HYM2 - BAMLC0A0CM).
#     Credit-quality slope; widens before risk-off events. **Caveat:**
#     ICE BofA shortened the freely-available FRED series in mid-2023, so
#     this feature is bounded by ~2023-05 onward and CANNOT cover the 2022
#     bear or earlier crises. Pre-2023 history would require a paid data
#     source.
#
#   - copper_gold_ratio: Copper futures / Gold futures (HG=F / GC=F),
#     log-transformed and 63d-changed. Industrial cycle vs monetary/risk-off;
#     classic intermarket leading signal — inverts at growth inflection
#     points 6-12 months ahead of equity drawdowns.
#
#   - xlp_xly_ratio: log(Consumer Staples ETF) / log(Consumer Discretionary
#     ETF), 63d-changed. Defensive-vs-cyclical sector relative strength.
#     Rotation INTO XLP precedes broader market drawdowns.
#
# yfinance source for HG=F / GC=F / XLP / XLY; cached via
# scripts/fetch_leading_indicators.py.
HYG_IG_FEATURES = ["hyg_ig_oas"]
LEADING_RS_FEATURES = ["copper_gold_ratio", "xlp_xly_ratio"]

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
    include_vix_term: bool = False,
    include_hyg_ig: bool = False,
    include_leading_rs: bool = False,
) -> pd.DataFrame:
    """Build the daily feature panel for HMM regime detection.

    Args:
        root: Repo root (auto-detect if None).
        start / end: Optional date bounds. If None, returns full available range.
        include_aux: If True, include auxiliary columns (real_rate_level,
            unemployment_momentum_3m, etc.) for downstream consumers.
        include_vix_term: If True, append VIX_TERM_FEATURES to the panel.
            Requires data/macro/{VIX9D,VIX,VIX3M}.parquet.
        include_hyg_ig: If True, append HYG_IG_FEATURES (hyg_ig_oas) to
            the panel. Requires BAMLH0A0HYM2 + BAMLC0A0CM in data/macro/.
            History is ~2023-05+ only on the free FRED tier.
        include_leading_rs: If True, append LEADING_RS_FEATURES
            (copper_gold_ratio, xlp_xly_ratio). Requires
            data/macro/{HG_F,GC_F,XLP,XLY}.parquet (fetched via
            scripts/fetch_leading_indicators.py).

    Returns:
        DataFrame indexed by daily date. Columns = FEATURE_COLUMNS
        [+ VIX_TERM_FEATURES] [+ HYG_IG_FEATURES] [+ LEADING_RS_FEATURES]
        [+ AUX_COLUMNS]. Rows with insufficient history will contain NaN
        values; callers (HMMRegimeClassifier) handle NaN gracefully.
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

    # --- VIX term-structure series (yfinance-cached, parquet shape matches
    # FRED parquet schema so _safe_load_fred is reusable).
    vix9d = _safe_load_fred("VIX9D") if include_vix_term else None
    vix_yf = _safe_load_fred("VIX") if include_vix_term else None
    vix3m = _safe_load_fred("VIX3M") if include_vix_term else None

    # --- E-rebuild phase-1: HY-IG OAS spread + intermarket leading RS ---
    hy_oas = _safe_load_fred("BAMLH0A0HYM2") if include_hyg_ig else None
    ig_oas = _safe_load_fred("BAMLC0A0CM") if include_hyg_ig else None
    copper = _safe_load_fred("HG_F") if include_leading_rs else None
    gold = _safe_load_fred("GC_F") if include_leading_rs else None
    xlp = _safe_load_fred("XLP") if include_leading_rs else None
    xly = _safe_load_fred("XLY") if include_leading_rs else None

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

    # --- VIX term-structure columns (slice 1 of input-panel rebuild) ---
    if include_vix_term:
        # Build VIX slope/level features only when all three series are
        # present. yfinance ^VIX coverage starts ~1990, ^VIX9D from ~2011,
        # ^VIX3M from ~2008, so the joint window is ^VIX9D-limited. For our
        # 2021-2025 validation window all three are dense.
        if vix9d is not None and vix_yf is not None and vix3m is not None \
                and not vix9d.empty and not vix_yf.empty and not vix3m.empty:
            vix9d_aligned = vix9d.reindex(daily_idx, method="ffill")
            vix_aligned = vix_yf.reindex(daily_idx, method="ffill")
            vix3m_aligned = vix3m.reindex(daily_idx, method="ffill")

            # vix_term_spread = vix3m - vix.  Negative = backwardation.
            out["vix_term_spread"] = vix3m_aligned - vix_aligned

            # vix9d / vix - 1.  Positive = near-term implied vol > 30d
            # implied vol (sharper, faster backwardation signal).
            # Centered at zero; div-by-zero guarded.
            ratio = vix9d_aligned / vix_aligned.replace(0.0, np.nan)
            out["vix9d_over_vix_ratio_minus1"] = ratio - 1.0

            # 60-trading-day z-score of VIX level. Rolling mean/std over a
            # window of 60 *trading* days (~3 months) — long enough to
            # capture regime drift, short enough to keep current regime in
            # frame.
            mean60 = vix_aligned.rolling(60, min_periods=60).mean()
            std60 = vix_aligned.rolling(60, min_periods=60).std(ddof=1)
            out["vix_zscore_60d"] = (vix_aligned - mean60) / std60.replace(0.0, np.nan)
        else:
            out["vix_term_spread"] = np.nan
            out["vix9d_over_vix_ratio_minus1"] = np.nan
            out["vix_zscore_60d"] = np.nan

    # --- E-rebuild phase-1: HY-IG OAS spread (level + 60d z-score) ---
    if include_hyg_ig:
        if hy_oas is not None and ig_oas is not None and not hy_oas.empty and not ig_oas.empty:
            joined = pd.concat(
                [hy_oas.rename("hy"), ig_oas.rename("ig")], axis=1, join="inner"
            ).dropna()
            spread = (joined["hy"] - joined["ig"]).sort_index()
            # Level (in pct, like the underlying OAS series).
            out["hyg_ig_oas"] = spread.reindex(daily_idx, method="ffill")
        else:
            out["hyg_ig_oas"] = np.nan

    # --- E-rebuild phase-1: copper-gold ratio + XLP/XLY ratio ---
    # We expose 63d log-changes (3-month change) so the HMM consumes a
    # MOMENTUM signal rather than a level. Levels carry secular drift
    # (gold price doubling 2020-2024) that contaminates Gaussian emissions;
    # 63d log-changes are stationary and have the lead-time interpretation
    # required ("rotation INTO defensives over the past quarter precedes
    # broader-market drawdown").
    if include_leading_rs:
        if copper is not None and gold is not None and not copper.empty and not gold.empty:
            cu_aligned = copper.reindex(daily_idx, method="ffill")
            au_aligned = gold.reindex(daily_idx, method="ffill")
            cg_ratio = cu_aligned / au_aligned.replace(0.0, np.nan)
            out["copper_gold_ratio"] = np.log(cg_ratio).diff(63)
        else:
            out["copper_gold_ratio"] = np.nan

        if xlp is not None and xly is not None and not xlp.empty and not xly.empty:
            xlp_aligned = xlp.reindex(daily_idx, method="ffill")
            xly_aligned = xly.reindex(daily_idx, method="ffill")
            rs = xlp_aligned / xly_aligned.replace(0.0, np.nan)
            out["xlp_xly_ratio"] = np.log(rs).diff(63)
        else:
            out["xlp_xly_ratio"] = np.nan

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

    # --- Return only canonical columns (or canonical + extras) ---
    cols = list(FEATURE_COLUMNS)
    if include_vix_term:
        cols += [c for c in VIX_TERM_FEATURES if c in out.columns]
    if include_hyg_ig:
        cols += [c for c in HYG_IG_FEATURES if c in out.columns]
    if include_leading_rs:
        cols += [c for c in LEADING_RS_FEATURES if c in out.columns]
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
    # VIX term-structure features are also point-in-time levels (slope,
    # ratio, z-score); take the last observation at the window boundary.
    "vix_term_spread",
    "vix9d_over_vix_ratio_minus1",
    "vix_zscore_60d",
    # E-rebuild phase-1 features — all snapshots (level OAS, 63d log-changes).
    "hyg_ig_oas",
    "copper_gold_ratio",
    "xlp_xly_ratio",
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
