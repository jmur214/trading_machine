# Master Blueprint & Roadmap

> **Master Protocol:** Every Phase in this roadmap represents an overarching goal. As new ideas exit the pipeline and enter this roadmap, that goal MUST be broken down into smaller, strictly actionable sub-steps.

## Phase 1: Robust Core Foundations (Completed)
- [x] Engines A-D scaffolding (Alpha, Risk, Portfolio, Governor).
- [x] Modular edge integration (Technical signals).
- [x] Initial Backtester & CSV execution simulation.
- [x] Cockpit Dashboard V1 (Performance metrics, PnL by edge, equity curve).
- [x] Governor feedback loops based on CSV trades.

## Phase 2: Codebase Review & Real Fund Architecture (Priority #1)
- [ ] Conduct a comprehensive, line-by-line codebase architecture review to ensure strict alignment with the "Real Fund Manager" mentality.


## Phase 2.5: Documentation & System Blueprinting
- [ ] **Define High-Level Engine Boundaries.**
  - [ ] Explicitly outline what Engine A (Alpha), Engine B (Risk), Engine C (Portfolio), and Engine D (Governor) *should* and *shouldn't* do at a high level.
  - [ ] Establish these limits to actively prevent logic bleed and technical debt across the execution pipeline.
- [ ] **Create an overarching `docs/Core/` meta-index file.**
  - [ ] Map, organize, and explain the specific contents of the `docs/Core/` folder itself to guide AI context.
- [ ] **Visualize system architecture with a Mermaid Flowchart.** *(⚠️ BLOCKED: Dependent on Engine Boundaries)*
  - [ ] Add the flowchart to `PROJECT_CONTEXT.md`.
  - [ ] Map the exact structural relationships between the code directories and the theoretical system architecture.
- [ ] **Audit and refine Engine `index.md` files.** *(⚠️ BLOCKED: Dependent on Engine Boundaries)*
  - [ ] Review the qualitative descriptions of all `index.md` files within the `engines/` subdirectories.
  - [ ] Ensure they strictly match the finalized, ironclad architectural boundaries for 100% functional accuracy.


## Phase 3: From Simulation to Reality
- [ ] Enforce structural risk diversification logic and cross-sector allocation before advancing trading operations.
- [ ] Connect the Order Management System (OMS).
- [ ] Incorporate slippage, fees, and short-borrow cost modeling.
- [ ] Solidify exposure limits and Max Drawdown logic.
- [ ] Transition from CSV data to Parquet / DB solutions for local analytics.
- [ ] Finalize the Alpaca Paper Trading integration with the Cockpit.

## Phase 4: Market Regime Detection & Intelligence
- [ ] Build a dedicated Market Regime Detection engine to identify volatility clustering, trend, and chop.
- [ ] Empower the Governor (Engine D) to actively retire/activate edges based on current regime context.
- [ ] Develop advanced edges: Fundamental intrinsic data, News Sentiment/Geopolitical scrapers.

## Phase 5: The "Schwab Intelligent Portfolio" (SIP) Extension
- [ ] Create Portfolio Sleeves (e.g., partitioning custodial sub-accounts for Equity, Fixed-Income, Cash).
- [ ] Automatic drift monitoring and independent rebalance scheduling.
- [ ] Tax-loss harvesting (TLH) simulation scaffolding.

## Phase 6: Scaling & Live Operations
- [ ] CI/CD pipeline, Docker containerization, and AWS/Cloud deployment.
- [ ] Dual Paper-Trader Segregation (PT-A for testing, PT-B for validated strategies).
- [ ] Live execution graduation (moving from Paper to real capital).

## Phase 7: Human-in-the-Loop Cockpit Override (Long-Term Vision)
- [ ] Develop the "Big Red Button" global halt mechanism.
- [ ] Build global risk adjustment sliders and mobile push notifications for drawdown/alert tracking.
