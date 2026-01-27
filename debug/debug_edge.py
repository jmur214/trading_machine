
import sys
import pandas as pd
from engines.engine_a_alpha.edges.xsec_momentum import XSecMomentumEdge

# Mock config
params = {
    "lookback": 10,
    "vol_window": 20,
    "vol_target": 0.10,
    "neutralize": "dollar",
    "top_n": 1,
    "bottom_n": 1
}

# Load data for multiple tickers
data_map = {}
tickers = ["AAPL", "MSFT", "SPY"]
for t in tickers:
    try:
        df = pd.read_csv(f"data/processed/{t}_1d.csv")
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df.set_index('timestamp', inplace=True)
        data_map[t] = df
        print(f"Loaded {t}: {len(df)} rows")
    except Exception as e:
        print(f"Error loading {t}: {e}")

# Test at a recent date where all have data
common_idx = None
for t, df in data_map.items():
    if common_idx is None:
        common_idx = df.index
    else:
        common_idx = common_idx.intersection(df.index)

if common_idx.empty:
    print("No common dates found!")
    sys.exit(1)

test_date = common_idx[-1]
print(f"Testing at {test_date}")

# Init Edge
edge = XSecMomentumEdge()
edge.set_params(params)

# compute signals
try:
    sigs = edge.compute_signals(data_map, test_date)
    print("Signals:", sigs)
except Exception as e:
    print(f"Error computing signals: {e}")
    import traceback
    traceback.print_exc()
