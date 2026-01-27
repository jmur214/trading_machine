---
description: Start-to-Finish Trading Machine Lifecycle
---

# Full Lifecycle Workflow

This is the master workflow to go from data to feedback.

**Agent Instruction**: You are authorized to run the commands below autonomously using `// turbo`. If a step fails, stop and ask for help.

1.  **Step 1: Data Check**
    *   Check if `data/processed` has recent files. If not, fetch data:
        ```bash
        python -m scripts.fetch_data --tickers AAPL MSFT SPY --start 2024-01-01 --end 2025-01-01 --timeframe 1d
        ```

2.  **Step 2: Run Backtest**
    *   Execute the standard backtest:
        ```bash
        // turbo
        python -m scripts.run_backtest
        ```

3.  **Step 3: Analytics & Feedback**
    *   Run the performance summary:
        ```bash
        // turbo
        python -m analytics.performance_summary
        ```
    *   Update Governor weights (Sandbox Mode for safety):
        ```bash
        // turbo
        python -m analytics.edge_feedback --mode sandbox
        ```

4.  **Step 4: Health Check**
    *   Run diagnostics to ensure system integrity:
        ```bash
        // turbo
        python -m scripts.run_diagnostics
        ```

5.  **Step 5: Reporting**
    *   Create a summary artifact for the user.
    *   Include the `run_id`, key metrics (Sharpe, PnL), and any health warnings.
