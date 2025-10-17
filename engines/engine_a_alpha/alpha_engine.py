from .signal_collector import SignalCollector
from .signal_processor import SignalProcessor
from .signal_formatter import SignalFormatter
import traceback


class AlphaEngine:
    """
    AlphaEngine
    ------------
    Orchestrates edge modules to produce trade intents.

    Workflow:
        collect()   -> gather raw signals from all edges
        process()   -> weight and threshold
        format()    -> convert to standardized dicts for RiskEngine
    """

    def __init__(self, edges: dict, edge_weights: dict, debug: bool = True):
        self.collector = SignalCollector(edges, edge_weights, debug=debug)
        self.processor = SignalProcessor(threshold=0.03, debug=debug)
        self.formatter = SignalFormatter(debug=debug)
        self.debug = debug
        self.edges = edges

    def generate_signals(self, market_slice: dict, timestamp):
        """Main entry point: returns list of trade intents."""

        # Defensive: handle missing or empty data
        if not market_slice or all(df.empty for df in market_slice.values()):
            if self.debug:
                print(f"[ALPHA][{timestamp}] Market slice empty — skipping.")
            return []

        try:
            # 1️⃣ Collect raw signals from all edges
            raw = self.collector.collect(market_slice)

            # 2️⃣ Score and threshold them
            scored = self.processor.score_signals(raw)

            # 3️⃣ Format into trade intents
            trades = self.formatter.format(scored, timestamp)

            # 4️⃣ Debug output
            if self.debug:
                if trades:
                    compact = [(t['ticker'], t['side'], round(t['score'], 3)) for t in trades]
                    print(f"[ALPHA][{timestamp}] signals: {compact}")
                else:
                    print(f"[ALPHA][{timestamp}] No actionable signals.")
            return trades

        except Exception as e:
            print(f"[ALPHA][ERROR] Exception during signal generation at {timestamp}: {e}")
            if self.debug:
                traceback.print_exc()
            return []