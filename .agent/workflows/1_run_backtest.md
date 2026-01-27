---
description: Run a standard full backtest
---

# Run Backtest Workflow

This workflow guides you through running a full backtest of the system.

1.  **Check Data Availability**
    *   Check if there is recent data in `data/processed/`.
    *   If not, or if the user requests fresh data, run:
        ```bash
        python -m scripts.fetch_data --tickers AAPL MSFT SPY --start 2022-01-01 --end 2025-01-01 --timeframe 1d
        ```

2.  **Run Backtest**
    *   Execute the backtest script:
        ```bash
        // turbo
        python -m scripts.run_backtest
        ```
    *   **Note**: Ensure you capture the `run_id` from the output.

3.  **Verify Output**
    *   Check that logs were created in `data/trade_logs/<run_id>/`.
    *   Run a quick performance summary:
        ```bash
        // turbo
        python -m analytics.performance_summary
        ```

4.  **Launch Dashboard (Optional)**
    *   If the user wants to see the results visually, offer to launch the dashboard:
        ```bash
        python -m cockpit.dashboard
        ```
