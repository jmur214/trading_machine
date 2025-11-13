from engines.engine_a_alpha.edges.momentum_edge import MomentumEdge
from engines.engine_a_alpha.edges.xsec_momentum import XSecMomentumEdge
import yfinance as yf, pandas as pd

def test_edges_output():
    tickers = ["AAPL", "MSFT", "SPY"]
    data_map = {t: yf.download(t, period="6mo", interval="1d") for t in tickers}
    now = max(df.index.max() for df in data_map.values())

    edges = [MomentumEdge(), XSecMomentumEdge()]

    for e in edges:
        signals = e.generate_signals(data_map, now)
        assert isinstance(signals, list)
        for s in signals:
            assert "ticker" in s
            assert "side" in s
            assert "confidence" in s
            assert isinstance(s["confidence"], (float, int))
            