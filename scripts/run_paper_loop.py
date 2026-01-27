
import sys
import os
import time
import logging
from pathlib import Path

# Add project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestration.mode_controller import ModeController, CachedCSVLiveFeed

def main():
    print("==================================================")
    print("   PAPER TRADING DASHBOARD (Backend)")
    print("==================================================")
    print("Mode: LIVE (Dry Run)")
    print("Feed: Cached CSVs (requires 'scripts/update_data.py' running)")
    print("Interval: 60 seconds")
    print("--------------------------------------------------")

    root_dir = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # Initialize Controller
    try:
        controller = ModeController(project_root=root_dir)
    except Exception as e:
        print(f"[FATAL] Could not initialize ModeController: {e}")
        return

    # Setup Feed (Monitors data/processed/*.csv)
    cache_dir = root_dir / "data" / "processed"
    feed = CachedCSVLiveFeed(
        cache_dir=str(cache_dir),
        tickers=controller.tickers,
        timeframe=controller.timeframe
    )
    
    print("[INFO] Starting polling loop. Press Ctrl+C to stop.")
    
    try:
        # Run Live Loop (Infinite)
        controller.run_live(
            feed=feed,
            poll_seconds=60.0,
            dry_run=True,
            max_steps=None # Infinite
        )
    except KeyboardInterrupt:
        print("\n[INFO] Stopping paper trading loop...")
    except Exception as e:
        print(f"[ERROR] Loop crashed: {e}")

if __name__ == "__main__":
    main()
