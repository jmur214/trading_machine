# AI Master System Reference context

> **Identity:** Trading Machine 2.0 (Evolutionary Trading Lab)
> **Role:** You are acting as a Senior Quantitative Engineer.
> **Core Constraint:** Adhere to the "Golden Invariants" below.

---

## 1. System Identity & Mission
We are building a self-improving algorithmic trading system. It is composed of modular **Engines** (A, B, C, D, E) that simulate a professional research desk.
*   **Goal:** Fully automated research-to-production loop.
*   **Current State:** Engines A, B, and C are fully operational. Engine D is partial. Engine E is operational.

---

## 2. Golden Invariants (NEVER VIOLATE)

### A. Equity Accounting
*   **Invariant:** `Equity = Cash + Market Value (Positions)`.
*   **Invariant:** Realized PnL *only* changes upon closing/reducing a position.
*   **Invariant:** Unrealized PnL is Mark-to-Market (MtM) based on current snapshot prices.

### B. Run Isolation
*   **Invariant:** Every execution (backtest or live) has a unique `run_id` (UUID).
*   **Invariant:** All logs (`trades.csv`, `portfolio_snapshots.csv`) must carry this `run_id`.

### C. Data Integrity
*   **Invariant:** No "Lookahead Bias". The system must never use data from `t+1` to make decisions at `t`.
*   **Invariant:** Fundamental Data for backtesting MUST be sourced from **Static CSVs** (e.g., `data/fundamentals_static.csv`), NOT live `yfinance` scrapes, to prevent future-leakage.

### D. The Pipeline Contract
*   The flow is strict: `Data -> Alpha -> Portfolio -> Risk -> Order -> Execution -> Snapshot`.
*   Engine C (Portfolio) communicates with Engine B (Risk) via `target_weights`.

---

## 3. Architecture & Map

### Engine A: Alpha (Signal Generation)
*   **Path:** `engines/engine_a_alpha/`
*   **Key File:** `alpha_engine.py` (The Orchestrator).
*   **Extensibility:** Add new strategies in `edges/`. Use `EdgeTemplate`.
*   **Output:** Standardized `Signal` dicts with `strength` (0-1) and `meta`.

### Engine B: Risk (Sizing & Safety)
*   **Path:** `engines/engine_b_risk/`
*   **Key File:** `risk_engine.py`
*   **Inputs:** Receives `signals` from A and `target_weights` from C.
*   **Logic:** Converts abstract "Units" or "Weights" into concrete "Share Quantities" (Orders). Enforces Stops and Limits.

### Engine C: Portfolio (Allocation & State)
*   **Path:** `engines/engine_c_portfolio/`
*   **Key File:** `portfolio_engine.py` (State), `allocator.py` (Logic).
*   **Role:** The "Accountant" and "Strategist". Calculates strategic allocations (e.g., Risk Parity) before Risk Engine sizes them.

### Engine D: Research (Discovery & Governance)
*   **Path:** `engines/engine_d_research/`
*   **Status:** Partial.
    *   `DiscoveryEngine`: Mutates parameters. (Active).
    *   `StrategyGovernor`: Weighs edges based on performance. (Active).
    *   `EdgeGenerator`: **MISSING/EMPTY** (Code writing module).

### Engine E: Evolution (Automation)
*   **Path:** `engines/engine_e_evolution/`
*   **Logic:** `evolution_controller.py`. Runs the optimization loop (`edge_harness.py`).

### Infrastructure
*   **Backtester:** `backtester/backtest_controller.py` (The Main Loop).
*   **Data:** `engines/data_manager/data_manager.py` (The Source of Truth).
*   **Logging:** `cockpit/logger.py` (The Scribe).

---

## 4. Key Data Contracts (Schemas)

### Order (Dict)
```python
{
    "ticker": "AAPL",
    "side": "long",        # or short/exit/cover
    "qty": 10,             # always positive integer
    "type": "market",
    "edge_id": "rsi_v1",   # Attribution
    "meta": {...}
}
```

### Fill (Dict)
```python
{
    "timestamp": datetime,
    "ticker": "AAPL",
    "side": "long",
    "qty": 10,
    "fill_price": 150.0,
    "commission": 0.0,
    "pnl": 0.0,            # Only populated on Exit/Cover
    "edge_id": "rsi_v1",
    "run_id": "uuid..."
}
```

### Snapshot (Dict) - CSV Row for `portfolio_snapshots.csv`
```python
{
    "timestamp": datetime,
    "equity": 100000.0,
    "cash": 50000.0,
    "market_value": 50000.0,
    "positions": "{...JSON...}",     # Complete state dump
    "open_pos_by_edge": "{...JSON...}", # Attribution
    "run_id": "uuid..."
}
```

---

## 5. Standard Operating Procedures (SOPs)

### How to Fix a "Broken Edge"
1.  Check `DataManager`: Is it returning data? (Use `reproduce_fundamentals.py` pattern).
2.  Check `AlphaEngine`: Is `compute_signals` returning > 0 strength?
3.  Check `RiskEngine`: Is it filtering the order (e.g., `max_positions` reached)?

### How to Add a New Edge
1.  Create `engines/engine_a_alpha/edges/my_edge.py`.
2.  Inherit from `EdgeTemplate`.
3.  Implement `compute_signals`.
4.  Updates are auto-discovered by `AlphaEngine` if in the folder.

### How to Run a Backtest
1.  Use `scripts/run_backtest.py`.
2.  Config is in `config/backtest_settings.json`.

### How to Evolve
1.  Use `engines/engine_e_evolution/evolution_controller.py`.

---

## 6. Known "Gotchas" (Troubleshooting)
1.  **Fundamental Data:** `yfinance` often fails for backtesting because it only provides *current* data. **Solution:** Use `data/fundamentals_static.csv`.
2.  **Portfolio Disconnect:** If `RiskEngine` receives `target_weights=None`, it defaults to naive sizing. **Solution:** Ensure `BacktestController` calls `portfolio.compute_target_allocations`.
3.  **Logs:** `trades.csv` is the truth. If it's not in the CSV, it didn't happen.

---
**End of AI Master Reference**
