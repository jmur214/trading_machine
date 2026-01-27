import sys, os
import pandas as pd
import numpy as np
import pytest
from datetime import datetime, timedelta

# Ensure project root is in path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.alpha_engine import AlphaEngine
from engines.engine_a_alpha.edges.momentum_edge import MomentumEdge
# XSecMomentumEdge might require more complex data, let's stick to simple MomentumEdge for pipeline test
# from engines.engine_a_alpha.edges.xsec_momentum import XSecMomentumEdge

def create_mock_data(tickers, days=200):
    """Generates deterministic mock OHLCV data with a trend for testing."""
    data_map = {}
    dates = pd.date_range(end=datetime.now(), periods=days, freq="B")
    
    for t in tickers:
        # Create a trending series so momentum edge triggers
        np.random.seed(42) # Deterministic
        price = 100 + np.cumsum(np.random.randn(days)) + np.linspace(0, 20, days) # Upward trend
        
        df = pd.DataFrame(index=dates)
        df["Open"] = price
        df["High"] = price + 1
        df["Low"] = price - 1
        df["Close"] = price
        df["Volume"] = 1000000
        data_map[t] = df
        
    return data_map, dates[-1]

def test_alphaengine_pipeline():
    tickers = ["MOCK1", "MOCK2"]
    data_map, now = create_mock_data(tickers)

    # Use only MomentumEdge for simplicity in this pipeline test
    edges = {"momentum_edge": MomentumEdge()}
    
    # Custom config to ensure signals pass through SignalProcessor's normalization
    # MomentumEdge already returns tanh-normalized scores ([-1, 1]).
    # Default clamp=6.0 would shrink 0.67 to ~0.11, which is < default enter_threshold 0.2.
    custom_config = {
        "debug": True,
        "enter_threshold": 0.1,  # Lower threshold
        "exit_threshold": 0.05,
        "regime": {
            "enable_trend": False,
            "enable_vol": False,
            "shrink_off": 0.0
        },
        "hygiene": {
            "min_history": 0,
            "dedupe_last_n": 0,
            "clamp": 1.0  # Set clamp to 1.0 so tanh(0.67/1.0) = 0.58 > 0.1
        },
        "ensemble": {
            "enable_shrink": False,
            "combine": "weighted_mean"
        },
        "edge_weights": {
            "momentum_edge": 1.0
        }
    }

    # Initialize engine with custom config
    ae = AlphaEngine(edges=edges, config=custom_config, debug=True)
    
    # Generate signals
    signals = ae.generate_signals(data_map, now)
    
    print(f"Signals generated: {signals}")
    
    assert len(signals) > 0, "AlphaEngine produced no signals with trending mock data"
    
    # Verify structure
    for sig in signals:
        assert "ticker" in sig
        assert "side" in sig
        assert "strength" in sig
        assert sig["strength"] != 0, "Strength should be non-zero for trending data"