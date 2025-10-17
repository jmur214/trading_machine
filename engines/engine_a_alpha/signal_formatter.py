import math


class SignalFormatter:
    """
    Converts scored signals into standardized trade intents for the Risk Engine.
    """

    def __init__(self, debug: bool = True):
        self.debug = debug

    def format(self, scored: dict, timestamp):
        """
        Converts processed signals to a standardized intent list.
        Each item includes: timestamp, ticker, side, score, and metadata.
        """
        intents = []

        for ticker, d in sorted(scored.items()):
            side = str(d.get("side", "none")).lower()
            score = float(d.get("score", 0.0))

            # Skip neutral or invalid signals
            if side not in ("long", "short") or not math.isfinite(score) or abs(score) < 1e-6:
                continue

            meta_edges = d.get("contrib", [])
            if not isinstance(meta_edges, list):
                meta_edges = []

            intent = {
                "timestamp": timestamp,
                "ticker": ticker,
                "side": side,
                "score": round(score, 4),
                "meta": {
                    "edges_triggered": meta_edges,
                    "n_edges": len(meta_edges),
                    "avg_signal": round(
                        sum(c.get("signal", 0.0) for c in meta_edges) / len(meta_edges), 4
                    ) if meta_edges else 0.0,
                },
            }
            intents.append(intent)

        if self.debug:
            if intents:
                brief = [
                    f"{i['ticker']}:{i['side']}({i['score']:+.3f})"
                    for i in intents
                ]
                print(f"[FORMATTER][{timestamp}] → {len(intents)} signals: {', '.join(brief)}")
            else:
                print(f"[FORMATTER][{timestamp}] No actionable signals.")

        return intents