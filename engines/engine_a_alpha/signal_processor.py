import numpy as np

class SignalProcessor:
    """
    Combine per-ticker edge signals into a single score in [-1, +1],
    then choose side based on a low threshold so we actually trade.
    """

    def __init__(self, threshold: float = 0.03, debug: bool = True):
        self.threshold = float(threshold)
        self.debug = debug

    def score_signals(self, raw_signals: dict):
        """
        raw_signals: dict[ticker -> list[{"signal": float, "weight": float, "edge": str}]]
        returns: dict[ticker -> {"score": float, "side": str, "contrib": list}]
        """
        scored = {}

        for ticker, items in raw_signals.items():
            if not items:
                scored[ticker] = {"score": 0.0, "side": "none", "contrib": []}
                continue

            # keep only valid numeric contributions
            contrib = []
            for it in items:
                s = it.get("signal", 0.0)
                w = it.get("weight", 0.0)
                if isinstance(s, (int, float)) and isinstance(w, (int, float)) and w != 0:
                    contrib.append({"edge": it.get("edge", "?"), "signal": float(s), "weight": float(w)})

            if not contrib:
                scored[ticker] = {"score": 0.0, "side": "none", "contrib": []}
                continue

            tot_w = sum(c["weight"] for c in contrib)
            weighted = sum(c["signal"] * c["weight"] for c in contrib) / tot_w
            score = float(np.clip(weighted, -1.0, 1.0))

            if score > self.threshold:
                side = "long"
            elif score < -self.threshold:
                side = "short"
            else:
                side = "none"

            scored[ticker] = {"score": score, "side": side, "contrib": contrib}

            if self.debug:
                keep = [(c["edge"], round(c["signal"], 3), round(c["weight"], 3)) for c in contrib]
                print(f"[ALPHA][DEBUG] {ticker}: score={score:.3f} side={side} contrib={keep}")

        return scored