# engines/engine_a_alpha/edges/test_edge.py
EDGE_NAME = "test_edge"
EDGE_GROUP = "technical"

def compute_signals(df_map, now, cfg=None):
    """
    Simple placeholder edge that emits a long (+1) signal every 5th bar
    for testing the Alpha → Risk → Logger chain.
    """
    print(f"[TEST_EDGE][DEBUG] Running compute_signals at {now}")

    scores = {}
    for ticker, df in df_map.items():
        if len(df) < 20:
            continue

        # Find closest bar if 'now' not in index
        if now not in df.index:
            closest_idx = df.index.get_indexer([now], method="nearest")[0]
            now = df.index[closest_idx]
            print(f"[TEST_EDGE][DEBUG] Adjusted timestamp for {ticker}: {now}")

        idx = df.index.get_loc(now)
        print(f"[TEST_EDGE][DEBUG] {ticker}: index position {idx} of {len(df)}")

        # Emit a signal every 5 bars for visibility
        if idx % 5 == 0:
            scores[ticker] = 1.0   # long bias
        else:
            scores[ticker] = -1.0  # short bias (for variation)

    print(f"[TEST_EDGE][DEBUG] Returning scores: {scores}")
    return scores