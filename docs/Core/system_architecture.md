# Comprehensive System Architecture

## The Core 4 Pipeline (The "Fund Manager")
This is the classical deterministic trading system responsible for keeping the portfolio safe and sized correctly.
1. **Data Manager (`engines/data_manager`):** Downloads and caches OHLCV + Fundamentals from Alpaca/YFinance.
2. **Engine A: Alpha (`engines/engine_a_alpha`):** Receives data, checks current market Regimes, evaluates mathematical rules (Edges), and returns a raw signal score (-1.0 to 1.0) for every ticker.
3. **Engine B: Risk (`engines/engine_b_risk`):** Transforms the raw signals into position-sizing targets by factoring in volatility (ATR) and correlation penalties.
4. **Engine C: Portfolio (`engines/engine_c_portfolio`):** Executes the orders needed to transition from the current allocation to the target allocation, while strictly maintaining the accounting identity (`equity = cash + market_value`).

## Orchestration Layer
The `ModeController` (`orchestration/mode_controller.py`) binds these 4 components together. It allows the exact same logic pipeline to run in:
- **Backtest Mode:** Slices data bar-by-bar locally.
- **Paper Mode:** Streams data via websockets and simulates execution.
- **Live Mode:** Plumbs the final Portfolio engine diffs straight to Broker REST APIs.

## The Evolutionary Layer (The "Hunter")
This runs asynchronously in parallel to the main system, attempting to act like a Quant Researcher.
- **Engine D: Research (`engines/engine_d_research`):** Randomly mutates parameters, walks them forward, and measures out-of-sample degradation.
- **The Governor:** A feedback-loop daemon that monitors live/paper trade outcomes and quietly adjusts the weights of the edges via JSON config files.

---
**For details on specific classes and mathematical rules within each module, reference the `index.md` files located directly inside each Python directory.**
