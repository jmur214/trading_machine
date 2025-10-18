import numpy as np
import pandas as pd

EDGE_NAME = "atr_breakout"
EDGE_GROUP = "technical"

def generate(df_map, now, cfg=None):
    """
    ATR breakout edge: signals +1 if current range > 1.5× ATR average (volatility spike).
    Works across all tickers in df_map.
    """
    results = {}

    for ticker, df in df_map.items():
        if len(df) < 25 or not all(col in df.columns for col in ["High", "Low", "Close"]):
            results[ticker] = 0.0
            continue

        if now not in df.index:
            results[ticker] = 0.0
            continue

        high, low, close = df["High"], df["Low"], df["Close"]

        # True range & ATR
        prev_close = close.shift(1)
        tr = np.maximum(high - low, np.maximum(abs(high - prev_close), abs(low - prev_close)))
        atr = tr.rolling(14).mean()

        # Current values
        row = df.loc[now]
        range_now = row["High"] - row["Low"]
        atr_now = atr.loc[now] if now in atr.index else np.nan

        if np.isnan(atr_now) or atr_now == 0:
            results[ticker] = 0.0
            continue

        ratio = range_now / atr_now
        signal = np.tanh((ratio - 1.0) * 2.0)  # positive when vol expands sharply
        results[ticker] = float(signal)

    return results