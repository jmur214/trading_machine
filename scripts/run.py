# scripts/run.py
import sys
from pathlib import Path

# 👇 Add the project root (the parent of "scripts/") to the Python path
sys.path.append(str(Path(__file__).resolve().parents[1]))

from orchestration.mode_controller import ModeController, CachedCSVLiveFeed

if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    mc = ModeController(project_root=root)

    # === 1️⃣ Run Backtest (existing functionality) ===
    mc.run_backtest()

    # === 2️⃣ Optional: Run Paper Trade simulation ===
    # mc.run_paper(fill_bar_delay=1, sleep_seconds=0.0)

    # === 3️⃣ Optional: Run Live (Dry Run) mode ===
    # feed = CachedCSVLiveFeed(
    #     cache_dir=str(root / "data" / "processed"),
    #     tickers=mc.tickers,
    #     timeframe=mc.timeframe,
    # )
    # mc.run_live(feed, poll_seconds=3.0, dry_run=True, max_steps=5)