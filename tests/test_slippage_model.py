import sys, os
import pytest
import pandas as pd
import numpy as np

# Ensure project root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.execution.slippage_model import get_slippage_model, FixedSlippageModel, VolatilitySlippageModel

def test_fixed_slippage():
    cfg = {"model_type": "fixed", "slippage_bps": 10.0}
    model = get_slippage_model(cfg)
    assert isinstance(model, FixedSlippageModel)
    
    # Buy: price + slippage
    price = 100.0
    bps = model.calculate_slippage_bps("TEST", pd.Series(), "buy")
    assert bps == 10.0
    filled = model.apply_slippage(price, bps, "buy")
    assert filled == 100.10 # 100 + 10bps (0.10)
    
    # Sell: price - slippage
    filled = model.apply_slippage(price, bps, "sell")
    assert filled == 99.90

def test_volatility_slippage_fallback():
    cfg = {"model_type": "volatility", "slippage_bps": 10.0}
    model = get_slippage_model(cfg)
    assert isinstance(model, VolatilitySlippageModel)
    
    # Single row -> fallback to fixed
    bps = model.calculate_slippage_bps("TEST", pd.Series({"Close": 100}), "buy")
    assert bps == 10.0

def test_volatility_slippage_scaling():
    cfg = {"model_type": "volatility", "slippage_bps": 10.0, "vol_lookback": 5}
    model = get_slippage_model(cfg)
    
    # Create synthetic data: 
    # High vol period
    dates = pd.date_range("2023-01-01", periods=20)
    # Alternating +2% / -2% returns -> high vol
    prices = [100.0]
    for i in range(19):
        change = 1.02 if i % 2 == 0 else 0.98
        prices.append(prices[-1] * change)
        
    df = pd.DataFrame({"Close": prices}, index=dates)
    
    # Calculate bps
    bps = model.calculate_slippage_bps("TEST", df, "buy")
    
    # Vol should be high relative to "long term" (which is just the sample std here)
    # Actually, in my implementation:
    # current_vol = returns.tail(lookback).std()
    # long_term_vol = returns.std()
    # If the whole series is high vol, ratio ~ 1.0 -> bps ~ 10.0
    
    # Let's make the recent part MORE volatile than the past
    prices_stable = [100.0] * 20 # zero vol
    prices_volatile = [100.0, 105.0, 95.0, 105.0, 95.0] # high vol
    
    df_stable = pd.DataFrame({"Close": prices_stable}, index=dates)
    
    # Append volatile tail
    df_combined = pd.concat([
        pd.DataFrame({"Close": [100.0]*50}), 
        pd.DataFrame({"Close": [100, 105, 95, 105, 95, 105]})
    ]).reset_index(drop=True)
    
    bps = model.calculate_slippage_bps("TEST", df_combined, "buy")
    
    # Current vol (last 5) >> Long term vol (mostly flat)
    # Ratio should be > 1.0
    assert bps > 10.0
    print(f"Vol-adjusted BPS: {bps}")

def test_execution_simulator_integration():
    from backtester.execution_simulator import ExecutionSimulator
    
    # Init with fixed model
    sim = ExecutionSimulator(slippage_bps=20.0, slippage_model="fixed")
    
    order = {"ticker": "TEST", "side": "long", "qty": 100}
    bar = pd.Series({"Open": 100.0, "High": 101, "Low": 99, "Close": 100, "PrevClose": 100})
    
    fill = sim.fill_at_next_open(order, bar)
    assert fill["fill_price"] == 100.20 # 100 + 20bps
