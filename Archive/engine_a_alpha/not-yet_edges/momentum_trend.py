import numpy as np
import pandas as pd

EDGE_NAME = "momentum_trend"
EDGE_GROUP = "technical"

def generate(df_map, now, cfg=None):
    """
    Momentum/trend edge: compares price to moving average.
    Emits positive signal if Close > MA, negative otherwise.
    """
    results = {}

    for ticker, df in df_map.items():
        if len(df) < 50 or "Close" not in df.columns or now not in df.index:
            results[ticker] = 0.0
            continue

        ma = df["Close"].rolling(50).mean()
        if now not in ma.index:
            results[ticker] = 0.0
            continue

        close_now = df.loc[now, "Close"]
        ma_now = ma.loc[now]

        if np.isnan(close_now) or np.isnan(ma_now):
            results[ticker] = 0.0
            continue

        signal = np.tanh((close_now / ma_now - 1.0) * 10.0)
        results[ticker] = float(signal)

    return results