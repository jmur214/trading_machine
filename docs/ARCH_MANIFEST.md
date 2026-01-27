# Architecture Manifest (Source of Truth)

> **Last Updated**: 2026-01-27
> **Status**: Institutional Grade (Tier 1) - Phase 2 Planning

This document defines the *current* state of the Trading Machine and the *intended* architecture for the "Quant Factory" upgrade.

---

## 1. System Philosophy
This is not a "Bot". It is an **Autonomous Research & Trading Platform**.
1.  **Strict Separation**: Engines (Alpha, Risk, Portfolio) are isolated. They communicate via standardized DataFrames.
2.  **Evolutionary**: The system finds its own strategies via `DiscoveryEngine`.
3.  **Scientific**: All strategies must pass "Parallel Universe" robustness checks (PBO) and Walk-Forward Optimization (WFO).
4.  **Institutional**: Risk is managed via Factor Models (Beta, Momentum) and Portfolio Optimization (MVO), not simple position sizing.

---

## 2. Core Engines
| Engine | Responsibilities | Key Files |
| :--- | :--- | :--- |
| **Engine A (Alpha)** | "The Signal Generator". Generates raw buy/sell signals (-1 to +1). | `alpha_engine.py`, `signal_processor.py`, `ml_predictor.py` |
| **Engine B (Risk)** | "The Guardrail". Blocks dangerous trades (Liquidity, Factor Risk). | `risk_engine.py`, `factor_analysis.py` |
| **Engine C (Portfolio)** | "The Allocator". Decides *how much* to buy (Optimizer). | `policy.py`, `optimizer.py` |
| **Engine D (Research)** | **"The Brain"**. Hunts for new strategies. | `discovery.py`, `wfo.py`, `robustness.py`, `regime_analytics.py` |
| **Data Manager** | "The Feeder". Ingests, normalizes, and caches data. | `data_manager.py` |

---

## 3. The "Learning Loop" (The Flywheel)
The system learns via the **Evolution Cycle** (`scripts/run_evolution_cycle.py`):
1.  **Discover**: `DiscoveryEngine` mutates parameters or logic (Genetic Algo).
2.  **Validate**: 
    *   **Fitness**: Backtest for Sharpe/Sortino.
    *   **Robustness**: `RobustnessTester` creates synthetic market histories to check for overfitting.
3.  **Verify**: `WalkForwardOptimizer` tests consistency over rolling time windows.
4.  **Promote**: Winners are automatically added to `config/edge_config.json`.

---

## 4. Phase 2 Architecture: "The Quant Factory" (PLANNED)
**Objective**: Integrate Fundamental Data and automate the discovery of complex "Factor + Technical" strategies.

### A. The Megadata Layer
*   **Goal**: unified queryable dataset of [Price + Visuals + Fundamentals].
*   **New Components**:
    *   `FundamentalLoader`: Ingests historical balance sheets/income statements.
    *   `FeatureEngineer`: Computes derived factors (e.g. `PE_ZScore`, `Revenue_Accel`).

### B. The "Hunter" (Discovery Upgrade)
*   **Goal**: Find logic chains like *"Buy when PE < 15 AND RSI < 30"*.
*   **Method**: 
    *   Upgrade `DiscoveryEngine` to support **Combinatorial Genes** (Fundamental + Technical).
    *   Use **Decision Trees** to find "Explosion Clusters" in the feature set.

### C. The Shadow Realm (Paper Validation)
*   **Goal**: Test strategies on live data without risk.
*   **New Workflow**: `run_shadow_paper.py`.
    *   Parallel execution loop that tracks "Provisional Strategies".
    *   Only promotes to Main Portfolio after N days of live Shadow Success.

---

## 5. Metrics & Standards
We judge success by **Institutional Metrics**, not just "Profit":
*   **Sharpe Ratio**: Risk-adjusted return. (> 1.0 required)
*   **Sortino Ratio**: Upside volatility capture. (> 1.5 preferred)
*   **PBO (Probability of Backtest Overfitting)**: Survival rate in synthetic data. (> 0.5 required)
*   **WFO Degradation**: OOS Performance / In-Sample Performance. (> 0.6 required)
