
import pandas as pd
import numpy as np
from typing import Dict, Any, List

class RegimePerfAnalytics:
    """
    Analytics module to measure strategy performance CONDITIONAL on Market Regime.
    Answers: "When does this strategy work best?"
    """
    
    def analyze(self, trades_df: pd.DataFrame, regime_history: pd.DataFrame) -> pd.DataFrame:
        """
        Merge trades with the regime AT ENTRY TIME.
        Calculate WinRate, Sharpe per Regime per Edge.
        """
        if trades_df.empty:
            return pd.DataFrame()
            
        # Ensure datetimes
        trades_df["timestamp"] = pd.to_datetime(trades_df["timestamp"])
        regime_history.index = pd.to_datetime(regime_history.index)
        
        # Tag trades with regime (Trend + Vol)
        # We assume regime_history has "trend" and "volatility" columns and is daily/hourly frequency
        # We align to the closest prior timestamp (asof join)
        
        trades_sorted = trades_df.sort_values("timestamp")
        regime_sorted = regime_history.sort_index()
        
        merged = pd.merge_asof(
            trades_sorted, 
            regime_sorted[["trend", "volatility"]], 
            left_on="timestamp", 
            right_index=True, 
            direction="backward"
        )
        
        merged["regime_label"] = merged["trend"] + "_" + merged["volatility"]
        
        # GroupBy Edge + Regime
        stats = merged.groupby(["edge", "regime_label"]).agg(
            pnl_sum=("pnl", "sum"),
            count=("pnl", "count"),
            win_rate=("pnl", lambda x: (x > 0).mean()),
            avg_win=("pnl", lambda x: x[x>0].mean() if (x>0).any() else 0),
            avg_loss=("pnl", lambda x: x[x<0].mean() if (x<0).any() else 0),
            # Simple trade-level Sharpe (mean/std) and Sortino (mean/downside_std)
            # Note: This is trade-level, not daily returns, but still useful for relative comparison
            trade_sharpe=("pnl", lambda x: x.mean() / (x.std() + 1e-9) if len(x) > 1 else 0),
            trade_sortino=("pnl", lambda x: x.mean() / (x[x<0].std() + 1e-9) if (x<0).any() and len(x) > 1 else (10.0 if x.mean() > 0 else 0))
        ).reset_index()
        
        # Derived: Profit Factor
        stats["profit_factor"] = abs(stats["avg_win"] / stats["avg_loss"].replace(0, -1e-9))
        
        return stats
