# Phase 2 Roadmap: The Quant Factory

> **Objective**: Enable the machine to "Hunt" for stocks poised to explode using Fundamental + Technical criteria, and validate them in a Shadow Environment.

---

## Milestone 1: Data Modernization ("The Fuel")
We need to ingest the "Explosion" variables (Fundamentals + Intraday).

- [ ] **1.1 Config Expansion**: Update `config/universe.json` to support asset classes (e.g. "Growth", "Value" buckets).
- [ ] **1.2 Fundamental Engine**: Create `engines/data_manager/fundamental_loader.py`.
    - Capabilities: Ingest CSVs/APIs for P/E, EPS, Revenue.
    - **Crucial**: Implement `Point-In-Time` mapping (avoid lookahead bias).
- [ ] **1.3 Feature Factory**: Create `engines/engine_d_research/feature_engineering.py`.
    - Output: A master Feature Matrix (Rows=Time, Cols=RSI, PE, Volatility, Sector_Rel_Strength).

## Milestone 2: The Hunter ("The Brain Upgrade")
Upgrade the `DiscoveryEngine` to look for complex patterns, not just simple indicators.

- [ ] **2.1 Genome Expansion**: Update `discovery.py` to support "Fundamental Genes" (e.g. `PE < Sector_Avg`).
- [ ] **2.2 Cluster Finding**: Implement a simple **Decision Tree Scanner** (using `sklearn`).
    - Input: The Feature Matrix.
    - Target: "Future 5-Day Return > 10%".
    - Output: "Rules" that define the explosion (e.g. "Vol_Compression + High_Earnings_Growth").
- [ ] **2.3 The "Settings" Auditor**: A module that takes a discovered rule and rigorously backtests variations of its settings (e.g. RSI 30 vs 35).

## Milestone 3: The Shadow Realm ("The Proving Ground")
A safe environment for new strategies to prove themselves on live data.

- [ ] **3.1 Shadow Broker**: Create a mock broker interface that tracks virtual orders.
- [ ] **3.2 Shadow Loop**: Create `scripts/run_shadow_paper.py`.
    - Purpose: Executing the "Candidate Strategies" in real-time alongside the main loop.
- [ ] **3.3 Promotion Logic**: A script that analyzes Shadow PnL and automatically moves a strategy to `config/edge_config.json` if it survives 30 days.

## Milestone 4: metrics & Workflows
- [ ] **4.1 Metrics Expansion**: Add Calmar, Kelly, Beta to `Cockpit`.
- [ ] **4.2 One-Click Workflows**: Create `.agent/workflows/` for "Nightly Hunt" and "Data Ingest".
