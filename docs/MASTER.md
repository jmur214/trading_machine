# Trading Machine: Master System Documentation

> **Status:** Active / Evolution Phase
> **Version:** 2.0 (Adaptive Architecture)

---

## PART 1: SYSTEM OVERVIEW (High Level)

### 1. Philosophy & Vision
The Trading Machine is not merely a backtesting script or a signal generator. It is an **Adaptive Evolutionary Lab**.
Its core purpose is to simulate the workflow of a professional quantitative research desk, but automated.
1.  **Observe:** Ingest raw market data (Price, Fundamentals, News).
2.  **Hypothesize:** Generate trading signals via "Edges" (Strategies).
3.  **Allocate:** Decide how much capital to bet on each idea (Portfolio Policy).
4.  **Execute:** Simulate trades with realistic limits, slippage, and costs.
5.  **Learn:** Analyze performance and automatically adjust strategy weights (The Governor).
6.  **Evolve:** Mutate parameters and discover new edges (The Discovery Engine).

The system seamlessly transitions between **Backtest**, **Paper Trading**, and **Live Trading** using the same core logic—only the Data Source and Execution Adapter change.

### 2. How It Works (The Lifecycle)
1.  **The Loop:** The system runs bar-by-bar (daily or intraday). It doesn't look ahead.
2.  **The Brain (Alpha):** At each time step, multiple "Edges" (e.g., RSI Bounce, Value Trap) look at history and vote on tickers.
3.  **The Accountant (Portfolio):** The Portfolio Engine calculates target weights based on these votes and the current capital.
4.  **The Guard (Risk):** The Risk Engine checks these targets against safety rules (Max Exposure, Volatility Caps) and issues specific Orders.
5.  **The Broker (Execution):** The Orders are filled at the next available price (Open/Close), incorporating fees and slippage.
6.  **The Feedback:** Every trade and daily snapshot is logged. The "Governor" reads these logs to promote winning edges and demote losers.

---

## PART 2: TECHNICAL DEEP DIVE

### 1. Data Layer (`engines/data_manager`)
*   **Role:** The bedrock of truth. Handles fetching, normalizing, and caching.
*   **Sources:**
    *   **Alpaca:** Primary source for Price/Volume (OHLCV).
    *   **YFinance:** Fallback and tertiary source.
    *   **Static CSV:** (Crucial Fix) Used for predictable Fundamental Data backtesting to avoid lookahead bias.
    *   **Synthetic:** Generates random market data (`SYNTH-A`) for validation.
*   **Key Logic:** `_normalize_dataframe` ensures every internal component sees the same columns (`Open`, `High`, `Low`, `Close`, `Volume`, `ATR`).
*   **Caching:** Uses Parquet/CSV in `data/processed` to speed up repeated runs.

### 2. Engine A: Alpha (`engines/engine_a_alpha`)
*   **Role:** Signal Generation.
*   **Structure:**
    *   **Edges:** Individual strategy classes (e.g., `RSIBounceEdge`) located in `edges/`. They output a raw score (-1.0 to +1.0).
    *   **SignalCollector:** Iterates through all active edges and harvests scores.
    *   **SignalProcessor:** Normalizes scores, applies hygiene (e.g., `min_history`), and ensembles them if multiple edges fire on one ticker.
    *   **RegimeDetector:** (Cognition) Checks SPY/Market State to tag signals (e.g., "Bull", "High Vol").
*   **Output:** A list of standardized `Signal` dictionaries: `{'ticker': 'AAPL', 'side': 'long', 'strength': 0.8, 'meta': {...}}`.

### 3. Engine C: Portfolio (`engines/engine_c_portfolio`)
*   **Role:** The Allocator & State Keeper.
*   **Key Logic:**
    *   **PortfolioEngine:** Tracks Cash, Equity, and Positions (`{'ticker': PositionObj}`). It applies fills and maintains the "Golden Invariants" (Equity = Cash + MktValue).
    *   **Policy/Allocator:** Decides *Strategic* allocation. It takes raw signals from Alpha and computes `target_weights`.
    *   **Logic:** Can use Volatility Targeting, Risk Parity, or simple Rank-and-Cut.
*   **Connection:** Passes `target_weights` to Engine B.

### 4. Engine B: Risk (`engines/engine_b_risk`)
*   **Role:** The Sizer & Gatekeeper.
*   **Inputs:** Signals (from A) + Target Weights (from C).
*   **Logic:**
    *   **Sizing:** Determines exact share count. Uses `ATR` for volatility-adjusted sizing (Risk Units) OR enforces the `target_weight` from Engine C.
    *   **Limits:** Enforces `max_gross_exposure`, `max_positions`, `sector_limits`.
    *   **Safety:** Stops trading if Drawdown > Threshold.
*   **Output:** `Order` objects ready for execution.

### 5. Execution Infrastructure (`backtester/execution_simulator.py`)
*   **Role:** Simulates the Broker.
*   **Logic:**
    *   Fills orders at the *Next Bar's Open* (Standard Backtest) or Close.
    *   Applies Slippage (BPS) and Commission.
    *   **Intrabar Logic:** Checks validity of High/Low for Stop Loss and Take Profit triggers. Conservative tie-breaking (assumes Stop hit before Target).

### 6. Engine D: Research & Governance (`engines/engine_d_research`)
*   **Role:** The Brain (Optimization & Discovery).
*   **Components:**
    *   **DiscoveryEngine:** Generates new experimentation candidates by mutating parameters of existing templates (Genetic Algorithm).
    *   **StrategyGovernor:** The "Manager". It analyzes `trades.csv` and `portfolio_snapshots.csv`. It calculates Sharpe/Sortino ratios per Edge and adjusts their `weight`.
    *   **Note:** The system does not yet *write new Python code* from scratch, but it evolves the *configuration* of existing code.

### 7. Engine E: Evolution (`engines/engine_e_evolution`)
*   **Role:** The "Self-Driving" Loop.
*   **Logic:** `EvolutionController`.
    1.  Selects edges to optimize.
    2.  Spawns `edge_harness.py` processes to run Walk-Forward Optimization.
    3.  Analyzes results (Parquet).
    4.  Promotes the best parameters to `alpha_settings.prod.json`.

### 8. Logging & Dashboard (`cockpit/`)
*   **CockpitLogger:** The Scribe.
    *   Writes `trades.csv` and `portfolio_snapshots.csv`.
    *   **Crucial:** Enforces a stable schema. Handles `run_id` propagation. Auto-heals CSV headers if new fields are added.
*   **Dashboard:** (Dash/Plotly) Visually renders the logs.
    *   Plots Cumulative Returns, Drawdowns, and Edge Attribution.

---

## System Map: The Flow of Information

```
[DATA_MANAGER] --> (Normalized OHLCV)
       |
       v
[ALPHA ENGINE] --> (Raw Scores) --> [PROCESSOR] --> (Signals)
       |                                              |
       |                                              v
       +-------------------------------------> [PORTFOLIO POLICY]
                                                      |
                                                      v
                                              (Target Weights)
                                                      |
                                                      v
                                                [RISK ENGINE]
                                                      |
(Orders) <--------------------------------------------+
   |
   v
[EXECUTION SIMULATOR] --> (Fills)
           |
           v
   [PORTFOLIO ENGINE] --> (State Update: Cash/Pos) --> [SNAPSHOT]
           |
           v
    [COCKPIT LOGGER] --> (CSV Files)
           |
           v
     [GOVERNOR] --> (Feedback: Weight Adjustments) --> [ALPHA ENGINE]
```

## Directory Structure Guide

*   `backtester/`: The orchestration loop (`BacktestController`) and simulator.
*   `cockpit/`: Logging and Dashboard UI.
*   `config/`: JSON/YAML settings (`backtest_settings`, `risk_settings`, `alpha_settings`).
*   `data/`:
    *   `raw/`: Raw downloaded data.
    *   `processed/`: Parquet caches.
    *   `trade_logs/`: Result of runs (CSV).
    *   `research/`: Output of optimization runs.
*   `engines/`:
    *   `engine_a_alpha/`: Signal logic.
    *   `engine_b_risk/`: Sizing logic.
    *   `engine_c_portfolio/`: Allocation logic.
    *   `engine_d_research/`: Discovery & Governance.
    *   `engine_e_evolution/`: Automation controller.
*   `scripts/`: Entry points (`run_backtest.py`).
*   `research/`: Harnesses for edge testing (`edge_harness.py`).
