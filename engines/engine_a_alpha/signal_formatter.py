class SignalFormatter:
    """
    Turn scored signals into standardized intents for Risk engine.
    """

    def __init__(self, debug: bool = True):
        self.debug = debug

    def format(self, scored: dict, timestamp):
        out = []
        for ticker, d in scored.items():
            side = d.get("side", "none")
            score = float(d.get("score", 0.0))
            if side == "none":
                continue

            intent = {
                "timestamp": timestamp,
                "ticker": ticker,
                "side": side,        # "long" | "short"
                "score": score,      # [-1, 1]
                "meta": {
                    "edges_triggered": d.get("contrib", []),  # list of {edge, signal, weight}
                },
            }
            out.append(intent)

            if self.debug:
                print(f"[FORMATTER] {timestamp} {ticker} side={side} score={score:.3f}")

        return out