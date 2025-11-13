# tests/test_edge_outputs_extended.py
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest, yfinance as yf, pandas as pd
from datetime import datetime
from engines.engine_a_alpha.edges.rsi_bounce import RSIBounceEdge
from engines.engine_a_alpha.edges.atr_breakout import ATRBreakoutEdge
from engines.engine_a_alpha.edges.bollinger_reversion import BollingerReversionEdge

@pytest.mark.parametrize("EdgeCls", [RSIBounceEdge, ATRBreakoutEdge, BollingerReversionEdge])
def test_edge_output_shape(EdgeCls):
    tickers = ["AAPL", "MSFT", "SPY"]
    data_map = {t: yf.download(t, period="3mo", interval="1d") for t in tickers}
    now = max(df.index.max() for df in data_map.values())
    edge = EdgeCls()
    scores = edge.compute_signals(data_map, now)
    assert isinstance(scores, dict)
    assert all(isinstance(v, float) for v in scores.values())
    signals = edge.generate_signals(data_map, now)
    for s in signals:
        assert "ticker" in s and "side" in s and "confidence" in s