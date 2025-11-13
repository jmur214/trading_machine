import numpy as np
import pandas as pd

def generate(df: pd.DataFrame):
    """
    10/30 SMA crossover with mild signal scaling.
    """
    if len(df) < 35 or "Close" not in df.columns:
        return {"signal": 0.0, "weight": 1.0}

    fast = df["Close"].rolling(10).mean()
    slow = df["Close"].rolling(30).mean()
    if fast.isna().iloc[-1] or slow.isna().iloc[-1]:
        return {"signal": 0.0, "weight": 1.0}

    diff = fast.iloc[-1] - slow.iloc[-1]
    base = df["Close"].iloc[-1]
    s = np.tanh(diff / max(base, 1e-6))  # small, smooth
    return {"signal": float(s), "weight": 1.0}