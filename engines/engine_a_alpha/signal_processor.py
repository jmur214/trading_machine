import numpy as np
import math


class SignalProcessor:
    """
    Combines per-ticker edge signals into a normalized score in [-1, 1],
    then assigns a trade side if it passes the threshold.
    """

    def __init__(self, threshold: float = 0.03, debug: bool = True):
        self.threshold = float(threshold)
        self.debug = debug

    # ------------------- Helpers -------------------
    def _is_valid(self, x) -> bool:
        return isinstance(x, (int, float, np.number)) and not math.isnan(x)

    # ------------------- Main Logic -------------------
    def score_signals(self, raw_signals: dict) -> dict:
        """
        raw_signals: dict[ticker -> list[{signal, weight, edge}]]
        returns: dict[ticker -> {"score": float, "side": str, "contrib": list}]
        """
        scored = {}

        for ticker, items in raw_signals.items():
            if not items:
                scored[ticker] = {"score": 0.0, "side": "none", "contrib": []}
                continue

            # Filter to numeric contributions only
            contrib = [
                {
                    "edge": it.get("edge", "?"),
                    "signal": float(it["signal"]),
                    "weight": float(it["weight"]),
                }
                for it in items
                if self._is_valid(it.get("signal")) and self._is_valid(it.get("weight")) and it.get("weight") != 0
            ]

            if not contrib:
                scored[ticker] = {"score": 0.0, "side": "none", "contrib": []}
                continue

            tot_w = sum(abs(c["weight"]) for c in contrib)
            if tot_w == 0:
                scored[ticker] = {"score": 0.0, "side": "none", "contrib": contrib}
                continue

            # Weighted average, clipped to [-1, 1]
            weighted = sum(c["signal"] * c["weight"] for c in contrib) / tot_w
            score = float(np.clip(weighted, -1.0, 1.0))

            # Decide side
            if score > self.threshold:
                side = "long"
            elif score < -self.threshold:
                side = "short"
            else:
                side = "none"

            scored[ticker] = {"score": score, "side": side, "contrib": contrib}

            if self.debug:
                preview = [(c["edge"], round(c["signal"], 3), round(c["weight"], 3)) for c in contrib]
                print(f"[ALPHA][PROCESS] {ticker:8s} → score={score:+.3f}, side={side}, edges={preview}")

        if self.debug:
            n_act = sum(1 for v in scored.values() if v["side"] != "none")
            print(f"[ALPHA][PROCESS] Active tickers this step: {n_act}/{len(scored)}")

        return scored