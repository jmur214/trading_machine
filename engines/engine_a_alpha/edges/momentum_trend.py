import numpy as np
import pandas as pd

def generate(df: pd.DataFrame):
    """
    Momentum-based edge: compares short-term vs long-term momentum.
    Returns signal ∈ [-1, +1].
    """
    if len(df) < 50 or "Close" not in df.columns:
        return {"signal": 0.0, "weight": 1.0}

    close = df["Close"]
    short_ret = close.pct_change(5).iloc[-1]
    long_ret = close.pct_change(20).iloc[-1]

    # Smooth and normalize signal
    raw_signal = np.tanh((short_ret - long_ret) * 10)

    return {"signal": float(raw_signal), "weight": 1.0}