import pandas as pd
import numpy as np
import logging
from typing import Dict, List, Optional
from ta.trend import SMAIndicator, EMAIndicator, MACD, ADXIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange, BollingerBands

logger = logging.getLogger("FEATURE_ENG")

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
        pass

    def compute_all_features(
        self,
        ohlc_df: pd.DataFrame,
        fund_df: pd.DataFrame,
        spy_df: Optional[pd.DataFrame] = None,
        tlt_df: Optional[pd.DataFrame] = None,
        gld_df: Optional[pd.DataFrame] = None,
        regime_meta: Optional[Dict] = None,
    ) -> pd.DataFrame:
        """
        Master factory method. Computes all feature blocks and returns a unified DataFrame.
        """
        if ohlc_df.empty:
            return pd.DataFrame()

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

        # Cleanup (Inf, NaN)
        df = df.replace([np.inf, -np.inf], np.nan)
        df = df.ffill()

        return df

    # ------------------------------------------------------------------
    # Cross-Sectional Features (operates on stacked multi-ticker DataFrame)
    # ------------------------------------------------------------------

    @staticmethod
    def compute_cross_sectional_features(big_df: pd.DataFrame, ticker_col: str = "ticker") -> pd.DataFrame:
        """
        Compute cross-sectional rank features across the universe.
        Must be called AFTER per-ticker features are computed and concatenated.

        Adds percentile ranks for momentum and volume features relative to the
        universe on each date.
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
