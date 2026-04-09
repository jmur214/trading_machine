
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

def update_all_data(force_full: bool = False, lookback_days: int = 3):
    """
    Programmatic entry point for data updating.
    """
    # Load config
    import json
    config_path = Path(__file__).parent.parent / "config" / "universe.json"
    try:
        with open(config_path, "r") as f:
            CORE_UNIVERSE = json.load(f)
    except Exception as e:
        log.error(f"Failed to load universe from {config_path}: {e}")
        CORE_UNIVERSE = ["SPY", "QQQ"]

    dm = DataManager()
    end_date = datetime.now()
    
    if force_full:
        start_date = end_date - timedelta(days=730)
        log.info(f"Forcing full update from {start_date.date()} to {end_date.date()}...")
        dm.ensure_data(CORE_UNIVERSE, start_date, end_date)
    else:
        # Check staleness
        spy_df = dm.load_cached("SPY", "1d")
        needs_update = False
        
        if spy_df is not None and not spy_df.empty:
            last_dt = spy_df.index[-1]
            # If last data is older than yesterday
            if last_dt < (end_date - timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0):
                log.info(f"Data stale (Last SPY: {last_dt.date()}). Downloading full history.")
                needs_update = True
            else:
                log.info("Data appears up to date.")
        else:
            log.info("No cache found. Downloading full history.")
            needs_update = True
            
        if needs_update:
            full_start = end_date - timedelta(days=730)
            dm.ensure_data(CORE_UNIVERSE, full_start, end_date)

    log.info("Data update complete.")

def main():
    parser = argparse.ArgumentParser(description="Smart Data Updater")
    parser.add_argument("--lookback_days", type=int, default=3)
    parser.add_argument("--force_full", action="store_true")
    args = parser.parse_args()
    
    update_all_data(force_full=args.force_full, lookback_days=args.lookback_days)

if __name__ == "__main__":
    main()
