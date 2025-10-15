import numpy as np
import pandas as pd

def generate(df: pd.DataFrame):
    """
    RSI reversal edge: long when RSI < 30, short when RSI > 70.
    Smooths values near 50.
    """
    if len(df) < 20 or "Close" not in df.columns:
        return {"signal": 0.0, "weight": 0.8}

    close = df["Close"]
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    rsi = 100 - (100 / (1 + rs))

    latest_rsi = rsi.iloc[-1]
    if np.isnan(latest_rsi):
        return {"signal": 0.0, "weight": 0.8}

    if latest_rsi < 30:
        signal = 1.0
    elif latest_rsi > 70:
        signal = -1.0
    else:
        signal = np.tanh((50 - latest_rsi) / 20.0)

    return {"signal": float(signal), "weight": 0.8}