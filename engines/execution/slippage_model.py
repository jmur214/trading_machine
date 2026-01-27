# engines/execution/slippage_model.py
from abc import ABC, abstractmethod
from dataclasses import dataclass
import numpy as np
import pandas as pd

@dataclass
class SlippageConfig:
    model_type: str = "fixed"  # "fixed" or "volatility"
    base_bps: float = 10.0     # Base slippage in basis points
    vol_lookback: int = 20     # Lookback for volatility calculation
    vol_multiplier: float = 1.0 # Multiplier for volatility impact

class SlippageModel(ABC):
    """
    Abstract base class for slippage models.
    """
    def __init__(self, config: SlippageConfig):
        self.config = config

    @abstractmethod
    def calculate_slippage_bps(self, ticker: str, bar_data: pd.DataFrame | pd.Series, side: str) -> float:
        """
        Calculate slippage in basis points for a given trade.
        
        Args:
            ticker: The asset ticker.
            bar_data: DataFrame or Series containing recent market data (must have 'Close' or 'High'/'Low').
            side: 'buy', 'sell', 'short', 'cover'.
            
        Returns:
            float: Slippage in basis points.
        """
        pass

    def apply_slippage(self, price: float, bps: float, side: str) -> float:
        """
        Apply calculated slippage to a price.
        """
        slip_amount = price * (bps / 10000.0)
        s = side.lower()
        if s in ("long", "buy", "cover"):   # paying more
            return price + slip_amount
        if s in ("short", "sell", "exit"):  # receiving less
            return price - slip_amount
        return price


class FixedSlippageModel(SlippageModel):
    """
    Applies a constant fixed basis point slippage to every trade.
    """
    def calculate_slippage_bps(self, ticker: str, bar_data: pd.DataFrame | pd.Series, side: str) -> float:
        return self.config.base_bps


class VolatilitySlippageModel(SlippageModel):
    """
    Scales slippage based on recent volatility (ATR or StdDev).
    Formula: effective_bps = base_bps * (current_vol / avg_vol)
    
    If data is insufficient, falls back to base_bps.
    """
    def calculate_slippage_bps(self, ticker: str, bar_data: pd.DataFrame | pd.Series, side: str) -> float:
        # If we only have a single row (Series), we can't compute vol, fallback to fixed
        if isinstance(bar_data, pd.Series):
            return self.config.base_bps
            
        if len(bar_data) < self.config.vol_lookback + 1:
            return self.config.base_bps

        try:
            # Calculate simple volatility (std dev of returns)
            closes = bar_data["Close"]
            returns = closes.pct_change().dropna()
            
            if len(returns) < self.config.vol_lookback:
                return self.config.base_bps

            current_vol = returns.tail(self.config.vol_lookback).std()
            long_term_vol = returns.std() # or use a longer fixed window if available
            
            if long_term_vol == 0:
                return self.config.base_bps

            # Scale factor: how turbulent is it right now vs usually?
            # We clip it to avoid extreme multipliers (e.g., 0.5x to 5.0x)
            ratio = current_vol / long_term_vol
            ratio = max(0.5, min(5.0, ratio))
            
            return self.config.base_bps * ratio * self.config.vol_multiplier
            
        except Exception:
            return self.config.base_bps

def get_slippage_model(config_dict: dict) -> SlippageModel:
    """Factory to create the appropriate model from a config dict."""
    cfg = SlippageConfig(
        model_type=config_dict.get("model_type", "fixed"),
        base_bps=float(config_dict.get("slippage_bps", 10.0)),
        vol_lookback=int(config_dict.get("vol_lookback", 20)),
        vol_multiplier=float(config_dict.get("vol_multiplier", 1.0))
    )
    
    if cfg.model_type == "volatility":
        return VolatilitySlippageModel(cfg)
    return FixedSlippageModel(cfg)
