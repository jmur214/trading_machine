import numpy as np
import pandas as pd

def generate(df: pd.DataFrame):
    """
    ATR breakout edge: signals +1 if current range > 1.5× ATR average (volatility spike).
    """
    if len(df) < 25 or not all(col in df.columns for col in ["High", "Low", "Close"]):
        return {"signal": 0.0, "weight": 1.0}

    high, low, close = df["High"], df["Low"], df["Close"]

    # True range
    prev_close = close.shift(1)
    tr = np.maximum(high - low, np.maximum(abs(high - prev_close), abs(low - prev_close)))
    atr = tr.rolling(14).mean()

    # Breakout measure
    range_now = high.iloc[-1] - low.iloc[-1]
    atr_now = atr.iloc[-1]

    if np.isnan(atr_now) or atr_now == 0:
        return {"signal": 0.0, "weight": 1.0}

    ratio = range_now / atr_now
    signal = np.tanh((ratio - 1.0) * 2.0)  # positive when vol expands sharply

    return {"signal": float(signal), "weight": 1.0}