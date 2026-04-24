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
    mode: str = "adaptive"               # adaptive | parrondo_fixed
    target_volatility: float = 0.15      # portfolio-level target annualized vol (15%)
    vol_target_enabled: bool = True      # toggle the _apply_vol_target overlay for A/B
    exposure_cap_enabled: bool = True    # toggle the advisory exposure cap overlay for A/B
    min_weight: float = -0.1             # minimum per-asset weight (for shorts)
    max_weight: float = 0.25             # maximum per-asset weight
    vol_lookback: int = 20               # bars to use for rolling volatility
    rebalance_threshold: float = 0.02    # rebalance if deviation exceeds 2%
    risk_free_rate: float = 0.0
    debug: bool = False
    
    # Parrondo / Fixed Mode Settings
    fixed_allocations: Optional[Dict[str, float]] = None # e.g. {"SPY": 0.5, "SHV": 0.5}


class PortfolioPolicy:
    """
    Determines target position weights.
    Modes:
      - 'adaptive': Inverse Volatility weighted by Signal Strength (Bensdorp).
      - 'parrondo_fixed': Rebalance to fixed targets regardless of signals (Parrondo).
    """

    def __init__(self, cfg: Optional[PortfolioPolicyConfig] = None):
        self.cfg = cfg or PortfolioPolicyConfig()
        self._base_cfg_snapshot = {
            "max_weight": self.cfg.max_weight,
            "target_volatility": self.cfg.target_volatility,
            "rebalance_threshold": self.cfg.rebalance_threshold,
            "mode": self.cfg.mode,
        }

    # ------------------------------------------------------------------ #
    def _apply_regime_overrides(self, regime_meta: Optional[Dict] = None) -> None:
        """Temporarily override cfg params from allocation recommendations for this regime."""
        # Reset to base first
        for k, v in self._base_cfg_snapshot.items():
            setattr(self.cfg, k, v)

        if not regime_meta:
            return

        # Check for allocation recommendations in advisory
        advisory = regime_meta.get("advisory", {})
        if not advisory:
            return

        alloc_rec = advisory.get("allocation_recommendation")
        if not alloc_rec or not isinstance(alloc_rec, dict):
            # Try loading from disk
            try:
                from engines.engine_c_portfolio.allocation_evaluator import AllocationEvaluator
                evaluator = AllocationEvaluator()
                evaluator.load_recommendations()

                macro = regime_meta.get("macro_regime")
                if isinstance(macro, dict):
                    label = macro.get("label", "_global")
                elif isinstance(macro, str):
                    label = macro
                else:
                    label = "_global"

                alloc_rec = evaluator.get_config_for_regime(label)
            except Exception:
                return

        if not alloc_rec:
            return

        # Apply overrides (only for known safe keys)
        for key in ("max_weight", "target_volatility", "rebalance_threshold", "mode"):
            if key in alloc_rec:
                setattr(self.cfg, key, alloc_rec[key])

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
                 equity: float,
                 current_weights: Dict[str, float] = None,
                 regime_meta: Optional[Dict] = None) -> Dict[str, float]:
        """
        Compute target weights for each asset.
        """
        # --- Apply learned allocation recommendations (regime-conditional) ---
        self._apply_regime_overrides(regime_meta)

        # 1. Parrondo / Fixed Mode
        # Ignores 'signals' (Alpha) effectively, or treats signal existence as 'tradable'.
        # Returns hardcoded weights to force mechanical rebalancing.
        if self.cfg.mode == "parrondo_fixed" and self.cfg.fixed_allocations:
            # Normalize just in case
            raw = self.cfg.fixed_allocations
            total = sum(abs(v) for v in raw.values())
            if total > 0:
                return {k: v/total for k, v in raw.items()}
            return raw

        # 2. Mean-Variance Optimization Mode (Professional)
        if self.cfg.mode == "mean_variance":
            # Lazy import to avoid circular dep if not used
            from .optimizer import PortfolioOptimizer
            optimizer = PortfolioOptimizer(risk_aversion=1.0) # Could be configurable in cfg

            # Prepare Inputs: Mu (Expected Returns) and Sigma (Covariance)
            mu_series = pd.Series(signals)
            
            # Sigma: Compute covariance
            returns_map = {}
            for tkr in price_data:
                if tkr in signals:
                    df = price_data[tkr]
                    if not df.empty and "Close" in df.columns:
                        returns_map[tkr] = df["Close"].pct_change()
            
            if not returns_map:
                return {} 
                
            returns_df = pd.DataFrame(returns_map).fillna(0.0)
            if len(returns_df) < 5:
                pass 
            else:
                sigma_df = returns_df.cov() * 252.0
                mu_series = mu_series.reindex(sigma_df.columns).fillna(0.0)
                
                # --- Diversification: Load Sector Map ---
                import json
                import os
                sector_map = {}
                try:
                    # Try default location
                    if os.path.exists("config/sector_map.json"):
                        with open("config/sector_map.json", "r") as f:
                            sector_map = json.load(f)
                except Exception:
                    pass
                
                # Build Constraints
                
                # Align current_weights to mu_series index (tickers)
                c_weights_arr = np.zeros(len(mu_series))
                if current_weights:
                    # Normalize input weights just in case
                    for i, tkr in enumerate(mu_series.index):
                        c_weights_arr[i] = current_weights.get(tkr, 0.0)

                constraints = {
                    "sector_map": sector_map,
                    "max_sector_exposure": 0.30, # Hardcoded for now
                    "current_weights": c_weights_arr,
                    "cost_penalty": 0.0020 # 20bps friction
                }

                # Run Optimization
                abs_mu = mu_series.abs()
                weights_series = optimizer.optimize(abs_mu, sigma_df, constraints=constraints)
                
                # Re-apply signs and clamp to [min_weight, max_weight]
                weights_out = {}
                for tkr, w in weights_series.items():
                    signed_w = w * np.sign(signals.get(tkr, 0))
                    capped = float(np.clip(signed_w, self.cfg.min_weight, self.cfg.max_weight))
                    weights_out[tkr] = capped

                if self.cfg.debug:
                    print(f"[POLICY] min_weight={self.cfg.min_weight} max_weight={self.cfg.max_weight}")
                    print("[POLICY] MVO Targets (Optimized & Diversified):", weights_out)
                return weights_out

        # 3. Adaptive Mode (Default) (Inverse Vol Model)
        if not signals:
            return {}

        vols = self.compute_vol_estimates(price_data)
        if not vols:
            # Fallback if no vol data: Equal Weight
            n = len(signals)
            return {t: (1.0/n) * np.sign(s) for t, s in signals.items()} if n > 0 else {}

        inv_vols = {}
        # Filter only tickers with vol data. Sorted so set-intersection iteration
        # order is stable across runs — FP aggregation of `total` downstream is
        # order-dependent, and an unsorted set here was the second source of
        # backtest non-determinism.
        available_tickers = sorted(set(signals.keys()).intersection(vols.keys()))

        for tkr in available_tickers:
            s_strength = signals[tkr]
            vol = vols[tkr]
            if vol <= 0 or not np.isfinite(vol):
                continue
            # Bensdorp Logic: Weight = Signal / Volatility
            inv_vols[tkr] = abs(s_strength) / vol 
        
        if not inv_vols:
            return {}

        total = sum(inv_vols.values())
        weights = {}
        for tkr, iv in inv_vols.items():
            raw_w = (iv / total) * np.sign(signals[tkr])
            capped = np.clip(raw_w, self.cfg.min_weight, self.cfg.max_weight)
            weights[tkr] = float(capped)

        if self.cfg.debug:
            print("[POLICY] Vol estimates:", vols)
            print("[POLICY] Target weights (pre-overlay):", weights)

        # --- Portfolio-level vol targeting overlay ---
        if self.cfg.vol_target_enabled:
            weights = self._apply_vol_target(weights, price_data)

        # --- Advisory exposure cap (from Engine E regime detection) ---
        if self.cfg.exposure_cap_enabled:
            weights = self._apply_exposure_cap(weights, regime_meta)

        if self.cfg.debug:
            print("[POLICY] Final weights (post-overlay):", weights)

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
        count = 0
        for t, target in target_weights.items():
            curr = current_weights.get(t, 0.0)
            dev += abs(target - curr)
            count += 1
        
        # Check for assets held but no longer in target
        for t, curr in current_weights.items():
            if t not in target_weights and abs(curr) > 0.001:
                dev += abs(curr)
                # count already handled partially, but really dev matters total
        
        avg_dev = dev / max(1, count)
        return avg_dev > self.cfg.rebalance_threshold

    # ------------------------------------------------------------------ #
    def _estimate_portfolio_vol(self, weights: Dict[str, float],
                                price_data: Dict[str, pd.DataFrame]) -> float:
        """Estimate annualized portfolio volatility from weights and recent returns."""
        tickers = [t for t in weights if t in price_data and abs(weights[t]) > 1e-9]
        if len(tickers) < 2:
            # Single asset or empty: return asset vol or fallback
            if tickers:
                vols = self.compute_vol_estimates(price_data)
                return vols.get(tickers[0], self.cfg.target_volatility)
            return self.cfg.target_volatility

        # Build returns matrix
        returns_map = {}
        for tkr in tickers:
            df = price_data[tkr]
            if "Close" in df.columns and len(df) >= self.cfg.vol_lookback:
                returns_map[tkr] = df["Close"].pct_change().tail(self.cfg.vol_lookback)

        if len(returns_map) < 2:
            return self.cfg.target_volatility

        returns_df = pd.DataFrame(returns_map).dropna()
        if len(returns_df) < 5:
            return self.cfg.target_volatility

        cov = returns_df.cov() * 252.0  # annualized
        w_arr = np.array([weights.get(t, 0.0) for t in cov.columns])
        port_var = float(w_arr @ cov.values @ w_arr)
        return float(np.sqrt(max(port_var, 1e-12)))

    # ------------------------------------------------------------------ #
    def _apply_vol_target(self, weights: Dict[str, float],
                          price_data: Dict[str, pd.DataFrame]) -> Dict[str, float]:
        """Scale weights so portfolio vol matches target_volatility."""
        if not weights:
            return weights

        port_vol = self._estimate_portfolio_vol(weights, price_data)
        if port_vol < 1e-9:
            return weights

        vol_scalar = float(np.clip(self.cfg.target_volatility / port_vol, 0.3, 2.0))

        if abs(vol_scalar - 1.0) > 0.01:
            weights = {t: w * vol_scalar for t, w in weights.items()}
            # Re-clamp to max_weight
            weights = {t: float(np.clip(w, self.cfg.min_weight, self.cfg.max_weight))
                       for t, w in weights.items()}
            if self.cfg.debug:
                print(f"[POLICY] Vol target: port_vol={port_vol:.3f} target={self.cfg.target_volatility:.3f} scalar={vol_scalar:.2f}")

        return weights

    # ------------------------------------------------------------------ #
    def _apply_exposure_cap(self, weights: Dict[str, float],
                            regime_meta: Optional[Dict] = None) -> Dict[str, float]:
        """Enforce advisory gross exposure cap from Engine E."""
        if not weights or not regime_meta:
            return weights

        advisory = regime_meta.get("advisory", {})
        if not advisory:
            return weights

        cap = advisory.get("suggested_exposure_cap")
        if cap is None:
            return weights

        cap = float(cap)
        gross = sum(abs(w) for w in weights.values())
        if gross > cap and gross > 1e-9:
            scale = cap / gross
            weights = {t: w * scale for t, w in weights.items()}
            if self.cfg.debug:
                print(f"[POLICY] Exposure cap: gross={gross:.3f} > cap={cap:.3f}, scaling by {scale:.2f}")

        return weights