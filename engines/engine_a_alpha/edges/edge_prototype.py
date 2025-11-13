EDGE_NAME = "test_edge"
EDGE_GROUP = "technical"
EDGE_PARAMS = {}

from debug_config import is_debug_enabled

def is_info_enabled() -> bool:
    from debug_config import DEBUG_LEVELS
    return DEBUG_LEVELS.get("TEST_EDGE_INFO", False)

def compute_signals(df_map, now, cfg=None):
    """
    Momentum-style test edge that uses configurable lookback and threshold parameters.
    Emits +1 for bullish momentum, -1 for bearish momentum, and 0 for neutral.
    """

    lookback = EDGE_PARAMS.get("lookback", 20)
    threshold = EDGE_PARAMS.get("threshold", 0.02)

    if is_debug_enabled("TEST_EDGE") or is_info_enabled():
        print(f"[TEST_EDGE][DEBUG] Running compute_signals at {now} (lookback={lookback}, threshold={threshold})")

    scores = {}
    for ticker, df in df_map.items():
        if len(df) < lookback + 1 or "Close" not in df.columns:
            continue

        if now not in df.index:
            closest_idx = df.index.get_indexer([now], method="nearest")[0]
            now = df.index[closest_idx]

        idx = df.index.get_loc(now)
        if idx < lookback:
            continue

        close = df["Close"].iloc[idx - lookback: idx + 1]
        ret = (close.iloc[-1] / close.iloc[0]) - 1.0

        if ret > threshold:
            signal = 1.0
        elif ret < -threshold:
            signal = -1.0
        else:
            signal = 0.0

        scores[ticker] = signal

        if is_debug_enabled("TEST_EDGE") or is_info_enabled():
            print(f"[TEST_EDGE][DEBUG] {ticker}: return={ret:.4f}, signal={signal}")

    if is_debug_enabled("TEST_EDGE") or is_info_enabled():
        print(f"[TEST_EDGE][DEBUG] Returning scores: {scores}")

    return scores