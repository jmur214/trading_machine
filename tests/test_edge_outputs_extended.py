# tests/test_edge_outputs_extended.py
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np
import pandas as pd
import pytest
from engines.engine_a_alpha.edges.rsi_bounce import RSIBounceEdge
from engines.engine_a_alpha.edges.atr_breakout import ATRBreakoutEdge
from engines.engine_a_alpha.edges.bollinger_reversion import BollingerReversionEdge


def _synthetic_ohlcv(n: int = 120, seed: int = 0) -> pd.DataFrame:
    """Deterministic OHLCV. Mimics yfinance's old single-level columns
    so we don't depend on the network or on yfinance's MultiIndex format
    change. The original test used yfinance live downloads; yfinance now
    returns MultiIndex columns even for single-ticker pulls, breaking
    every consumer that expects df['Close'] to be a Series."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.012, n)
    close = 100.0 * np.cumprod(1.0 + rets)
    high = close * (1.0 + np.abs(rng.normal(0.0, 0.005, n)))
    low = close * (1.0 - np.abs(rng.normal(0.0, 0.005, n)))
    open_ = (high + low) / 2.0
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Open": open_, "High": high, "Low": low, "Close": close,
        "Volume": np.full(n, 1_000_000),
    }, index=idx)


@pytest.mark.parametrize("EdgeCls", [RSIBounceEdge, ATRBreakoutEdge, BollingerReversionEdge])
def test_edge_output_shape(EdgeCls):
    tickers = ["AAPL", "MSFT", "SPY"]
    data_map = {t: _synthetic_ohlcv(seed=hash(t) % 1000) for t in tickers}
    now = max(df.index.max() for df in data_map.values())
    edge = EdgeCls()
    scores = edge.compute_signals(data_map, now)
    assert isinstance(scores, dict)
    assert all(isinstance(v, float) for v in scores.values())
    signals = edge.generate_signals(data_map, now)
    for s in signals:
        assert "ticker" in s and "side" in s and "confidence" in s