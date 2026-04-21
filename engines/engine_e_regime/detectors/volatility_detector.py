"""
VolatilityDetector — Axis 2 of 5.

Classifies volatility regime using:
  - ATR(14) percentile rank over 252 bars
  - Yang-Zhang realized volatility (OHLC-based, ~5x more efficient than close-to-close)
  - Vol ratio (short/long): realized_vol_5bar / realized_vol_60bar as a shock leading indicator
"""

import numpy as np
import pandas as pd
from typing import Tuple

from engines.engine_e_regime.regime_config import VolatilityConfig


def _yang_zhang_vol(df: pd.DataFrame, window: int) -> pd.Series:
    """Yang-Zhang volatility estimator using OHLC data.

    Combines overnight (close-to-open), open-to-close, and Rogers-Satchell
    components for ~5x statistical efficiency over close-to-close.
    """
    log_oc = np.log(df["Open"] / df["Close"].shift(1))  # overnight
    log_co = np.log(df["Close"] / df["Open"])  # open-to-close
    log_ho = np.log(df["High"] / df["Open"])
    log_lo = np.log(df["Low"] / df["Open"])

    # Rogers-Satchell component
    rs = log_ho * (log_ho - log_co) + log_lo * (log_lo - log_co)

    # Yang-Zhang: weighted sum of overnight, close-to-open, and RS variances
    k = 0.34 / (1.34 + (window + 1) / (window - 1))
    overnight_var = log_oc.rolling(window).var()
    close_open_var = log_co.rolling(window).var()
    rs_var = rs.rolling(window).mean()

    yz_var = overnight_var + k * close_open_var + (1 - k) * rs_var
    return np.sqrt(yz_var.clip(lower=0)) * np.sqrt(252)  # annualized


class VolatilityDetector:
    """Detects volatility regime from benchmark (SPY) data.

    States: "low" | "normal" | "high" | "shock"
    """

    def __init__(self, config: VolatilityConfig = None):
        self.cfg = config or VolatilityConfig()

    def detect(self, benchmark_df: pd.DataFrame) -> Tuple[str, float, dict]:
        """Analyze benchmark DataFrame and return (state, confidence, details).

        Returns:
            (state, confidence, details) where state is "low"|"normal"|"high"|"shock".
        """
        cfg = self.cfg
        if benchmark_df.empty or len(benchmark_df) < cfg.lookback_bars:
            return ("normal", 0.3, self._empty_details())

        df = benchmark_df.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Ensure float types
        for col in ["Open", "High", "Low", "Close"]:
            df[col] = df[col].astype(float)

        # --- ATR percentile ---
        hl = df["High"] - df["Low"]
        hpc = (df["High"] - df["Close"].shift(1)).abs()
        lpc = (df["Low"] - df["Close"].shift(1)).abs()
        tr = pd.concat([hl, hpc, lpc], axis=1).max(axis=1)
        atr = tr.rolling(window=cfg.atr_window).mean()

        recent = atr.iloc[-cfg.lookback_bars:]
        current_atr = float(atr.iloc[-1])
        atr_pctile = float((recent.dropna() < current_atr).mean() * 100)

        # --- Yang-Zhang realized volatility ---
        yz_vol = _yang_zhang_vol(df, cfg.vol_long_window)
        current_yz = float(yz_vol.iloc[-1]) if not np.isnan(yz_vol.iloc[-1]) else 0.0

        # --- Vol ratio (short/long) ---
        close = df["Close"]
        log_ret = np.log(close / close.shift(1))
        vol_short = log_ret.rolling(cfg.vol_short_window).std() * np.sqrt(252)
        vol_long = log_ret.rolling(cfg.vol_long_window).std() * np.sqrt(252)

        vs = float(vol_short.iloc[-1]) if not np.isnan(vol_short.iloc[-1]) else 0.0
        vl = float(vol_long.iloc[-1]) if not np.isnan(vol_long.iloc[-1]) else 0.01
        vol_ratio = vs / (vl + 1e-9)

        # --- State classification ---
        if (
            atr_pctile > cfg.shock_percentile
            and (current_yz > cfg.shock_vol_threshold or vol_ratio > cfg.vol_ratio_shock_threshold)
        ):
            state = "shock"
        elif atr_pctile > cfg.high_percentile:
            state = "high"
        elif atr_pctile < cfg.low_percentile:
            state = "low"
        else:
            state = "normal"

        # --- Confidence ---
        # How deep into the bucket are we?
        if state == "shock":
            # Distance above shock threshold
            confidence = 0.7 + 0.25 * min((atr_pctile - cfg.shock_percentile) / 10, 1.0)
        elif state == "high":
            band = cfg.shock_percentile - cfg.high_percentile
            confidence = 0.5 + 0.4 * min((atr_pctile - cfg.high_percentile) / (band + 1e-9), 1.0)
        elif state == "low":
            confidence = 0.5 + 0.4 * min((cfg.low_percentile - atr_pctile) / (cfg.low_percentile + 1e-9), 1.0)
        else:
            # normal — confidence peaks at center of band
            center = (cfg.high_percentile + cfg.low_percentile) / 2
            dist_from_edge = min(
                atr_pctile - cfg.low_percentile,
                cfg.high_percentile - atr_pctile,
            )
            band_half = (cfg.high_percentile - cfg.low_percentile) / 2
            confidence = 0.4 + 0.5 * (dist_from_edge / (band_half + 1e-9))

        confidence = float(np.clip(confidence, 0.1, 0.95))

        details = {
            "atr": round(current_atr, 4),
            "atr_percentile": round(atr_pctile, 1),
            "yang_zhang_vol": round(current_yz, 4),
            "vol_ratio_5_60": round(vol_ratio, 3),
        }

        return (state, confidence, details)

    @staticmethod
    def _empty_details() -> dict:
        return {
            "atr": 0.0,
            "atr_percentile": 50.0,
            "yang_zhang_vol": 0.0,
            "vol_ratio_5_60": 1.0,
        }
