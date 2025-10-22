import numpy as np
import pandas as pd

EDGE_NAME = "momentum_edge"
EDGE_GROUP = "technical"


def generate_signals(df_map, now, cfg=None):
    """
    Momentum edge:
    - Long when short-term MA crosses above long-term MA.
    - Short when short-term MA crosses below long-term MA.
    - Signal strength based on normalized difference between MAs.
    """

    signals = []
    short_window = 10
    long_window = 40

    for ticker, df in df_map.items():
        if len(df) < long_window + 2 or "Close" not in df.columns:
            continue

        close = df["Close"].astype(float)

        # Compute moving averages
        ma_short = close.rolling(short_window).mean()
        ma_long = close.rolling(long_window).mean()

        # Compute momentum delta
        delta = ma_short - ma_long
        prev_delta = delta.shift(1)

        # Check for crossover event
        if delta.iloc[-1] > 0 and prev_delta.iloc[-1] <= 0:
            side = "long"
        elif delta.iloc[-1] < 0 and prev_delta.iloc[-1] >= 0:
            side = "short"
        else:
            side = None

        if side:
            # Strength = normalized distance between MAs
            rel_strength = np.tanh((delta.iloc[-1] / (close.iloc[-1] * 0.02)))
            signals.append({
                "ticker": ticker,
                "side": side,
                "strength": float(abs(rel_strength)),
                "edge": EDGE_NAME,
                "edge_group": EDGE_GROUP
            })

    return signals