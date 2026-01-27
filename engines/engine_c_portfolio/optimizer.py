
import numpy as np
import pandas as pd
from scipy.optimize import minimize
from typing import Dict, List, Optional, Tuple

class PortfolioOptimizer:
    """
    Mean-Variance Optimizer (MVO) for professional portfolio construction.
    Solves for weights that maximize utility:
        Maximize: w.T * mu - lambda * (w.T * Sigma * w)
    Subject to:
        sum(w) = 1 (or 0 for long-short neutral)
        0 <= w <= max_weight (long only per asset)
    """
    
    def __init__(self, risk_aversion: float = 1.0):
        self.risk_aversion = risk_aversion

    def optimize(
        self,
        mu: pd.Series,              # Expected returns (alpha scores)
        sigma: pd.DataFrame,        # Covariance matrix
        constraints: Dict[str, any] = None
    ) -> pd.Series:
        """
        Derive optimal weights.
        """
        tickers = mu.index.tolist()
        n = len(tickers)
        
        # Initial guess (equal weight)
        w0 = np.array([1.0/n] * n)
        
        # Objective Function: Minimize -Utility (Maximize Utility)
        # Utility = Returns - (Risk_Aversion * Variance) - (Transaction_Cost * Turnover)
        # current_weights: array of current holdings (aligned with tickers)
        # cost_bps: transaction cost in basis points (e.g. 10bps = 0.0010)
        
        current_weights = constraints.get("current_weights", np.zeros(n)) if constraints else np.zeros(n)
        cost_penalty = constraints.get("cost_penalty", 0.0010) if constraints else 0.0010 

        def objective(w):
            ret = np.dot(w, mu.values)
            risk = np.dot(w.T, np.dot(sigma.values, w))
            # Turnover = Sum(|w_new - w_old|)
            turnover = np.sum(np.abs(w - current_weights))
            return -(ret - self.risk_aversion * risk - cost_penalty * turnover)
            
        # Constraints
        # 1. Sum of weights = 1 (Fully invested)
        # We start with the base constraint
        cons = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]

        # 2. Sector Constraints (if provided)
        # constraints format expected: {"sector_map": {"AAPL": "Tech", ...}, "max_sector_exposure": 0.30}
        if constraints and "sector_map" in constraints and "max_sector_exposure" in constraints:
            s_map = constraints["sector_map"]
            max_sec = float(constraints["max_sector_exposure"])
            
            # Map tickers to indices
            t_to_i = {t: i for i, t in enumerate(tickers)}
            
            # Group indices by sector
            sectors = {}
            for t in tickers:
                sec = s_map.get(t, "Unknown")
                if sec not in sectors:
                    sectors[sec] = []
                sectors[sec].append(t_to_i[t])
            
            # Create a constraint for each sector
            for sec, indices in sectors.items():
                if not indices:
                    continue
                # Constraint: Sum(weights_in_sector) - max_sec <= 0  => Sum <= Max
                # Scipy 'ineq' means fun(x) >= 0. So we want: Max - Sum >= 0
                def sector_constraint(w, idxs=indices, limit=max_sec):
                    return limit - np.sum(w[idxs])
                
                cons.append({'type': 'ineq', 'fun': sector_constraint})

        
        # Bounds (0 to 1 for long only)
        bounds = tuple((0.0, 1.0) for _ in range(n))
        
        # Run Solver
        res = minimize(objective, w0, method='SLSQP', bounds=bounds, constraints=cons)
        
        if not res.success:
            print(f"[OPTIMIZER] Warning: Optimization failed: {res.message}")
            return pd.Series(w0, index=tickers) # Fallback
            
        return pd.Series(res.x, index=tickers)

    def calculate_metrics(self, weights: pd.Series, mu: pd.Series, sigma: pd.DataFrame) -> dict:
        w = weights.values
        ret = np.dot(w, mu.values)
        vol = np.sqrt(np.dot(w.T, np.dot(sigma.values, w)))
        sharpe = ret / vol if vol > 0 else 0
        return {
            "expected_return": ret,
            "expected_vol": vol,
            "sharpe": sharpe
        }
