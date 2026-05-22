import pandas as pd
import numpy as np
import logging
from datetime import date as _date
from typing import Any, Dict, List, Optional, Tuple
from ta.trend import SMAIndicator, EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange, BollingerBands

logger = logging.getLogger("FEATURE_ENG")


# ----------------------------------------------------------------------
# Fundamentals-percentile vocabulary (Change 2 of T-2026-05-08-006).
# These are the V/Q/A factor columns the SimFin adapter publishes via
# `engines/data_manager/fundamentals/simfin_adapter.py`. Any of these
# present in the cross-sectional input DataFrame gets a corresponding
# `XS_<PrettyName>_Pctile` column. Adding a new factor here is the only
# step needed to expose it to Discovery.
# ----------------------------------------------------------------------
_FUNDAMENTALS_COLUMNS: Tuple[str, ...] = (
    "earnings_yield_book",
    "book_to_assets",
    "roe",
    "roa",
    "gross_margin",
    "gross_profitability",
    "sloan_accruals",
    "asset_growth",
    # Price-relative valuation ratios — present when the caller has
    # joined a price-aware ratio onto the panel.
    "pe_ratio",
    "pb_ratio",
    "book_to_market",
    "earnings_yield_market",
)

# Acronyms preserved as upper-case in the pretty name (for column
# legibility — `XS_ROE_Pctile` reads cleaner than `XS_Roe_Pctile`).
_FUND_ACRONYMS = {"PE", "PB", "PS", "ROE", "ROA", "ROIC", "EPS",
                  "EBIT", "EBITDA", "EV", "FCF"}


def _pretty_fund_col(col: str) -> str:
    """`pe_ratio` -> `PE_Ratio`; `book_to_market` -> `Book_To_Market`."""
    return "_".join(
        p.upper() if p.upper() in _FUND_ACRONYMS else p.capitalize()
        for p in col.split("_")
    )


# Programmer-error exceptions that MUST propagate from a Foundry feature
# evaluation. Same set the gauntlet narrow-catch (commits 453e04e,
# ee42ab7) and the backtest_controller fix (T-2026-05-08-005, commit
# 129c7ba) re-raise. A Foundry feature that raises any of these has a
# bug — silently treating it as "no data" hides interface drift.
_FOUNDRY_PROGRAMMER_ERRORS: Tuple[type, ...] = (
    TypeError, AttributeError, NameError, AssertionError, ImportError,
)


# Module-level singleton flag — force-import the Foundry features
# package exactly once per process so all `@feature` decorators
# self-register before TreeScanner asks for the registry. Wrapped in
# a function (not a top-level import) so a missing optional dependency
# during ad-hoc unit tests degrades to "no Foundry features available"
# instead of import-failing the whole module.
_FOUNDRY_FEATURES_IMPORTED = False


# ----------------------------------------------------------------------
# Foundry vectorization caches (T-2026-05-08-013).
#
# TreeScanner's production call path iterates ~109 tickers and invokes
# `compute_all_features(..., ticker=T)` per ticker. Inside, every
# tier-A/B Foundry feature is evaluated on the (T, date_seq) grid. A
# subset of features (calendar, FRED-macro, market-wide cross-asset)
# return values that are FUNCTIONS OF DATE ONLY — calling them per
# ticker re-does identical work N times. The cache below classifies
# features empirically once-per-process and memoizes their per-date
# values so the second-through-Nth ticker hits the cache.
#
# Memory bound: ~8 ticker-independent features × ~2000 trading dates
# = ~16K entries × 24 bytes/entry ≈ 400 KB. Trivial.
#
# Concurrency: Engine D is single-threaded; no locking needed.
#
# Test interaction: the autouse `reset_registries` fixture in
# `tests/test_feature_foundry.py` clears the FeatureRegistry but NOT
# these caches. That's intentional — the caches are keyed by
# (feature_id, date) and the feature_ids are stable across the
# fixture's snapshot/clear/restore. Tests that change feature
# semantics under the same id should call `_clear_foundry_caches()`
# explicitly.
# ----------------------------------------------------------------------
_FOUNDRY_TICKER_INDEPENDENCE: Dict[str, bool] = {}
_FOUNDRY_TICKER_INDEPENDENT_VALUE_CACHE: Dict[Tuple[str, _date], Any] = {}

# Sentinel for "cache miss" — distinguishes from a legitimately-cached
# `None` (which itself means "feature returned None for this date").
# Using a plain object lets us write `if cached is _CACHE_MISS` without
# colliding with any value the feature could legitimately return.
_CACHE_MISS = object()

# Synthetic ticker names used for the empirical classification probe.
# They MUST NOT correspond to any real ticker in `data/processed/` so
# `local_ohlcv`-backed features return None for both samples (which
# means the feature gets safely classified as ticker-DEPENDENT — the
# correctness-preserving default).
_FOUNDRY_PROBE_TICKER_A = "__FOUNDRY_PROBE_AAA__"
_FOUNDRY_PROBE_TICKER_B = "__FOUNDRY_PROBE_BBB__"

# Three sample dates spanning a year, biased toward weekdays. If a
# feature returns the SAME non-None value for both probe tickers on
# AT LEAST ONE of these dates, it's classified as ticker-independent.
_FOUNDRY_PROBE_DATES: Tuple[_date, ...] = (
    _date(2024, 1, 2),
    _date(2024, 6, 17),
    _date(2024, 12, 30),
)


def _classify_feature_ticker_independence(feat) -> bool:
    """Determine whether a Foundry feature is ticker-independent.
    Cached after first call.

    Two paths in priority order:

    1. **Explicit declaration** (T-2026-05-12-038-CONT): if the
       `@feature(..., ticker_independent=True)` decorator field is set,
       trust it without an empirical probe. This is the correct path for
       universe-wide features (`correlation_average_60d`,
       `dispersion_60d`, etc.) that return None for synthetic probe
       tickers and would otherwise be misclassified as ticker-dependent.

    2. **Empirical probe** (T-2026-05-08-013, original): feature is
       ticker-independent iff `feat.func(ticker, dt)` returns the same
       non-None value for two distinct synthetic tickers on at least one
       of `_FOUNDRY_PROBE_DATES`. This catches calendar / macro features
       that don't depend on ticker; it safely rejects `local_ohlcv`-
       backed features that return None for synthetic tickers.

    Path 2 is the SAFE DEFAULT: a feature missing the explicit
    annotation falls back to the empirical probe, preserving pre-
    T-038-CONT behavior for every feature except those newly annotated.
    """
    fid = feat.feature_id
    if fid in _FOUNDRY_TICKER_INDEPENDENCE:
        return _FOUNDRY_TICKER_INDEPENDENCE[fid]

    # Path 1: trust the explicit decorator field when present.
    if getattr(feat, "ticker_independent", False):
        _FOUNDRY_TICKER_INDEPENDENCE[fid] = True
        return True

    # Path 2: empirical probe (pre-T-038-CONT behavior).
    func = feat.func
    independent = False
    for d in _FOUNDRY_PROBE_DATES:
        try:
            v_a = func(_FOUNDRY_PROBE_TICKER_A, d)
            v_b = func(_FOUNDRY_PROBE_TICKER_B, d)
        except Exception:
            # A probe failure is informative ("feature errors on this
            # ticker shape") but not classifying — skip and try the
            # next date. If all probes fail, the feature stays in the
            # safe default (ticker-dependent → no cache).
            continue
        if v_a is not None and v_b is not None and v_a == v_b:
            independent = True
            break
    _FOUNDRY_TICKER_INDEPENDENCE[fid] = independent
    return independent


def _clear_foundry_caches() -> None:
    """Test helper: drop both the classification map and the value
    cache. Use in tests that swap a feature's implementation under
    the same `feature_id`."""
    _FOUNDRY_TICKER_INDEPENDENCE.clear()
    _FOUNDRY_TICKER_INDEPENDENT_VALUE_CACHE.clear()


def _ensure_foundry_features_loaded() -> bool:
    """Force-import the Foundry features package on first call. Returns
    True if the registry is usable, False if the import failed (in which
    case Engine D continues with the technical-only vocabulary).
    """
    global _FOUNDRY_FEATURES_IMPORTED
    if _FOUNDRY_FEATURES_IMPORTED:
        return True
    try:
        import core.feature_foundry.features  # noqa: F401  trigger self-register
        _FOUNDRY_FEATURES_IMPORTED = True
        return True
    except Exception as exc:
        logger.warning(
            "[FEATURE_ENG] Foundry features unavailable; "
            "Engine D running on technical-only vocabulary: %s: %s",
            type(exc).__name__, exc,
        )
        return False

class FeatureEngineer:
    """
    Tier 1 Research Feature Factory.

    Responsibility:
    ---------------
    Takes Raw Data (OHLCV + Fundamentals) -> Returns 'Huntable' Feature Matrix.

    Architecture:
    -------------
    - Modular 'Aspects': Trend, Volatility, Fundamental, Relative,
      Calendar, Microstructure, Inter-Market, Regime Context.
    - Consistency: Same logic for Backtest (Training) and Live (Inference).
    - Caching: Computed features saved to Parquet to speed up ML training.
    """

    def __init__(self):
        # Force-import the Foundry features package so all `@feature`
        # decorators self-register before any TreeScanner consumer asks
        # the registry for them. Idempotent (singleton flag); safe if
        # the autouse `reset_registries` test fixture in
        # `tests/test_feature_foundry.py` snapshots the registry before
        # a test clears it, because the modules stay in `sys.modules`
        # and the snapshot captures the registered features at fixture
        # entry.
        _ensure_foundry_features_loaded()

    def compute_all_features(
        self,
        ohlc_df: pd.DataFrame,
        fund_df: pd.DataFrame,
        spy_df: Optional[pd.DataFrame] = None,
        tlt_df: Optional[pd.DataFrame] = None,
        gld_df: Optional[pd.DataFrame] = None,
        regime_meta: Optional[Dict] = None,
        ticker: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Master factory method. Computes all feature blocks and returns a unified DataFrame.

        ``ticker`` (additive in T-2026-05-08-006) is the symbol the
        ohlc_df belongs to. When provided, every tier-A and tier-B
        Foundry feature is evaluated on the (ticker, date) grid and
        added as ``Foundry_<feature_id>`` columns. When ``None`` the
        Foundry pass is skipped — preserves backward-compat for
        callers that don't yet thread the ticker through.

        T-054c (2026-05-12): when ticker is None we emit a one-shot
        WARNING via stdlib warnings.warn (DeprecationWarning category).
        This makes the "silent Foundry skip" LOUD per the T-034
        fail-loud-not-silent pattern, preventing future sibling bugs
        like T-054 (discovery.py:135) and T-054b (rule_based_edge.py:137
        + scripts/run_shadow_paper.py:86) where production callers
        accidentally omitted ticker= and saw foundry_feature columns
        silently disappear for months. Tests + __main__ demos may pass
        ticker=None intentionally; they'll see the warning but otherwise
        function unchanged.
        """
        if ohlc_df.empty:
            return pd.DataFrame()
        if ticker is None:
            import warnings
            warnings.warn(
                "FeatureEngineer.compute_all_features called with ticker=None. "
                "The Foundry pass will be SKIPPED — no Foundry_<feature_id> columns "
                "will be added. If your caller is production code (not a test or "
                "__main__ demo), this is almost certainly a bug — see T-054 / T-054b "
                "for the prior sibling-bug class. Pass ticker= explicitly to silence "
                "this warning and populate Foundry features.",
                DeprecationWarning,
                stacklevel=2,
            )

        # 1. Technical (Trend/Momentum/Volatility)
        df = self._compute_technicals(ohlc_df.copy())

        # 2. Fundamentals (Valuation/Growth)
        if not fund_df.empty:
            df = df.join(fund_df, how="left")

        # 3. Relative Strength (vs SPY)
        if spy_df is not None and not spy_df.empty:
            df = self._compute_relative_strength(df, spy_df)

        # 4. Calendar / Seasonality
        df = self._compute_calendar_features(df)

        # 5. Microstructure
        df = self._compute_microstructure_features(df)

        # 6. Inter-Market
        df = self._compute_intermarket_features(df, spy_df, tlt_df, gld_df)

        # 7. Regime Context
        if regime_meta:
            df = self._compute_regime_features(df, regime_meta)

        # 8. Foundry features — point-evaluations from the
        # `core.feature_foundry` registry. Vocabulary expansion;
        # Discovery TreeScanner consumes whatever columns we provide.
        if ticker:
            df = self._compute_foundry_features(df, ticker)

        # Cleanup (Inf, NaN)
        df = df.replace([np.inf, -np.inf], np.nan)
        df = df.ffill()

        return df

    # ------------------------------------------------------------------
    # Foundry Features (point-evaluations on per-ticker per-date grid)
    # ------------------------------------------------------------------

    def _compute_foundry_features(self, df: pd.DataFrame, ticker: str) -> pd.DataFrame:
        """Evaluate every tier-A and tier-B Foundry feature for ``ticker``
        across ``df.index`` and append columns prefixed ``Foundry_``.

        Skipped tiers: ``adversarial`` (auto-generated permuted twins —
        not vocabulary, only used by the leakage detector).

        Per-feature failure modes:
          - feature returns ``None``: column gets ``NaN`` for that bar.
          - feature raises a programmer error (TypeError, AttributeError,
            NameError, AssertionError, ImportError): re-raise. Same
            policy as `_fundamentals_helpers._PROGRAMMER_ERRORS` — these
            are bugs, not missing data.
          - feature raises any other Exception: column gets ``NaN`` for
            that bar; logged at DEBUG so audits surface unexpected
            swallowing.
        """
        if not isinstance(df.index, pd.DatetimeIndex):
            return df

        if not _ensure_foundry_features_loaded():
            return df

        # Local import — avoids a circular import at module load time
        # if the test harness arranges modules in unusual order.
        from core.feature_foundry import get_feature_registry

        registry = get_feature_registry()
        feats = [
            f for f in registry.list_features()
            if f.tier in ("A", "B")  # skip "adversarial"
        ]

        # Pre-extract the date sequence once. Foundry features expect
        # `datetime.date`; df.index is `Timestamp` so we map upfront.
        date_seq = [
            (d.date() if hasattr(d, "date") else d) for d in df.index
        ]

        for feat in feats:
            col_name = f"Foundry_{feat.feature_id}"
            # Pull `func` and `feature_id` out of the inner loop so we
            # don't pay attribute-lookup cost per-bar.
            func = feat.func
            fid = feat.feature_id
            ticker_independent = _classify_feature_ticker_independence(feat)
            values: List[float] = []
            for dt in date_seq:
                # ticker-independent path: hit the per-process cache
                # keyed by (fid, dt) — second+ ticker calls hit this
                # for calendar / FRED-macro / market-wide features.
                if ticker_independent:
                    cache_key = (fid, dt)
                    cached = _FOUNDRY_TICKER_INDEPENDENT_VALUE_CACHE.get(
                        cache_key, _CACHE_MISS,
                    )
                    if cached is not _CACHE_MISS:
                        v = cached
                    else:
                        try:
                            v = func(ticker, dt)
                        except _FOUNDRY_PROGRAMMER_ERRORS:
                            raise
                        except Exception as exc:
                            logger.debug(
                                "[FEATURE_ENG] Foundry feature %r dropped %s @ %s: %s: %s",
                                fid, ticker, dt,
                                type(exc).__name__, exc,
                            )
                            v = None
                        _FOUNDRY_TICKER_INDEPENDENT_VALUE_CACHE[cache_key] = v
                else:
                    # ticker-dependent path: scalar call (no cache —
                    # would explode in size on a 109-ticker universe).
                    try:
                        v = func(ticker, dt)
                    except _FOUNDRY_PROGRAMMER_ERRORS:
                        raise
                    except Exception as exc:
                        logger.debug(
                            "[FEATURE_ENG] Foundry feature %r dropped %s @ %s: %s: %s",
                            fid, ticker, dt,
                            type(exc).__name__, exc,
                        )
                        v = None
                if v is None:
                    values.append(np.nan)
                else:
                    try:
                        values.append(float(v))
                    except (TypeError, ValueError):
                        values.append(np.nan)
            df[col_name] = values

        return df

    # ------------------------------------------------------------------
    # Cross-Sectional Features (operates on stacked multi-ticker DataFrame)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_cross_sectional_features(big_df: pd.DataFrame, ticker_col: str = "ticker") -> pd.DataFrame:
        """
        Compute cross-sectional rank features across the universe.
        Must be called AFTER per-ticker features are computed and concatenated.

        Adds percentile ranks for momentum, volume, and (when present in
        the input frame) the V/Q/A fundamentals factors. New in
        T-2026-05-08-006: any column from `_FUNDAMENTALS_COLUMNS`
        present in `big_df` gets a corresponding `XS_<PrettyName>_Pctile`.
        Caller is responsible for PIT-aligned fundamentals — convention
        established in `engines/engine_a_alpha/edges/_fundamentals_helpers.py`.
        """
        if big_df.empty or ticker_col not in big_df.columns:
            return big_df

        df = big_df.copy()

        # Need a date column for grouping — use index if DatetimeIndex, else try "Date"
        if isinstance(df.index, pd.DatetimeIndex):
            df["_date"] = df.index
        elif "Date" in df.columns:
            df["_date"] = df["Date"]
        else:
            # No date column — can't do cross-sectional ranking
            return big_df

        # Features to rank cross-sectionally
        rank_targets = {}

        # Momentum ranks
        if "Close" in df.columns:
            df["ROC_20"] = df.groupby(ticker_col)["Close"].pct_change(20)
            df["ROC_60"] = df.groupby(ticker_col)["Close"].pct_change(60)
            rank_targets["ROC_20"] = "XS_Mom_20_Pctile"
            rank_targets["ROC_60"] = "XS_Mom_60_Pctile"

        if "Vol_ZScore" in df.columns:
            rank_targets["Vol_ZScore"] = "XS_VolZ_Pctile"

        if "RS_3M" in df.columns:
            rank_targets["RS_3M"] = "XS_RS3M_Pctile"

        if "ATR_Pct" in df.columns:
            rank_targets["ATR_Pct"] = "XS_ATR_Pctile"

        # Fundamentals percentile ranks — V/Q/A factor vocabulary.
        # Only columns actually present in the input frame are added.
        for fund_col in _FUNDAMENTALS_COLUMNS:
            if fund_col in df.columns:
                rank_targets[fund_col] = f"XS_{_pretty_fund_col(fund_col)}_Pctile"

        # Compute percentile ranks within each date
        for src_col, dst_col in rank_targets.items():
            if src_col in df.columns:
                df[dst_col] = df.groupby("_date")[src_col].rank(pct=True)

        df.drop(columns=["_date"], inplace=True)
        return df

    # ------------------------------------------------------------------
    # Technical Features (existing — unchanged)
    # ------------------------------------------------------------------

    def _compute_technicals(self, df: pd.DataFrame) -> pd.DataFrame:
        if not all(col in df.columns for col in ["Open", "High", "Low", "Close", "Volume"]):
            return df

        # --- Trend ---
        df["SMA_50"] = SMAIndicator(close=df["Close"], window=50).sma_indicator()
        df["SMA_200"] = SMAIndicator(close=df["Close"], window=200).sma_indicator()
        df["EMA_20"] = EMAIndicator(close=df["Close"], window=20).ema_indicator()

        df["Dist_SMA200"] = (df["Close"] - df["SMA_200"]) / df["SMA_200"]

        df["Above_SMA200"] = (df["Close"] > df["SMA_200"]).astype(int)
        df["Golden_Cross"] = (df["SMA_50"] > df["SMA_200"]).astype(int)

        # --- Momentum ---
        df["RSI_14"] = RSIIndicator(close=df["Close"], window=14).rsi()

        macd = MACD(close=df["Close"])
        df["MACD"] = macd.macd()
        df["MACD_Hist"] = macd.macd_diff()
        df["MACD_Signal"] = macd.macd_signal()

        adx = ADXIndicator(high=df["High"], low=df["Low"], close=df["Close"], window=14)
        df["ADX"] = adx.adx()

        # --- Volatility ---
        atr_ind = AverageTrueRange(high=df["High"], low=df["Low"], close=df["Close"], window=14)
        atr_val = atr_ind.average_true_range()
        df["ATR_Pct"] = atr_val / df["Close"]

        bb = BollingerBands(close=df["Close"], window=20, window_dev=2)
        upper = bb.bollinger_hband()
        lower = bb.bollinger_lband()
        mid = bb.bollinger_mavg()

        df["BB_Width"] = (upper - lower) / mid
        df["BB_Squeeze"] = (df["BB_Width"] < 0.05).astype(int)

        vol_mean = df["Volume"].rolling(20).mean()
        vol_std = df["Volume"].rolling(20).std()
        df["Vol_ZScore"] = (df["Volume"] - vol_mean) / (vol_std + 1e-9)

        return df

    # ------------------------------------------------------------------
    # Relative Strength (existing — unchanged)
    # ------------------------------------------------------------------

    def _compute_relative_strength(self, df: pd.DataFrame, spy_df: pd.DataFrame) -> pd.DataFrame:
        spy_aligned = spy_df["Close"].reindex(df.index).ffill()

        ratio = df["Close"] / spy_aligned

        df["RS_3M"] = ratio.pct_change(63)

        rs_sma50 = ratio.rolling(50).mean()
        df["RS_Strong"] = (ratio > rs_sma50).astype(int)

        return df

    # ------------------------------------------------------------------
    # Calendar / Seasonality Features
    # ------------------------------------------------------------------

    def _compute_calendar_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Pure calendar-derived features. No external data required.
        Uses cyclical encoding (sin/cos) to preserve circular relationships.
        """
        idx = df.index
        if not isinstance(idx, pd.DatetimeIndex):
            return df

        # Day of week: cyclical sin/cos (Monday=0, Friday=4)
        dow = idx.dayofweek.astype(float)
        df["DOW_Sin"] = np.sin(2 * np.pi * dow / 5.0)
        df["DOW_Cos"] = np.cos(2 * np.pi * dow / 5.0)

        # Month of year: cyclical sin/cos
        month = idx.month.astype(float)
        df["Month_Sin"] = np.sin(2 * np.pi * month / 12.0)
        df["Month_Cos"] = np.cos(2 * np.pi * month / 12.0)

        # Quarter-end proximity: trading days until next quarter end
        def _days_to_quarter_end(dt):
            q_month = ((dt.month - 1) // 3 + 1) * 3
            q_year = dt.year
            if q_month > 12:
                q_month = 3
                q_year += 1
            q_end = pd.Timestamp(year=q_year, month=q_month, day=1) + pd.offsets.MonthEnd(0)
            delta = np.busday_count(dt.date(), q_end.date())
            return max(delta, 0)

        df["QEnd_Proximity"] = pd.Series(
            [_days_to_quarter_end(dt) for dt in idx], index=idx, dtype=float
        )

        # Options expiration proximity: days to next third Friday
        def _days_to_opex(dt):
            """Find next third Friday of the month (options expiration)."""
            year, month = dt.year, dt.month
            # Third Friday: first day of month, advance to Friday, then add 2 weeks
            first = pd.Timestamp(year=year, month=month, day=1)
            # Days until Friday (Friday = 4)
            days_to_friday = (4 - first.dayofweek) % 7
            third_friday = first + pd.Timedelta(days=days_to_friday + 14)
            if dt.date() > third_friday.date():
                # Move to next month
                if month == 12:
                    year, month = year + 1, 1
                else:
                    month += 1
                first = pd.Timestamp(year=year, month=month, day=1)
                days_to_friday = (4 - first.dayofweek) % 7
                third_friday = first + pd.Timedelta(days=days_to_friday + 14)
            delta = np.busday_count(dt.date(), third_friday.date())
            return max(delta, 0)

        df["OpEx_Proximity"] = pd.Series(
            [_days_to_opex(dt) for dt in idx], index=idx, dtype=float
        )

        return df

    # ------------------------------------------------------------------
    # Microstructure Features
    # ------------------------------------------------------------------

    def _compute_microstructure_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Price-action microstructure derived from OHLCV.
        """
        if not all(col in df.columns for col in ["Open", "High", "Low", "Close"]):
            return df

        # Overnight gap: (Open_t - Close_{t-1}) / Close_{t-1}
        df["Overnight_Gap"] = (df["Open"] - df["Close"].shift(1)) / (df["Close"].shift(1) + 1e-9)

        # Intraday range: (High - Low) / Close
        df["Intraday_Range"] = (df["High"] - df["Low"]) / (df["Close"] + 1e-9)

        # Close location within bar: (Close - Low) / (High - Low)
        # 1.0 = closed at high, 0.0 = closed at low
        bar_range = df["High"] - df["Low"]
        df["Close_Location"] = (df["Close"] - df["Low"]) / (bar_range + 1e-9)
        df["Close_Location"] = df["Close_Location"].clip(0.0, 1.0)

        # Gap fill indicator: did the overnight gap get filled by the close?
        # Gap up filled: Open > prev_Close but Close <= prev_Close
        # Gap down filled: Open < prev_Close but Close >= prev_Close
        prev_close = df["Close"].shift(1)
        gap_up = df["Open"] > prev_close
        gap_dn = df["Open"] < prev_close
        filled_up = gap_up & (df["Low"] <= prev_close)  # price came back down to fill
        filled_dn = gap_dn & (df["High"] >= prev_close)  # price came back up to fill
        df["Gap_Filled"] = (filled_up | filled_dn).astype(int)

        return df

    # ------------------------------------------------------------------
    # Inter-Market Features
    # ------------------------------------------------------------------

    def _compute_intermarket_features(
        self,
        df: pd.DataFrame,
        spy_df: Optional[pd.DataFrame] = None,
        tlt_df: Optional[pd.DataFrame] = None,
        gld_df: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """
        Cross-asset features: SPY/TLT/GLD returns and correlations.
        Gracefully degrades when data is unavailable.
        """
        if spy_df is not None and not spy_df.empty and "Close" in spy_df.columns:
            spy_close = spy_df["Close"].reindex(df.index).ffill()
            spy_ret = spy_close.pct_change()
            df["SPY_Ret_5d"] = spy_ret.rolling(5).sum()
            df["SPY_Ret_20d"] = spy_ret.rolling(20).sum()

        if tlt_df is not None and not tlt_df.empty and "Close" in tlt_df.columns:
            tlt_close = tlt_df["Close"].reindex(df.index).ffill()
            tlt_ret = tlt_close.pct_change()
            df["TLT_Ret_5d"] = tlt_ret.rolling(5).sum()

            # SPY-TLT rolling correlation (60-bar)
            if "SPY_Ret_5d" in df.columns and spy_df is not None:
                spy_ret = spy_df["Close"].reindex(df.index).ffill().pct_change()
                df["SPY_TLT_Corr_60"] = spy_ret.rolling(60).corr(tlt_ret)

        if gld_df is not None and not gld_df.empty and "Close" in gld_df.columns:
            gld_close = gld_df["Close"].reindex(df.index).ffill()
            gld_ret = gld_close.pct_change()
            df["GLD_Ret_5d"] = gld_ret.rolling(5).sum()

            # SPY-GLD rolling correlation (60-bar)
            if spy_df is not None and not spy_df.empty:
                spy_ret = spy_df["Close"].reindex(df.index).ffill().pct_change()
                df["SPY_GLD_Corr_60"] = spy_ret.rolling(60).corr(gld_ret)

        return df

    # ------------------------------------------------------------------
    # Regime Context Features
    # ------------------------------------------------------------------

    def _compute_regime_features(self, df: pd.DataFrame, regime_meta: Dict) -> pd.DataFrame:
        """
        Convert Engine E's regime state dict into numeric features.
        These are constant across the DataFrame (same regime for all bars in a batch).
        For bar-by-bar regime, the caller should pass per-bar regime_meta.
        """
        # Trend state — prefer the structured `trend_regime["state"]` (5-axis
        # output from regime_detector.detect_regime), fall back to the top-level
        # backward-compat key.  Bull/bear/range labels live here.
        trend = (regime_meta.get("trend_regime") or {}).get("state") \
            or regime_meta.get("trend", "unknown")
        df["Regime_Bull"] = int(trend == "bull")
        df["Regime_Bear"] = int(trend == "bear")
        df["Regime_Range"] = int(trend == "range")

        # Volatility state — same shape rules as trend.
        vol = (regime_meta.get("volatility_regime") or {}).get("state") \
            or regime_meta.get("volatility", "unknown")
        df["Regime_VolHigh"] = int(vol in ("high", "shock"))
        df["Regime_VolLow"] = int(vol == "low")

        # Correlation state — only exists nested under `correlation_regime`;
        # there is no top-level `"correlation"` backward-compat key.  The prior
        # code read the missing key and silently set Regime_CorrSpike=0 for
        # every bar of every TreeScanner hunt.
        corr = (regime_meta.get("correlation_regime") or {}).get("state", "unknown")
        df["Regime_CorrSpike"] = int(corr in ("spike", "elevated"))

        # Composite scores
        df["Regime_Stability"] = float(regime_meta.get("regime_stability", 0.5))
        df["Regime_TransRisk"] = float(regime_meta.get("transition_risk", 0.0))

        # Advisory risk scalar
        advisory = regime_meta.get("advisory", {})
        df["Regime_RiskScalar"] = float(advisory.get("risk_scalar", 1.0))

        return df


if __name__ == "__main__":
    # POC Test
    print("Testing Feature Engineer...")
    dates = pd.date_range("2023-01-01", periods=300, freq="B")
    data = {"Close": np.random.normal(100, 5, 300).cumsum().clip(50, 200),
            "Open": np.random.normal(100, 5, 300).cumsum().clip(50, 200),
            "High": np.random.normal(102, 5, 300).cumsum().clip(50, 200),
            "Low": np.random.normal(98, 5, 300).cumsum().clip(50, 200),
            "Volume": np.random.randint(1000, 10000, 300)}
    df = pd.DataFrame(data, index=dates)

    fe = FeatureEngineer()
    res = fe.compute_all_features(df, pd.DataFrame())
    print(f"Feature count: {len(res.columns)}")
    print(res.tail().T)
