import pandas as pd
import numpy as np
from engines.engine_a_alpha.edge_base import EdgeBase
from engines.engine_a_alpha.edge_template import EdgeTemplate


class SeasonalityEdge(EdgeBase, EdgeTemplate):
    """
    Stat/Quant edge: calendar seasonality patterns.

    Computes historical average returns by day-of-week or month-of-year
    per ticker. Generates long signals when the current period historically
    has a win rate above threshold with positive average return.
    """

    EDGE_ID = "seasonality_v1"
    EDGE_GROUP = "stat_quant"
    EDGE_CATEGORY = "seasonality"

    @classmethod
    def get_hyperparameter_space(cls):
        return {
            "mode": {"type": "categorical", "choices": ["day_of_week", "month_of_year"]},
            "min_win_rate": {"type": "float", "min": 0.55, "max": 0.75},
            "min_avg_return": {"type": "float", "min": 0.0005, "max": 0.005},
            "lookback_years": {"type": "int", "min": 2, "max": 10},
        }

    def compute_signals(self, data_map, as_of):
        scores = {}
        mode = self.params.get("mode", "day_of_week")
        min_wr = self.params.get("min_win_rate", 0.60)
        min_avg = self.params.get("min_avg_return", 0.001)
        lookback_years = self.params.get("lookback_years", 5)

        for t, df in data_map.items():
            if len(df) < 252 or "Close" not in df:
                continue

            close = df["Close"]
            rets = close.pct_change().dropna()

            # Filter to lookback window
            cutoff = as_of - pd.DateOffset(years=lookback_years)
            rets = rets[rets.index >= cutoff]
            if len(rets) < 100:
                scores[t] = 0.0
                continue

            # Group by calendar period
            if mode == "day_of_week":
                current_period = as_of.dayofweek if isinstance(as_of, pd.Timestamp) else 0
                groups = rets.groupby(rets.index.dayofweek)
            else:
                current_period = as_of.month if isinstance(as_of, pd.Timestamp) else 1
                groups = rets.groupby(rets.index.month)

            if current_period not in groups.groups:
                scores[t] = 0.0
                continue

            period_rets = groups.get_group(current_period)
            win_rate = float((period_rets > 0).mean())
            avg_ret = float(period_rets.mean())

            if win_rate >= min_wr and avg_ret >= min_avg:
                scores[t] = 1.0
            elif (1 - win_rate) >= min_wr and avg_ret <= -min_avg:
                scores[t] = -1.0
            else:
                scores[t] = 0.0

        return scores
