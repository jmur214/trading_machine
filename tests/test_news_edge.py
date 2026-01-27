
import sys
import pandas as pd
from pathlib import Path

# Add root to path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from engines.engine_a_alpha.edges.news_sentiment_edge import NewsSentimentEdge

def test_news_edge_logic():
    print("Test 1: Instantiation")
    edge = NewsSentimentEdge()
    print("Success. Params:", edge.params)
    
    print("\nTest 2: Loading History (Mocking Path or Real Path)")
    # We use the real path since we know files exist there
    # But we want to see the prints!
    
    # Mock data map
    data_map = {
        "TSLA": pd.DataFrame({"Close": [100, 101, 102], "date": pd.to_datetime(["2024-01-01", "2024-01-02", "2023-01-03"])}),
        "AAPL": pd.DataFrame({"Close": [150, 151, 152]})
    }
    
    print("\nTest 3: Compute Signals for 2024-01-03")
    now = pd.Timestamp("2024-01-03")
    
    # This should trigger _load_history_lazy
    scores = edge.compute_signals(data_map, now)
    
    print("\nSCORES:", scores)
    
    # Assertions
    if "TSLA" in scores:
        print(f"TSLA Score: {scores['TSLA']}")
    else:
        print("TSLA score missing!")

if __name__ == "__main__":
    test_news_edge_logic()
