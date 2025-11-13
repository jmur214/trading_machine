import numpy as np
import pandas as pd

EDGE_NAME = "rsi_reversal"
EDGE_GROUP = "technical"

def generate(df_map, now, cfg=None):
    """
    RSI reversal edge: long when RSI < 30, short when RSI > 70.
    Works across all tickers in df_map.
    """
    results = {}

    for ticker, df in df_map.items():
        if len(df) < 20 or "Close" not in df.columns or now not in df.index:
            results[ticker] = 0.0
            continue

        close = df["Close"]
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / (avg_loss + 1e-9)
        rsi = 100 - (100 / (1 + rs))

        latest_rsi = rsi.loc[now] if now in rsi.index else np.nan
        if np.isnan(latest_rsi):
            results[ticker] = 0.0
            continue

        if latest_rsi < 30:
            signal = 1.0
        elif latest_rsi > 70:
            signal = -1.0
        else:
            signal = np.tanh((50 - latest_rsi) / 20.0)

        results[ticker] = float(signal)

    return results