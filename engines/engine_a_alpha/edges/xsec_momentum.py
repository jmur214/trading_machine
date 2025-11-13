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
    def compute_signals(self, prices: pd.DataFrame, as_of: pd.Timestamp) -> dict[str, float]:
        # Detect if prices is a dict (from collector) and combine
        if isinstance(prices, dict):
            try:
                import pandas as _pd  # local alias
                close_frames = []
                for ticker, df in prices.items():
                    if not isinstance(df, _pd.DataFrame):
                        print(f"[xsec_momentum][WARN] {ticker} not a DataFrame: {type(df)}")
                        continue
                    # Flatten MultiIndex or tuple columns
                    if isinstance(df.columns, pd.MultiIndex) or any(isinstance(c, tuple) for c in df.columns):
                        df.columns = ["_".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in df.columns]
                        print(f"[xsec_momentum][INFO] Flattened MultiIndex columns for {ticker}: {list(df.columns)[:5]}")
                    cols = [c for c in df.columns if "close" in c.lower()]
                    if not cols:
                        print(f"[xsec_momentum][WARN] {ticker} missing Close column, available={list(df.columns)}")
                        continue
                    close_series = df[cols[0]].rename(ticker)
                    close_frames.append(close_series)
                if not close_frames:
                    print("[xsec_momentum][WARN] No valid close series found in prices dict")
                    return {}
                p = _pd.concat(close_frames, axis=1)
            except Exception as e:
                import warnings
                warnings.warn(f"[xsec_momentum] failed to combine prices dict ({type(e).__name__}): {e}")
                return {}
        else:
            p = prices.copy()

        p = p.loc[:as_of].copy()
        if p.empty or p.shape[0] < self.params.get("min_lookback", 60):
            return {}

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
            return {}
        mom = (recent.iloc[-1] / recent.iloc[-1 - lookback] - 1.0).dropna()

        if mom.empty:
            return {}

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

        # Return numeric dict {ticker: weight}
        return weights

    def generate_signals(self, prices, as_of):
        """
        Returns a list of rich signal dicts with keys:
        "ticker", "side", "confidence", "edge", "edge_group", "edge_id", "edge_category", "meta"
        """
        weights = self.compute_signals(prices, as_of)
        signals = []
        if not weights:
            return signals
        # Sort by abs(weight) descending for rank
        sorted_items = sorted(weights.items(), key=lambda x: -abs(x[1]))
        for rank, (ticker, weight) in enumerate(sorted_items, 1):
            side = "long" if weight > 0 else "short" if weight < 0 else "flat"
            confidence = abs(weight)
            signal = {
                "ticker": ticker,
                "side": side,
                "confidence": confidence,
                "edge": "xsec_momentum_v1",
                "edge_group": "momentum",
                "edge_id": "xsec_momentum_v1",
                "edge_category": "momentum",
                "meta": {
                    "explain": f"Cross-sectional momentum rank {rank}, weight={weight:.4f}",
                    "momentum_weight": weight,
                    "rank_position": rank,
                }
            }
            signals.append(signal)
        if _DBG:
            print(f"[EDGE][DEBUG][xsec_momentum_v1] Generated {len(signals)} rich signals at {as_of}")
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