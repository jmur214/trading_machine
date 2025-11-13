import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.alpha_engine import AlphaEngine
from engines.engine_a_alpha.edges.momentum_edge import MomentumEdge
from engines.engine_a_alpha.edges.xsec_momentum import XSecMomentumEdge
import yfinance as yf

def test_alphaengine_pipeline():
    tickers = ["AAPL", "MSFT", "SPY"]
    data_map = {t: yf.download(t, period="6mo", interval="1d") for t in tickers}
    now = max(df.index.max() for df in data_map.values())

    edges = {"momentum_edge": MomentumEdge(), "xsec_momentum": XSecMomentumEdge()}
    ae = AlphaEngine(edges=edges, debug=False)
    signals = ae.generate_signals(data_map, now)
    assert len(signals) > 0, "AlphaEngine produced no signals"