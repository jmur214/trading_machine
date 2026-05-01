import pandas as pd
import numpy as np
from engines.engine_a_alpha.edge_base import EdgeBase
from engines.engine_a_alpha.edge_template import EdgeTemplate


class HerdingEdge(EdgeBase, EdgeTemplate):
    """
    Behavioral edge: cross-sectional herding detection.

    When a large fraction of the universe moves in the same direction
    on the same day (breadth > threshold), generate a contrarian signal
    on the most extreme movers.

    Herding clusters indicate emotional excess and tend to revert.
    """

    EDGE_ID = "herding_v1"
    EDGE_GROUP = "behavioral"
    EDGE_CATEGORY = "contrarian"
    DEFAULT_MIN_ADV_USD = 200_000_000  # $200M/day; cross-sectional but fills are per-ticker per Path-2 audit

    @classmethod
    def get_hyperparameter_space(cls):
        return {
            "breadth_threshold": {"type": "float", "min": 0.70, "max": 0.95},
            "extreme_pctile": {"type": "float", "min": 85.0, "max": 98.0},
            "min_universe_size": {"type": "int", "min": 10, "max": 30},
        }

    def compute_signals(self, data_map, as_of):
        scores = {}
        breadth_thr = self.params.get("breadth_threshold", 0.80)
        extreme_pct = self.params.get("extreme_pctile", 90.0)
        min_universe = self.params.get("min_universe_size", 10)
        min_adv_usd = self.params.get("min_adv_usd", self.DEFAULT_MIN_ADV_USD)

        # Compute daily returns for all tickers above the ADV floor
        # (sub-floor names are excluded from both the breadth calc and the
        # contrarian targeting — they get a 0 score in the output below.)
        ticker_rets = {}
        for t, df in data_map.items():
            if len(df) < 5 or "Close" not in df.columns:
                continue
            if self._below_adv_floor(df, min_adv_usd, ticker=t):
                continue
            ret = float(df["Close"].pct_change().iloc[-1])
            if not np.isnan(ret):
                ticker_rets[t] = ret

        if len(ticker_rets) < min_universe:
            return {t: 0.0 for t in data_map}

        rets = np.array(list(ticker_rets.values()))
        tickers = list(ticker_rets.keys())

        # Breadth: fraction moving in the dominant direction
        up_frac = (rets > 0).mean()
        down_frac = (rets < 0).mean()
        breadth = max(up_frac, down_frac)
        dominant_dir = "up" if up_frac >= down_frac else "down"

        if breadth < breadth_thr:
            # No herding detected
            return {t: 0.0 for t in data_map}

        # Herding detected — contrarian on extreme movers
        abs_rets = np.abs(rets)
        extreme_cutoff = np.percentile(abs_rets, extreme_pct)

        for i, t in enumerate(tickers):
            if abs_rets[i] >= extreme_cutoff:
                # Contrarian: if herd went up, short extremes; if down, long extremes
                if dominant_dir == "up":
                    scores[t] = -1.0
                else:
                    scores[t] = 1.0
            else:
                scores[t] = 0.0

        # Fill any tickers not computed
        for t in data_map:
            if t not in scores:
                scores[t] = 0.0

        return scores
