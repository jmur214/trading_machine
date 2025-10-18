# engines/engine_c_portfolio/policy.py
from __future__ import annotations

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class PortfolioPolicyConfig:
    """
    Configuration for the portfolio policy allocator.
    """
    target_volatility: float = 0.15      # portfolio-level target annualized vol (15%)
    min_weight: float = -0.1             # minimum per-asset weight (for shorts)
    max_weight: float = 0.25             # maximum per-asset weight
    vol_lookback: int = 20               # bars to use for rolling volatility
    rebalance_threshold: float = 0.02    # rebalance if deviation exceeds 2%
    risk_free_rate: float = 0.0          # for Sharpe-style weighting (optional)
    debug: bool = False


class PortfolioPolicy:
    """
    Determines target position weights for each ticker given:
      - recent volatility (risk parity)
      - current signal strength (from Engine A)
      - overall equity and caps

    Outputs normalized weights summing to 1.0 (subject to caps).
    """

    def __init__(self, cfg: Optional[PortfolioPolicyConfig] = None):
        self.cfg = cfg or PortfolioPolicyConfig()

    # ------------------------------------------------------------------ #
    def compute_vol_estimates(self, price_data: Dict[str, pd.DataFrame]) -> Dict[str, float]:
        """
        Compute annualized volatility per asset based on the last N bars.
        Returns dict: {ticker: vol}
        """
        vols = {}
        for tkr, df in price_data.items():
            if "Close" not in df.columns or len(df) < self.cfg.vol_lookback:
                continue
            returns = df["Close"].pct_change().dropna()
            if returns.empty:
                continue
            vol = returns.tail(self.cfg.vol_lookback).std() * np.sqrt(252)
            vols[tkr] = float(vol)
        return vols

    # ------------------------------------------------------------------ #
    def allocate(self,
                 signals: Dict[str, float],
                 price_data: Dict[str, pd.DataFrame],
                 equity: float) -> Dict[str, float]:
        """
        Compute target weights for each asset.
        signals: normalized edge strength in [-1, +1].
        Returns dict: {ticker: target_weight}
        """
        if not signals:
            return {}

        vols = self.compute_vol_estimates(price_data)
        if not vols:
            return {t: 0.0 for t in signals}

        inv_vols = {}
        for tkr, s in signals.items():
            vol = vols.get(tkr)
            if vol is None or vol <= 0 or not np.isfinite(vol):
                continue
            inv_vols[tkr] = abs(s) / vol  # signal-weighted inverse vol

        if not inv_vols:
            return {t: 0.0 for t in signals}

        total = sum(inv_vols.values())
        weights = {}
        for tkr, iv in inv_vols.items():
            raw_w = (iv / total) * np.sign(signals[tkr])
            capped = np.clip(raw_w, self.cfg.min_weight, self.cfg.max_weight)
            weights[tkr] = float(capped)

        if self.cfg.debug:
            print("[POLICY] Vol estimates:", vols)
            print("[POLICY] Target weights:", weights)

        return weights

    # ------------------------------------------------------------------ #
    def requires_rebalance(self,
                           current_weights: Dict[str, float],
                           target_weights: Dict[str, float]) -> bool:
        """
        Determine whether the portfolio should rebalance based on deviation.
        """
        if not current_weights:
            return True
        dev = 0.0
        for t in target_weights:
            dev += abs(target_weights[t] - current_weights.get(t, 0.0))
        avg_dev = dev / max(1, len(target_weights))
        return avg_dev > self.cfg.rebalance_threshold