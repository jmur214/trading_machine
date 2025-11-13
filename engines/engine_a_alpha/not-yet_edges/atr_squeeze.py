from utils.math_utils import atr
import numpy as np

def edge(df, atr_period=14, lookback=60, pct=20):
    if len(df) < lookback + atr_period + 1:
        return 0
    a = atr(df, period=atr_period)
    window = a.iloc[-lookback:]
    thresh = np.percentile(window.values, pct)
    # If low ATR + price above recent mean -> long bias; below mean -> short
    price = df["Close"].iloc[-1]
    mean = df["Close"].rolling(20).mean().iloc[-1]
    if a.iloc[-1] <= thresh and price > mean:
        return 1
    if a.iloc[-1] <= thresh and price < mean:
        return -1
    return 0