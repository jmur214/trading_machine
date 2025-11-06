from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict, Any, Sequence
from engines.engine_a_alpha.edge_base import EdgeBase

# Optional: if you have debug_config, honor it (quiet by default)
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

class XSecMomentumEdge(EdgeBase):
    """
    Cross-sectional momentum:
      • lookback: days to compute momentum (e.g., 60)
      • top_n, bottom_n: how many to long/short (e.g., 2 long, 1 short)
      • min_lookback: require at least this many data points before trading
      • vol_target: annualized vol target for portfolio (e.g., 0.10 = 10%)
      • vol_window: window for vol estimation (e.g., 20)
      • neutralize: 'dollar' or 'none' (simple dollar-neutral long/short)
    Returns signals as weights in [-1,1], not just {-1,0,1}.
    """
    def compute_signals(self, prices: pd.DataFrame, as_of: pd.Timestamp) -> list[dict]:
        p = prices.loc[:as_of].copy()
        if p.empty or p.shape[0] < self.params.get("min_lookback", 60):
            return []

        lookback = int(self.params.get("lookback", 60))
        top_n = int(self.params.get("top_n", 2))
        bottom_n = int(self.params.get("bottom_n", 1))
        vol_window = int(self.params.get("vol_window", 20))
        vol_target = float(self.params.get("vol_target", 0.10))
        neutralize = str(self.params.get("neutralize", "dollar"))

        recent = p.tail(max(lookback + 1, vol_window + 1))
        rets = recent.pct_change().dropna()

        # Momentum score = trailing total return over lookback
        if recent.shape[0] < lookback + 1:
            return []
        mom = (recent.iloc[-1] / recent.iloc[-1 - lookback] - 1.0).dropna()

        if mom.empty:
            return []

        # Rank by momentum
        mom = mom.sort_values(ascending=False)
        longs = list(mom.head(top_n).index)
        shorts = list(mom.tail(bottom_n).index)

        # Vol-scaling per asset: inverse vol weights
        asset_vol = rets.rolling(vol_window).std().iloc[-1] * np.sqrt(252.0)
        asset_vol = asset_vol.replace(0, np.nan)

        weights: Dict[str, float] = {}
        # Base raw signal = +1 for longs, -1 for shorts
        for t in longs:
            weights[t] = 1.0
        for t in shorts:
            weights[t] = weights.get(t, 0.0) - 1.0

        # Scale by inverse vol so risk is more balanced
        for t in list(weights.keys()):
            vol = float(asset_vol.get(t, np.nan))
            if not np.isfinite(vol) or vol <= 0:
                # if vol unknown, keep small weight
                weights[t] *= 0.1
            else:
                weights[t] = weights[t] / vol  # inverse-vol scaling

        # Dollar-neutral (sum weights ~ 0)
        if neutralize == "dollar" and weights:
            s = sum(weights.values())
            if abs(s) > 1e-12:
                # subtract mean weight to center
                mean_w = s / len(weights)
                for t in weights:
                    weights[t] -= mean_w

        # Rescale to portfolio vol target (rough heuristic).
        # Estimate portfolio vol from weighted returns
        if weights:
            w = pd.Series(weights).reindex(rets.columns).fillna(0.0)
            port_rets = (rets * w).sum(axis=1)
            sigma = _ann_vol(port_rets)
            if sigma and np.isfinite(sigma) and sigma > 0:
                scale = vol_target / sigma
                for t in weights:
                    weights[t] *= float(scale)

            # Clip weights into [-1, 1] for safety
            for t in weights:
                weights[t] = float(np.clip(weights[t], -1.0, 1.0))

        if _DBG:
            print(f"[ALPHA][DEBUG] {as_of.date()} XSecMomentumEdge weights: {weights}")

        signals = []
        for t, w in weights.items():
            signals.append({
                "ticker": t,
                "side": "long" if w > 0 else "short",
                "confidence": abs(w),
                "edge": "xsec_momentum",
                "edge_id": "xsec_momentum",
                "category": "technical",
                "meta": {"weight": w}
            })

        return signals

# convenience constructors used by harness dynamic importer
def set_params(params: Dict[str, Any]) -> None:
    global _EDGE_INSTANCE
    try:
        _EDGE_INSTANCE.set_params(params)
    except NameError:
        _EDGE_INSTANCE = XSecMomentumEdge()
        _EDGE_INSTANCE.set_params(params)

def compute_signals(prices: pd.DataFrame, as_of: pd.Timestamp) -> list[dict]:
    global _EDGE_INSTANCE
    try:
        return _EDGE_INSTANCE.compute_signals(prices, as_of)
    except NameError:
        _EDGE_INSTANCE = XSecMomentumEdge()
        return _EDGE_INSTANCE.compute_signals(prices, as_of)