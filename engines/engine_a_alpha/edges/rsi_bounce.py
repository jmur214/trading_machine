import numpy as np
import pandas as pd

def generate(df: pd.DataFrame):
    """
    RSI(14): +1 below 30, -1 above 70, smoothly scaled in between.
    """
    if len(df) < 20 or "Close" not in df.columns:
        return {"signal": 0.0, "weight": 0.8}

    close = df["Close"]
    delta = close.diff()
    up = delta.clip(lower=0.0)
    down = -delta.clip(upper=0.0)

    roll = 14
    avg_up = up.rolling(roll).mean()
    avg_down = down.rolling(roll).mean()
    rs = avg_up / (avg_down + 1e-9)
    rsi = 100 - (100 / (1 + rs))

    r = rsi.iloc[-1]
    if pd.isna(r):
        return {"signal": 0.0, "weight": 0.8}

    if r < 30:
        sig = 1.0
    elif r > 70:
        sig = -1.0
    else:
        # smoothly push toward zero around 50
        sig = np.tanh((50.0 - r) / 20.0)

    return {"signal": float(sig), "weight": 0.8}