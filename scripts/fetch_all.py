
import os
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure we can find the engines module
sys.path.append(os.getcwd())

from engines.data_manager.data_manager import DataManager

def main():
    load_dotenv()
    
    # Check credentials
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    
    if not api_key:
        print("[FETCH_ALL] ⚠️  ALPACA_API_KEY not found in environment. Data fetch may fail or fall back to mock.")
    
    # Load settings
    config_path = Path("config/backtest_settings.json")
    if not config_path.exists():
        print(f"[FETCH_ALL] Error: {config_path} not found.")
        return

    with open(config_path, "r") as f:
        cfg = json.load(f)
        
    tickers = cfg.get("tickers", [])
    print(f"[FETCH_ALL] Found {len(tickers)} tickers in config: {tickers[:5]}...")
    
    # Instantiating DataManager with proper auth
    dm = DataManager(
        cache_dir="data/processed",
        api_key=api_key,
        secret_key=secret_key,
        base_url=os.getenv("ALPACA_BASE_URL")
    )
    
    # We want a generous history for backtesting (e.g. 2 years)
    start_date = "2023-01-01"
    end_date = "2024-12-31" 
    
    print(f"[FETCH_ALL] Ensuring data from {start_date} to {end_date}...")
    
    # Force 'ensure_data' to fetch
    data_map = dm.ensure_data(
        tickers=tickers,
        start=start_date,
        end=end_date,
        timeframe="1d"
    )
    
    print(f"[FETCH_ALL] Data available for: {list(data_map.keys())}")
    print(f"[FETCH_ALL] Done. Check data/processed/")

if __name__ == "__main__":
    main()
