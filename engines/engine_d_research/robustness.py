
import pandas as pd
import numpy as np
from typing import List, Dict, Any, Optional

class RobustnessTester:
    """
    Tier 1 Research Tool: Robustness & Overfitting Check.
    
    Problem:
    --------
    "We have limited data." -> Standard backtests overfit to the specific history.
    
    Solution:
    ---------
    Data Augmentation via Circular Block Bootstrap. 
    We generate N "Synthetic Realities" that preserve the statistical properties 
    (volatility, correlation, regimes) of the original data but scramble the sequence.
    
    If a strategy survives these alternate realities, it is NOT overfit.
    """
    
    def generate_bootstrap_paths(self, df: pd.DataFrame, n_paths: int = 100, block_size: int = 20) -> List[pd.DataFrame]:
        """
        Generate N synthetic price histories using Circular Block Bootstrap.
        Preserves serial correlation within blocks (e.g. 20 days).
        """
        if df.empty:
            return []
            
        returns = df["Close"].pct_change().dropna().values
        n_samples = len(returns)
        
        synthetic_dfs = []
        
        # Pre-compute start price
        start_price = df["Close"].iloc[0]
        
        for i in range(n_paths):
            # Generate random block starting indices
            # We need approx n_samples / block_size blocks
            n_blocks = int(np.ceil(n_samples / block_size))
            
            # Random indices
            indices = np.random.randint(0, n_samples, n_blocks)
            
            synthetic_returns = []
            
            for idx in indices:
                # Grab the block, wrapping around if needed (Circular)
                if idx + block_size > n_samples:
                    # Split block (end + start)
                    part1 = returns[idx:]
                    part2 = returns[:(idx + block_size - n_samples)]
                    block = np.concatenate([part1, part2])
                else:
                    block = returns[idx : idx + block_size]
                
                synthetic_returns.append(block)
                
            # Flatten
            flat_ret = np.concatenate(synthetic_returns)[:n_samples]
            
            # Reconstruct Price Path (Geometric Brownian Motion approx from returns)
            # Price_t = Price_0 * Product(1 + r)
            price_path = start_price * np.cumprod(1 + flat_ret)
            
            # Create DataFrame
            # We preserve index (dates) for compatibility, though the "events" are scrambled
            syn_df = df.copy()
            # We only overwrite Close/Open/High/Low scalled
            # This is a simplification. For rigorous checks we'd scale everything.
            
            # Scale factor for H/L/O based on new Close vs Old Close magnitude?
            # Simpler: Just replace Close, assume execution assumes Close.
            # Or better: Apply pct_change to all columns?
            # MVP: Reconstruct Close.
            syn_df["Close"] = price_path
            syn_df["Open"] = price_path # Approx
            syn_df["High"] = price_path # Approx
            syn_df["Low"] = price_path # Approx
            
            synthetic_dfs.append(syn_df)
            
        return synthetic_dfs

    def calculate_pbo(self, 
                      strategy_func, 
                      df: pd.DataFrame, 
                      n_paths: int = 50) -> Dict[str, float]:
        """
        Probability of Backtest Overfitting (PBO).
        Runs the strategy on N synthetic paths.
        
        Metric: What % of synthetic equity curves have Sharpe > 0?
        If the strategy works in < 50% of synthetic markets, it effectively is random luck.
        We want > 90% survival rate.
        """
        paths = self.generate_bootstrap_paths(df, n_paths=n_paths)
        
        sharpes = []
        for path_df in paths:
            # Run strategy (Duck typed function that takes DF and returns equity curve or sharpe)
            # We assume strategy_func returns a dict with 'sharpe'
            try:
                res = strategy_func({"SYTH": path_df})
                sharpes.append(res.get("sharpe", -1.0))
            except Exception:
                sharpes.append(-1.0)
                
        sharpes = np.array(sharpes)
        
        # PBO Logic (Simplified variant)
        # Probability that the strategy fails in random market variants
        # Survival Rate
        survival_rate = (sharpes > 0.0).mean()
        avg_sharpe = sharpes.mean()
        
        return {
            "n_paths": n_paths,
            "survival_rate": float(survival_rate), # Target > 0.9
            "avg_synthetic_sharpe": float(avg_sharpe),
            "original_sharpe_percentile": 0.0 # TODO: Compare real result to these distribution
        }
