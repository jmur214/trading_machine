# -------------------------------------------------------------------
# Engine B (Extension): Factor Risk Model
# -------------------------------------------------------------------
# A proprietary risk model used to decompose portfolio risk into
# systematic factors (Beta, Momentum, Size, Value, Volatility).
# 
# Used by the Optimizer to enforce Factor Neutrality if requested.
# -------------------------------------------------------------------

import pandas as pd
import numpy as np
from typing import Dict, List

class FactorRiskModel:
    """
    Computes factor exposures for a universe of assets.
    Factors:
    - Market (SPY Beta)
    - Momentum (12M-1M return)
    - Volatility (IDIO Vol)
    """
    
    def __init__(self, benchmark_ticker="SPY"):
        self.benchmark = benchmark_ticker
        
    def compute_exposures(self, price_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """
        Returns a DataFrame of factor loadings (Tickers x Factors).
        """
        exposures = {}
        
        spy = price_data.get(self.benchmark)
        if spy is None:
            return pd.DataFrame()
            
        spy_ret = spy["Close"].pct_change().dropna()
        
        for tkr, df in price_data.items():
            if tkr == self.benchmark: continue
            if df.empty or len(df) < 60: continue
            
            ret = df["Close"].pct_change().dropna()
            
            # Align
            common = ret.index.intersection(spy_ret.index)
            if len(common) < 30: continue
            
            y = ret.loc[common]
            X = spy_ret.loc[common]
            
            # 1. Market Beta
            try:
                cov = np.cov(y, X)[0, 1]
                var = np.var(X)
                beta = cov / var
            except:
                beta = 1.0
                
            # 2. Momentum (12-1 Return)
            # Simple proxy: last 126 days return
            mom = (df["Close"].iloc[-1] / df["Close"].iloc[0]) - 1.0
            
            # 3. Size (Log Price as proxy if MarketCap unavailable)
            size = np.log(df["Close"].iloc[-1] * df["Volume"].iloc[-20:].mean())
            
            exposures[tkr] = {
                "beta": beta,
                "momentum": mom,
                "size_proxy": size
            }
            
        df_exp = pd.DataFrame.from_dict(exposures, orient='index')
        
        # Z-Score Normalize
        return (df_exp - df_exp.mean()) / df_exp.std()
