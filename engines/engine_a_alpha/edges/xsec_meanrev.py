# engines/engine_a_alpha/edges/xsec_meanrev.py
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict, Any, Union
from engines.engine_a_alpha.edge_base import EdgeBase

try:
    from debug_config import is_debug_enabled
    _DBG = is_debug_enabled("ALPHA")
except Exception:
    _DBG = False

def _ann_vol(returns: pd.Series) -> float:
    r = returns.dropna()
    if r.empty:
        return np.nan
    return float(r.std() * np.sqrt(252.0))

class XSecMeanReversionEdge(EdgeBase):
    """
    Cross-sectional mean reversion via rolling z-scores of returns.
    Parameters:
      • lookback: window for z-score (e.g., 20)
      • rets_window: shorter return horizon for the signal (e.g., 5)
      • top_n: number of most overbought to SHORT
      • bottom_n: number of most oversold to LONG
      • min_lookback: minimum rows required (>= max(lookback, rets_window)+1)
      • vol_window: window for inverse-vol scaling (e.g., 20)
      • vol_target: target annualized portfolio vol (e.g., 0.10)
      • neutralize: 'dollar' or 'none'
      • z_clip: clamp absolute z-scores to this bound (e.g., 3.0)
    Returns weights in [-1, 1].
    """
    def compute_signals(self, prices: Union[pd.DataFrame, Dict[str, pd.DataFrame]], as_of: pd.Timestamp) -> Dict[str, float]:
        if isinstance(prices, dict):
            combined_weights: Dict[str, float] = {}
            for ticker, df in prices.items():
                if _DBG:
                    print(f"[ALPHA][DEBUG] Processing ticker '{ticker}'")
                weights = self._compute_signals_single(df, as_of)
                # Prefix keys with ticker to avoid collisions if needed
                for k, v in weights.items():
                    combined_weights[k] = v
                if _DBG:
                    print(f"[ALPHA][DEBUG] Ticker '{ticker}' weights: {weights}")
            return combined_weights
        else:
            return self._compute_signals_single(prices, as_of)

    def _compute_signals_single(self, prices: pd.DataFrame, as_of: pd.Timestamp) -> Dict[str, float]:
        p = prices.loc[:as_of]
        lookback = int(self.params.get("lookback", 20))
        rets_window = int(self.params.get("rets_window", 5))
        vol_window = int(self.params.get("vol_window", 20))
        vol_target = float(self.params.get("vol_target", 0.10))
        top_n = int(self.params.get("top_n", 1))
        bottom_n = int(self.params.get("bottom_n", 1))
        neutralize = str(self.params.get("neutralize", "dollar"))
        z_clip = float(self.params.get("z_clip", 3.0))
        min_lookback = int(self.params.get("min_lookback", max(lookback, rets_window) + 1))

        if p.empty or p.shape[0] < min_lookback:
            return {}

        recent = p.tail(max(lookback + 1, vol_window + 1, rets_window + 1)).copy()
        rets = recent.pct_change().dropna()
        if rets.empty:
            return {}

        # Rolling z-score of short-horizon returns (rets_window)
        rH = recent.pct_change(rets_window).iloc[-1]  # last rets_window-day return
        mu = rets.rolling(lookback).mean().iloc[-1]
        sd = rets.rolling(lookback).std().iloc[-1]
        z = (rH - mu).divide(sd.replace(0.0, np.nan))
        z = z.replace([np.inf, -np.inf], np.nan).dropna()

        if z.empty:
            return {}

        # Clip extreme z to reduce outlier impact and sort: high z = overbought
        z = z.clip(lower=-z_clip, upper=z_clip).sort_values(ascending=False)
        overbought = list(z.head(top_n).index)     # candidates to SHORT
        oversold = list(z.tail(bottom_n).index)    # candidates to LONG

        # Base signals: SHORT overbought (-1), LONG oversold (+1)
        weights: Dict[str, float] = {}
        for t in overbought:
            weights[t] = -1.0
        for t in oversold:
            weights[t] = weights.get(t, 0.0) + 1.0

        # Inverse-vol scaling
        asset_vol = rets.rolling(vol_window).std().iloc[-1] * np.sqrt(252.0)
        asset_vol = asset_vol.replace(0, np.nan)
        for t in list(weights.keys()):
            vol = float(asset_vol.get(t, np.nan))
            if not np.isfinite(vol) or vol <= 0:
                weights[t] *= 0.1
            else:
                weights[t] = weights[t] / vol

        # Dollar neutralize
        if neutralize == "dollar" and weights:
            s = sum(weights.values())
            if abs(s) > 1e-12:
                mean_w = s / len(weights)
                for t in weights:
                    weights[t] -= mean_w

        # Portfolio vol targeting (heuristic)
        if weights:
            w = pd.Series(weights).reindex(rets.columns).fillna(0.0)
            port_rets = (rets * w).sum(axis=1)
            sigma = _ann_vol(port_rets)
            if sigma and np.isfinite(sigma) and sigma > 0:
                scale = vol_target / sigma
                for t in weights:
                    weights[t] *= float(scale)

            # Safety clip
            for t in weights:
                weights[t] = float(np.clip(weights[t], -1.0, 1.0))

        if _DBG:
            print(f"[ALPHA][DEBUG] {as_of.date()} XSecMeanReversionEdge weights: {weights}")

        return weights

# Dynamic-import helpers (match how your AlphaEngine loads edges)
def set_params(params: Dict[str, Any]) -> None:
    global _EDGE_INSTANCE
    try:
        _EDGE_INSTANCE.set_params(params)
    except NameError:
        _EDGE_INSTANCE = XSecMeanReversionEdge()
        _EDGE_INSTANCE.set_params(params)

def compute_signals(prices: pd.DataFrame, as_of: pd.Timestamp) -> Dict[str, float]:
    global _EDGE_INSTANCE
    try:
        return _EDGE_INSTANCE.compute_signals(prices, as_of)
    except NameError:
        _EDGE_INSTANCE = XSecMeanReversionEdge()
        return _EDGE_INSTANCE.compute_signals(prices, as_of)