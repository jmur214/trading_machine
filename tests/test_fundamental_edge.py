from engines.engine_a_alpha.edges.fundamental_value import ValueTrapEdge
from engines.data_manager.data_manager import DataManager
import pandas as pd

def test_value_edge():
    print("[TEST] Initializing ValueTrapEdge...")
    edge = ValueTrapEdge({"max_pe": 100.0, "max_rsi": 100.0}) # Generous P/E and RSI to ensure trigger
    
    print("[TEST] Fetching data for AAPL...")
    dm = DataManager()
    df = dm.load_cached("AAPL", "1d")
    
    # Mock data if needed
    if df is None or df.empty:
        print("[TEST] Generating mock data...")
        dates = pd.date_range("2023-01-01", periods=100)
        # Create a sharp drop at the end to trigger RSI < 30
        prices = [100.0] * 80 + [100.0 * (0.95 ** i) for i in range(20)]
        df = pd.DataFrame({
            "Close": prices,
            "Volume": [1000] * 100
        }, index=dates)
    
    data_map = {"AAPL": df}
    
    print("[TEST] Computing signals...")
    signals = edge.compute_signals(data_map, df.index[-1])
    
    print(f"[TEST] Score for AAPL: {signals.get('AAPL')}")
    
    # Check cache
    assert "AAPL" in edge.fundamental_cache
    print(f"[TEST] Cached Fundamentals: {edge.fundamental_cache['AAPL']}")

if __name__ == "__main__":
    test_value_edge()
