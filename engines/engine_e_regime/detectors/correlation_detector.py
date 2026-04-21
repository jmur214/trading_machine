"""
CorrelationDetector — Axis 3 of 5.

Classifies market correlation regime using three components:
  A. Sector correlation via PC1 explained variance (primary) + avg pairwise (secondary)
  B. Cross-asset: SPY-TLT correlation with directionality check, SPY-GLD safe-haven
  C. Combined classification into dispersed / normal / elevated / spike
"""

import json
import os
import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple

from engines.engine_e_regime.regime_config import CorrelationConfig

_SECTOR_MAP_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "config", "sector_map.json"
)


def _load_sector_map(path: str = _SECTOR_MAP_PATH) -> dict:
    """Load ticker → sector mapping from config."""
    resolved = os.path.abspath(path)
    if not os.path.exists(resolved):
        return {}
    with open(resolved, "r") as f:
        return json.load(f)


class CorrelationDetector:
    """Detects correlation regime from multi-ticker data.

    States: "dispersed" | "normal" | "elevated" | "spike"
    """

    def __init__(self, config: CorrelationConfig = None, sector_map: dict = None):
        self.cfg = config or CorrelationConfig()
        self.sector_map = sector_map or _load_sector_map()

    def detect(
        self,
        data_map: Dict[str, pd.DataFrame],
        now_idx: int = -1,
    ) -> Tuple[str, float, dict]:
        """Analyze correlation structure across all tickers.

        Args:
            data_map: Dict of {ticker: OHLCV DataFrame}.
            now_idx: Index position to evaluate (default -1 for latest bar).

        Returns:
            (state, confidence, details)
        """
        cfg = self.cfg

        # --- A. Sector correlation ---
        pc1_var, avg_corr = self._compute_sector_correlation(data_map, now_idx)

        # --- B. Cross-asset correlations ---
        spy_tlt_corr = self._cross_asset_corr(data_map, "SPY", "TLT", cfg.rolling_window, now_idx)
        spy_gld_corr = self._cross_asset_corr(data_map, "SPY", "GLD", cfg.rolling_window, now_idx)

        # SPY-TLT directionality: is correlation rising rapidly?
        spy_tlt_corr_change = 0.0
        if "SPY" in data_map and "TLT" in data_map:
            spy_tlt_corr_change = self._compute_corr_change(
                data_map, "SPY", "TLT", cfg.rolling_window, cfg.spy_tlt_change_lookback, now_idx
            )

        # --- Combined classification ---
        # PC1 is the primary metric, avg_corr and spy_tlt are secondary
        if (
            pc1_var > cfg.pc1_spike_threshold
            or avg_corr > cfg.avg_corr_spike_threshold
            or spy_tlt_corr > cfg.spy_tlt_spike_threshold
        ):
            state = "spike"
        elif (
            pc1_var > cfg.pc1_elevated_threshold
            or avg_corr > cfg.avg_corr_elevated_threshold
            or spy_tlt_corr > cfg.spy_tlt_elevated_threshold
        ):
            state = "elevated"
        elif (
            pc1_var < cfg.pc1_dispersed_threshold
            and avg_corr < cfg.avg_corr_dispersed_threshold
            and spy_tlt_corr < cfg.spy_tlt_dispersed_threshold
        ):
            state = "dispersed"
        else:
            state = "normal"

        # --- Confidence ---
        if state == "spike":
            # Higher PC1 → higher confidence
            confidence = 0.6 + 0.35 * min(
                (pc1_var - cfg.pc1_spike_threshold) / 0.15, 1.0
            )
        elif state == "elevated":
            confidence = 0.5 + 0.3 * min(
                (pc1_var - cfg.pc1_elevated_threshold) / 0.15, 1.0
            )
        elif state == "dispersed":
            confidence = 0.5 + 0.3 * min(
                (cfg.pc1_dispersed_threshold - pc1_var) / 0.15, 1.0
            )
        else:
            confidence = 0.5

        confidence = float(np.clip(confidence, 0.1, 0.95))

        details = {
            "avg_sector_corr": round(avg_corr, 3),
            "pc1_explained": round(pc1_var, 3),
            "spy_tlt_corr": round(spy_tlt_corr, 3),
            "spy_tlt_corr_change": round(spy_tlt_corr_change, 4),
            "spy_gld_corr": round(spy_gld_corr, 3),
        }

        return (state, confidence, details)

    def _compute_sector_correlation(
        self, data_map: Dict[str, pd.DataFrame], now_idx: int
    ) -> Tuple[float, float]:
        """Compute PC1 explained variance and average pairwise correlation of sector returns.

        Sector returns are weighted by number of constituent tickers.
        Returns (pc1_explained_variance, avg_pairwise_correlation).
        """
        cfg = self.cfg

        # Group tickers by sector
        sector_tickers: Dict[str, list] = {}
        for ticker, sector in self.sector_map.items():
            if sector in ("Benchmark",) or ticker not in data_map:
                continue
            sector_tickers.setdefault(sector, []).append(ticker)

        # Build sector return series (ticker-count-weighted)
        sector_returns = {}
        for sector, tickers in sector_tickers.items():
            returns_list = []
            for t in tickers:
                df = data_map[t]
                if isinstance(df.columns, pd.MultiIndex):
                    df = df.copy()
                    df.columns = df.columns.get_level_values(0)
                close = df["Close"].astype(float)
                if len(close) < cfg.rolling_window + 5:
                    continue
                ret = close.pct_change().dropna()
                if now_idx != -1:
                    ret = ret.iloc[: now_idx + 1]
                returns_list.append(ret)

            if returns_list:
                # Equal-weight within sector (each ticker contributes proportionally)
                aligned = pd.concat(returns_list, axis=1).dropna()
                if len(aligned) >= cfg.rolling_window:
                    sector_returns[sector] = aligned.mean(axis=1)

        if len(sector_returns) < self.cfg.min_sectors:
            return (0.30, 0.30)  # insufficient data — neutral

        # Align all sector return series
        sector_df = pd.DataFrame(sector_returns).dropna()
        if len(sector_df) < cfg.rolling_window:
            return (0.30, 0.30)

        # Use the last rolling_window bars
        recent = sector_df.iloc[-cfg.rolling_window :]

        # --- PC1 explained variance via SVD ---
        cov_matrix = recent.cov().values
        try:
            _, s, _ = np.linalg.svd(cov_matrix)
            pc1_var = float(s[0] / s.sum()) if s.sum() > 0 else 0.30
        except np.linalg.LinAlgError:
            pc1_var = 0.30

        # --- Average pairwise correlation ---
        corr_matrix = recent.corr().values
        n = corr_matrix.shape[0]
        if n > 1:
            # Upper triangle excluding diagonal
            upper = corr_matrix[np.triu_indices(n, k=1)]
            avg_corr = float(np.nanmean(upper))
        else:
            avg_corr = 0.30

        return (pc1_var, avg_corr)

    def _cross_asset_corr(
        self,
        data_map: Dict[str, pd.DataFrame],
        ticker_a: str,
        ticker_b: str,
        window: int,
        now_idx: int,
    ) -> float:
        """Compute rolling correlation between two tickers."""
        if ticker_a not in data_map or ticker_b not in data_map:
            return 0.0

        df_a = data_map[ticker_a]
        df_b = data_map[ticker_b]

        for df in (df_a, df_b):
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

        close_a = df_a["Close"].astype(float).pct_change()
        close_b = df_b["Close"].astype(float).pct_change()

        aligned = pd.concat(
            [close_a.rename("a"), close_b.rename("b")], axis=1
        ).dropna()

        if len(aligned) < window:
            return 0.0

        if now_idx != -1:
            aligned = aligned.iloc[: now_idx + 1]

        recent = aligned.iloc[-window:]
        corr = recent["a"].corr(recent["b"])
        return float(corr) if not np.isnan(corr) else 0.0

    def _compute_corr_change(
        self,
        data_map: Dict[str, pd.DataFrame],
        ticker_a: str,
        ticker_b: str,
        window: int,
        change_lookback: int,
        now_idx: int,
    ) -> float:
        """Compute how much SPY-TLT correlation has changed over change_lookback bars.

        Positive = correlation is rising (moving toward zero or positive = warning).
        """
        if ticker_a not in data_map or ticker_b not in data_map:
            return 0.0

        df_a = data_map[ticker_a]
        df_b = data_map[ticker_b]

        for df in (df_a, df_b):
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

        close_a = df_a["Close"].astype(float).pct_change()
        close_b = df_b["Close"].astype(float).pct_change()

        aligned = pd.concat(
            [close_a.rename("a"), close_b.rename("b")], axis=1
        ).dropna()

        if now_idx != -1:
            aligned = aligned.iloc[: now_idx + 1]

        if len(aligned) < window + change_lookback:
            return 0.0

        # Current rolling correlation
        current_corr = aligned["a"].iloc[-window:].corr(aligned["b"].iloc[-window:])
        # Correlation change_lookback bars ago
        past_end = -change_lookback
        past_corr = (
            aligned["a"].iloc[past_end - window : past_end].corr(
                aligned["b"].iloc[past_end - window : past_end]
            )
        )

        if np.isnan(current_corr) or np.isnan(past_corr):
            return 0.0

        return float(current_corr - past_corr)

    def reset(self) -> None:
        """No internal state to reset for CorrelationDetector."""
        pass

    @staticmethod
    def _empty_details() -> dict:
        return {
            "avg_sector_corr": 0.0,
            "pc1_explained": 0.0,
            "spy_tlt_corr": 0.0,
            "spy_tlt_corr_change": 0.0,
            "spy_gld_corr": 0.0,
        }
