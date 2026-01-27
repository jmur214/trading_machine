
import os
import sys
import argparse
import logging
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.data_manager.data_manager import DataManager
from debug_config import is_debug_enabled

# Setup logging
logging.basicConfig(level=logging.INFO, format="[UPDATE_DATA] %(message)s")
log = logging.getLogger("UpdateData")

def main():
    parser = argparse.ArgumentParser(description="Smart Data Updater - Fetches missing data up to today.")
    parser.add_argument("--lookback_days", type=int, default=3, help="How far back to check for missing recent data")
    parser.add_argument("--force_full", action="store_true", help="Force full redownload (2 years)")
    args = parser.parse_args()

    # Load config
    # We read from the centralized config
    import json
    config_path = Path(__file__).parent.parent / "config" / "universe.json"
    try:
        with open(config_path, "r") as f:
            CORE_UNIVERSE = json.load(f)
    except Exception as e:
        log.error(f"Failed to load universe from {config_path}: {e}")
        # Fallback default
        CORE_UNIVERSE = ["SPY", "QQQ"]

    dm = DataManager()
    
    end_date = datetime.now()
    
    if args.force_full:
        start_date = end_date - timedelta(days=730) # 2 years
        log.info(f"Forcing full update from {start_date.date()} to {end_date.date()}...")
        dm.ensure_data(CORE_UNIVERSE, start_date, end_date)
    else:
        # incremental update
        start_date = end_date - timedelta(days=args.lookback_days)
        log.info(f"Checking for updates from {start_date.date()} to {end_date.date()}...")
        
        # We assume ensure_data handles the "incremental" check internally via cache inspection
        # But ensure_data currently prefers cache if it exists at all.
        # We need to explicitly check if cache is stale.
        # For now, we'll rely on ensure_data's ability to fetch if missing, 
        # BUT since we want to *append* active data, we might need a force-fetch of the tail.
        
        # Actually, simpler strategy: Just ask for the last N days. 
        # DataManager.ensure_data() logic:
        #  - if cache exists and > 10 rows, use it.
        #  - This effectively PREVENTS updates if cache is stale but present.
        
        # FIX: We must detect staling.
        # Let's peek at one key file (SPY)
        spy_df = dm.load_cached("SPY", "1d")
        if spy_df is not None and not spy_df.empty:
            last_dt = spy_df.index[-1]
            if last_dt < (end_date - timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0):
                log.info(f"Data appears stale (Last SPY date: {last_dt.date()}). Triggering refresh.")
                # Force fetch the missing tail and merge?
                # Or just force re-download of the active range if it's small?
                # DataManager doesn't support "merge" natively yet. 
                # Simplest robust fix: If stale, re-download the last 30 days and overwrite? 
                # No, that loses history if we overwrite.
                # True fix: Re-download full history if stale. Bandwidth is cheap.
                full_start = end_date - timedelta(days=730)
                dm.ensure_data(CORE_UNIVERSE, full_start, end_date)
            else:
                log.info("Data appears up to date.")
        else:
            log.info("No cache found. Downloading full history.")
            full_start = end_date - timedelta(days=730)
            dm.ensure_data(CORE_UNIVERSE, full_start, end_date)

    log.info("Data update complete.")

if __name__ == "__main__":
    main()
