import numpy as np
import pandas as pd

def generate(df: pd.DataFrame):
    """
    20-period Bollinger bands. +1 above upper band, -1 below lower band,
    smooth z-distance inside bands.
    """
    if len(df) < 25 or "Close" not in df.columns:
        return {"signal": 0.0, "weight": 1.2}

    close = df["Close"]
    ma = close.rolling(20).mean()
    sd = close.rolling(20).std()

    mu = ma.iloc[-1]
    sigma = sd.iloc[-1]
    px = close.iloc[-1]

    if pd.isna(mu) or pd.isna(sigma) or sigma <= 0:
        return {"signal": 0.0, "weight": 1.2}

    upper = mu + 2 * sigma
    lower = mu - 2 * sigma

    if px > upper:
        sig = 1.0
    elif px < lower:
        sig = -1.0
    else:
        # scale by z-score, but softly
        z = (px - mu) / (2 * sigma)
        sig = float(np.tanh(z))

    return {"signal": float(sig), "weight": 1.2}