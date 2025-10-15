from .signal_collector import SignalCollector
from .signal_processor import SignalProcessor
from .signal_formatter import SignalFormatter

class AlphaEngine:
    """
    - generate_signals(market_slice, timestamp) -> list[intents]
    """

    def __init__(self, edges: dict, edge_weights: dict, debug: bool = True):
        self.collector = SignalCollector(edges, edge_weights, debug=debug)
        self.processor = SignalProcessor(threshold=0.03, debug=debug)
        self.formatter = SignalFormatter(debug=debug)
        self.debug = debug

    def generate_signals(self, market_slice: dict, timestamp):
        raw = self.collector.collect(market_slice)
        scored = self.processor.score_signals(raw)
        trades = self.formatter.format(scored, timestamp)

        if self.debug:
            nz = [(t['ticker'], t['side'], round(t['score'], 3)) for t in trades]
            if nz:
                print(f"[ALPHA][{timestamp}] non-zero signals: {nz}")

        return trades