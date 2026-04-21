"""
ForwardStressDetector — Axis 5 of 5.

Forward-looking stress detection using VIX term structure.
Three-tier graceful degradation:
  Tier 1: VIX + VIX3M term spread (preferred — leads realized vol by months)
  Tier 2: VIX level + z-score only (if VIX3M unavailable)
  Tier 3: Synthetic vol proxy from realized volatility (offline/backtest fallback)

Based on Lai (2022): option-implied signals have 4.6% indecisive probability mass
vs 16% for returns and 34% for conditional volatility.
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple

from engines.engine_e_regime.regime_config import ForwardStressConfig


class ForwardStressDetector:
    """Detects forward stress regime from VIX term structure or synthetic proxy.

    States: "calm" | "cautious" | "stressed" | "panic"
    """

    def __init__(self, config: ForwardStressConfig = None):
        self.cfg = config or ForwardStressConfig()

    def detect(
        self,
        benchmark_df: pd.DataFrame,
        data_map: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> Tuple[str, float, dict]:
        """Analyze forward stress signals.

        Args:
            benchmark_df: SPY DataFrame (used for Tier 3 fallback).
            data_map: Full data_map that may contain ^VIX and ^VIX3M.

        Returns:
            (state, confidence, details)
        """
        cfg = self.cfg
        data_map = data_map or {}

        vix_df = data_map.get(cfg.vix_ticker)
        vix3m_df = data_map.get(cfg.vix3m_ticker)

        # Determine which tier we can use
        if vix_df is not None and vix3m_df is not None and len(vix_df) >= 20 and len(vix3m_df) >= 20:
            return self._tier1(vix_df, vix3m_df)
        elif vix_df is not None and len(vix_df) >= 20:
            return self._tier2(vix_df)
        else:
            return self._tier3(benchmark_df)

    def _tier1(
        self, vix_df: pd.DataFrame, vix3m_df: pd.DataFrame
    ) -> Tuple[str, float, dict]:
        """Tier 1: Full VIX term structure (VIX + VIX3M)."""
        cfg = self.cfg

        vix_close = self._get_close(vix_df)
        vix3m_close = self._get_close(vix3m_df)

        vix_val = float(vix_close.iloc[-1])
        vix3m_val = float(vix3m_close.iloc[-1])

        # Term spread: normally positive (contango). Negative = backwardation = fear
        term_spread = vix3m_val - vix_val

        # VIX z-score over lookback
        lookback = min(cfg.vix_lookback, len(vix_close))
        vix_history = vix_close.iloc[-lookback:]
        vix_mean = float(vix_history.mean())
        vix_std = float(vix_history.std())
        vix_z = (vix_val - vix_mean) / (vix_std + 1e-9)

        # Classification
        if (
            term_spread < cfg.panic_term_spread
            and vix_val > cfg.panic_vix_level
            and vix_z > cfg.panic_vix_z
        ):
            state = "panic"
        elif (
            term_spread < cfg.stressed_term_spread
            or vix_val > cfg.stressed_vix_level
            or vix_z > cfg.stressed_vix_z
        ):
            state = "stressed"
        elif (
            term_spread < cfg.cautious_term_spread
            or vix_val > cfg.cautious_vix_level
            or vix_z > cfg.cautious_vix_z
        ):
            state = "cautious"
        else:
            state = "calm"

        confidence = self._compute_confidence(state, vix_val, vix_z, term_spread)

        details = {
            "vix": round(vix_val, 2),
            "vix3m": round(vix3m_val, 2),
            "term_spread": round(term_spread, 2),
            "vix_z_score": round(vix_z, 3),
            "data_tier": "tier1_term_structure",
        }

        return (state, confidence, details)

    def _tier2(self, vix_df: pd.DataFrame) -> Tuple[str, float, dict]:
        """Tier 2: VIX level + z-score only (no VIX3M)."""
        cfg = self.cfg
        vix_close = self._get_close(vix_df)
        vix_val = float(vix_close.iloc[-1])

        lookback = min(cfg.vix_lookback, len(vix_close))
        vix_history = vix_close.iloc[-lookback:]
        vix_mean = float(vix_history.mean())
        vix_std = float(vix_history.std())
        vix_z = (vix_val - vix_mean) / (vix_std + 1e-9)

        # Without term spread, use VIX level and z-score only
        if vix_val > cfg.panic_vix_level and vix_z > cfg.panic_vix_z:
            state = "panic"
        elif vix_val > cfg.stressed_vix_level or vix_z > cfg.stressed_vix_z:
            state = "stressed"
        elif vix_val > cfg.cautious_vix_level or vix_z > cfg.cautious_vix_z:
            state = "cautious"
        else:
            state = "calm"

        # Tier 2 confidence is slightly lower (missing term structure info)
        confidence = self._compute_confidence(state, vix_val, vix_z, None)
        confidence = min(confidence, 0.85)  # cap at 0.85 for Tier 2

        details = {
            "vix": round(vix_val, 2),
            "vix3m": None,
            "term_spread": None,
            "vix_z_score": round(vix_z, 3),
            "data_tier": "tier2_vix_only",
        }

        return (state, confidence, details)

    def _tier3(self, benchmark_df: pd.DataFrame) -> Tuple[str, float, dict]:
        """Tier 3: Synthetic proxy from realized volatility ratio."""
        cfg = self.cfg

        if benchmark_df.empty or len(benchmark_df) < cfg.vix_lookback:
            return ("calm", 0.3, self._empty_details("tier3_synthetic"))

        df = benchmark_df.copy()
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df["Close"].astype(float)
        log_ret = np.log(close / close.shift(1))

        vol_short = float(log_ret.rolling(5).std().iloc[-1]) * np.sqrt(252)
        vol_long = float(log_ret.rolling(60).std().iloc[-1]) * np.sqrt(252)

        if np.isnan(vol_short) or np.isnan(vol_long):
            return ("calm", 0.3, self._empty_details("tier3_synthetic"))

        # Synthetic term spread: negative when short vol > long vol
        synthetic_spread = vol_long - vol_short

        # Synthetic VIX approximation (annualized short-term vol × 100 for VIX-like scale)
        synthetic_vix = vol_short * 100

        # Z-score of short-term vol
        vol_history = (log_ret.rolling(5).std() * np.sqrt(252)).dropna()
        lookback = min(cfg.vix_lookback, len(vol_history))
        vol_mean = float(vol_history.iloc[-lookback:].mean())
        vol_std_val = float(vol_history.iloc[-lookback:].std())
        vol_z = (vol_short - vol_mean) / (vol_std_val + 1e-9)

        # Use thresholds scaled for realized vol (less sharp than VIX)
        if synthetic_spread < -0.10 and synthetic_vix > 35 and vol_z > 2.0:
            state = "panic"
        elif synthetic_spread < -0.05 or synthetic_vix > 25 or vol_z > 1.5:
            state = "stressed"
        elif synthetic_spread < 0 or synthetic_vix > 18 or vol_z > 1.0:
            state = "cautious"
        else:
            state = "calm"

        # Tier 3 confidence is lowest (synthetic proxy)
        confidence = self._compute_confidence(state, synthetic_vix, vol_z, synthetic_spread)
        confidence = min(confidence, 0.75)  # cap at 0.75 for Tier 3

        details = {
            "vix": round(synthetic_vix, 2),
            "vix3m": None,
            "term_spread": round(synthetic_spread, 4),
            "vix_z_score": round(vol_z, 3),
            "data_tier": "tier3_synthetic",
        }

        return (state, confidence, details)

    def _compute_confidence(
        self, state: str, vix: float, vix_z: float, term_spread: Optional[float]
    ) -> float:
        """Compute confidence based on how deep into the state we are."""
        if state == "panic":
            confidence = 0.8 + 0.15 * min(vix_z / 3.0, 1.0)
        elif state == "stressed":
            confidence = 0.55 + 0.3 * min(vix_z / 2.0, 1.0)
        elif state == "cautious":
            confidence = 0.4 + 0.3 * min(vix_z / 1.5, 1.0)
        else:  # calm
            # Calm is more confident when VIX is well below thresholds
            calm_depth = max(0, (self.cfg.cautious_vix_level - vix) / 10.0)
            confidence = 0.4 + 0.4 * min(calm_depth, 1.0)

        return float(np.clip(confidence, 0.1, 0.95))

    @staticmethod
    def _get_close(df: pd.DataFrame) -> pd.Series:
        """Extract Close series, handling MultiIndex columns."""
        if isinstance(df.columns, pd.MultiIndex):
            df = df.copy()
            df.columns = df.columns.get_level_values(0)
        return df["Close"].astype(float)

    @staticmethod
    def _empty_details(tier: str = "tier3_synthetic") -> dict:
        return {
            "vix": None,
            "vix3m": None,
            "term_spread": None,
            "vix_z_score": 0.0,
            "data_tier": tier,
        }

    def reset(self) -> None:
        """No internal state to reset."""
        pass
