import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.signal_collector import SignalCollector
from engines.engine_a_alpha.edges.momentum_edge import MomentumEdge
from engines.engine_a_alpha.edges.xsec_momentum import XSecMomentumEdge
import yfinance as yf

def test_collector_normalization():
    tickers = ["AAPL", "MSFT", "SPY"]
    data_map = {t: yf.download(t, period="3mo", interval="1d") for t in tickers}
    now = max(df.index.max() for df in data_map.values())

    edges = {"momentum_edge": MomentumEdge(), "xsec_momentum": XSecMomentumEdge()}
    collector = SignalCollector(edges=edges, debug=False)
    scores = collector.collect(data_map, now)
    assert isinstance(scores, dict)
    assert len(scores) > 0