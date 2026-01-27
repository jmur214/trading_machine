# test_alpaca_live.py
from orchestration.mode_controller import ModeController, CachedCSVLiveFeed

if __name__ == "__main__":
    controller = ModeController(project_root=".")
    feed = CachedCSVLiveFeed(
        cache_dir="./data/processed",
        tickers=["AAPL"],
        timeframe="1D"
    )

    # Run only a few bars to confirm Alpaca connection and execution
    controller.run_live(
        feed=feed,
        poll_seconds=3,
        dry_run=False,        # actual Alpaca call
        use_alpaca=True,      # route via your Alpaca adapter
        max_steps=3           # limit to 3 bars so it doesn’t loop forever
    )