# Master Blueprint & Roadmap

> **Master Protocol:** Every Phase in this roadmap represents an overarching goal. As new ideas exit the pipeline and enter this roadmap, that goal MUST be broken down into smaller, strictly actionable sub-steps.

## Phase 1: Robust Core Foundations (Completed)
- [x] Engines A-D scaffolding (Alpha, Risk, Portfolio, Governor).
- [x] Modular edge integration (Technical signals).
- [x] Initial Backtester & CSV execution simulation.
- [x] Cockpit Dashboard V1 (Performance metrics, PnL by edge, equity curve).
- [x] Governor feedback loops based on CSV trades.

## Phase 2: Codebase Review & Real Fund Architecture (Completed)
- [x] Conduct a comprehensive, line-by-line codebase architecture review to ensure strict alignment with the "Real Fund Manager" mentality.
  - *Completed via `docs/Audit/` — see `codebase_findings.md`, `high_level-engine_function.md`, and `engine_charters.md`.*
- [x] **6-Engine Architecture Restructure.**
  - [x] Split Engine D (Research) into: D (Discovery & Evolution), E (Regime Intelligence), F (Governance).
  - [x] Move MetricsEngine to shared `core/` infrastructure.
  - [x] Move SignalGate to Engine A (`engine_a_alpha/learning/`).
  - [x] Move `promote.py` and `evolution_controller.py` to Governance (F).
  - [x] Wire ModeController to orchestrate Engine E (regime detection as a service).
  - [x] Update all imports across codebase. Remove old `engine_d_research/` and `engine_e_evolution/` directories.
  - *New architecture: A (Alpha), B (Risk), C (Portfolio), D (Discovery), E (Regime), F (Governance).*


## Phase 2.5: Documentation & System Blueprinting
- [x] **Define High-Level Engine Boundaries.**
  - [x] Explicitly outline what Engine A (Alpha), Engine B (Risk), Engine C (Portfolio), and Engine D (Governor) *should* and *shouldn't* do at a high level.
  - [x] Establish these limits to actively prevent logic bleed and technical debt across the execution pipeline.
  - *Completed in `docs/Audit/engine_charters.md` — formal authority boundaries, input/output contracts, and invariants defined for all 5 engines (A-E).*
- [x] **Create an overarching `docs/Core/` meta-index file.**
  - [x] Map, organize, and explain the specific contents of the `docs/Core/` folder itself to guide AI context.
  - *Completed as `docs/Core/README.md` — tiered reading order, document flow diagram, and important rules.*
- [ ] **Visualize system architecture with a Mermaid Flowchart.**
  - [ ] Add the flowchart to `PROJECT_CONTEXT.md`.
  - [ ] Map the exact structural relationships between the code directories and the theoretical system architecture.
- [ ] **Audit and refine Engine `index.md` files.**
  - [ ] Review the qualitative descriptions of all `index.md` files within the `engines/` subdirectories.
  - [ ] Ensure they strictly match the finalized architectural boundaries for 100% functional accuracy.
- [x] **Reconcile Edge Taxonomy (6 Core Edges vs actual implementation).**
  - Kept the 6 Core Edges as the taxonomy. Added "Evolutionary / Synthetic" as a 7th meta-category for GA-generated composite edges.
  - Current alignment:
    - ✅ **Price / Technical** — Implemented (RSI Bounce, ATR Breakout, Bollinger Reversion, Momentum, SMA Cross)
    - ✅ **Fundamental** — Implemented (FundamentalRatio, ValueTrap)
    - 🟡 **News-Based / Event-Driven** — Partial (VADER sentiment exists; EarningsVolEdge handles pre/post-earnings patterns)
    - ✅ **Stat/Quant** — Implemented (SeasonalityEdge, GapEdge, VolumeAnomalyEdge, XSec Momentum/Reversion)
    - ✅ **Behavioral/Psychological** — Implemented (PanicEdge, HerdingEdge, EarningsVolEdge)
    - ❌ **"Grey"** — Not implemented (abstract data source stubs planned)
  - **Evolutionary / Synthetic** — CompositeEdge genomes evolved via GA (tournament selection, crossover, mutation), RuleBasedEdge from tree scanning. These are meta-edges that combine genes from any category above.
  - **ML Gating** — MLPredictor and SignalGate are infrastructure (meta-filters), not edges. Not part of the taxonomy.


## Phase 3: From Simulation to Reality
- [ ] Enforce structural risk diversification logic and cross-sector allocation before advancing trading operations.
- [ ] Connect the Order Management System (OMS).
- [ ] Incorporate slippage, fees, and short-borrow cost modeling. *(Partial: fixed + vol-based slippage and commission exist in ExecutionSimulator; short-borrow cost not yet modeled)*
- [ ] Solidify exposure limits and Max Drawdown logic. *(Partial: RiskEngine enforces gross exposure, sector limits, position limits, ATR stops, trailing stops; Governor MDD kill-switch at -25%)*
- [ ] Transition from CSV data to Parquet / DB solutions for local analytics. *(Partial: DataManager dual-writes Parquet + CSV; Parquet is primary read path)*
- [ ] Finalize the Alpaca Paper Trading integration with the Cockpit.

## Phase 4: Market Regime Detection & Intelligence
- [x] Build a dedicated Market Regime Detection engine (Engine E). *(Completed: `engine_e_regime/` with `RegimeDetector`; advisory hints planned)*
- [x] **Comprehensive Engine E rewrite — 5-axis regime detection with advisory system.**
  - [x] Phase 1: Foundation (RegimeConfig, regime_settings.json, HysteresisFilter)
  - [x] Phase 2: Sub-detectors (Trend, Volatility, Correlation, Breadth, Forward Stress)
  - [x] Phase 3: Coordinator + Advisory (AdvisoryEngine, RegimeHistoryStore, RegimeDetector rewrite, macro regime mapping)
  - [x] Phase 4: Wiring (BacktestController, ModeController, AlphaEngine, CompositeEdge, run_backtest.py)
  - [x] Phase 5: History + Analytics (regime history persistence, RegimePerfAnalytics compatibility)
  - *84 unit tests passing. 5 axes, hysteresis, soft macro regime probabilities, coherence checks, VIX term structure.*
- [x] **Double-counting cleanup:** Replaced binary `market_vol == "high"` (-25%) and `market_trend == "bear"` (-50%) cuts in SignalProcessor with Engine E's advisory `risk_scalar` applied selectively in stressed/crisis regimes. Backtest validated: Sharpe improved from -0.56 to -0.40. Edge affinity boost deferred until Governance (F) proves regime-conditional profitability. See `lessons_learned.md` for details.
- [x] **Self-Learning Feedback Loop Closure.**
  - [x] Governor MDD kill-switch: soft proportional penalty (current vs historical drawdown) instead of permanent hard zero.
  - [x] Governor normalization: removed sum-to-1.0 constraint; weights are now independent quality scores in [0, 1].
  - [x] RiskEngine dynamic sizing: fixed inert `gate_confidence` default; now uses signal `strength` + `governor_weight` for position sizing.
  - [x] Equal aggregation weights: `run_backtest.py` passes 1.0 for all loaded edges, Governor handles quality differentiation post-aggregation.
  - [x] Silent edges fixed: config no longer overrides edge weights to 0.0; `EdgeRegistry.get_all_specs()` added.
  - [x] Discovery wired: `--discover` flag on `run_backtest.py` triggers post-backtest hunt → validate → promote cycle.
  - *See `lessons_learned.md` 2026-04-16 entries for details.*
- [x] **Regime-Conditional Edge Management (B) + Portfolio Management (C).**
  - [x] Phase 1: `RegimePerformanceTracker` — per-edge, per-regime Welford online stats (`engines/engine_f_governance/regime_tracker.py`).
  - [x] Phase 2: Governor regime-conditional weights — blended `alpha * regime_weight + (1-alpha) * global_weight` with fallback when data sparse.
  - [x] Phase 3: Trade fill regime tagging — every fill stamped with `regime_label` from macro regime at time of execution.
  - [x] Phase 4: AlphaEngine wiring — `get_edge_weights(regime_meta=regime_meta)` passes current regime to Governor.
  - [x] Phase 5: Learned edge affinity — `RegimePerformanceTracker.get_learned_affinity()` replaces static `MACRO_EDGE_AFFINITY` table; applied as 0.3-1.5x multiplier per edge category in `SignalProcessor`.
  - [x] Phase 6: Advisory wired to Risk Engine — `prepare_order()` now consumes `suggested_max_positions`, `suggested_exposure_cap`, `risk_scalar`, and `correlation_regime` for dynamic sector limits. All constraints can only tighten, never loosen beyond config.
  - [x] Phase 7: Portfolio vol targeting — `PortfolioPolicy` now estimates portfolio-level vol via `w @ cov @ w` and scales weights to match `target_volatility`. Advisory exposure cap enforcement applied post-allocation.
  - [x] Phase 8: Autonomous allocation discovery — `AllocationEvaluator` tests 384 parameter combos (mode, max_weight, target_vol, rebalance_thresh, risk_per_trade_pct), scores by composite metric, saves per-regime recommendations. Governor runs evaluation in `update_from_trade_log()` feedback loop. `auto_apply_allocation` defaults to false.
  - *New files: `regime_tracker.py`, `allocation_evaluator.py`. Modified: governor.py, alpha_engine.py, signal_processor.py, risk_engine.py, policy.py, portfolio_engine.py, backtest_controller.py, governor_settings.json.*
- [x] **Regime Classification Threshold Calibration.** Transitional base score 0.30→0.15, confidence threshold 0.40→0.25. Validated across 2021-2024: regime labels now match market character (bull years → expansion, 2022 → cautious/turmoil). See `lessons_learned.md` 2026-04-20 entry.
- [x] **Governor Regime Tracker Window Fix.** Tracker now processes all trades (not just 90-day rolling window) since Welford's algorithm is designed for indefinite accumulation.
- [x] **CockpitLogger `regime_label` column.** Added to `TRADE_COLUMNS` so regime labels persist in trade CSVs.
- [ ] **OPEN: Short Bias Inversion Bug.** Multi-year backtest (2021-2024) revealed 72% short bias. `rsi_bounce` is 98% short, `atr_breakout` 78% short. Structural bug in signal-to-side pipeline — not a parameter issue. Needs end-to-end signal trace. See `lessons_learned.md` 2026-04-20 entry.
- [x] Empower Governance (Engine F) to retire/activate edges based on regime-conditional performance (via `RegimePerformanceTracker`).
- [x] **Engine D Discovery & Edge Ecosystem Overhaul.**
  - [x] **Feature Engineering Expansion:** 18 features -> 40+ across 7 categories (technical, fundamental, calendar, microstructure, inter-market, regime context, cross-sectional).
  - [x] **Two-Stage ML Pipeline:** LightGBM screening for feature importance -> shallow decision tree for interpretable rule extraction. Time-series CV with purge gap. Vol-adjusted targets (ATR-scaled thresholds).
  - [x] **Genetic Algorithm Engine:** Tournament selection, single-point crossover, Gaussian mutation, elitism. Persistent population in `ga_population.yml`. Seeding from existing composite edges.
  - [x] **4-Gate Validation Pipeline:** Backtest (Sharpe > 0) -> PBO robustness (50 paths, survival > 0.7) -> WFO degradation (OOS >= 60% IS) -> Monte Carlo significance (p < 0.05).
  - [x] **Expanded Gene Vocabulary:** 7 gene types in CompositeEdge (technical, fundamental, regime, calendar, microstructure, intermarket, behavioral) with weighted random generation.
  - [x] **New Stat/Quant Edges:** SeasonalityEdge (calendar patterns), GapEdge (overnight gap fill), VolumeAnomalyEdge (spike reversal / dry-up breakout).
  - [x] **New Behavioral Edges:** PanicEdge (multi-condition extreme reversion), HerdingEdge (cross-sectional contrarian), EarningsVolEdge (pre-earnings vol compression / post-earnings drift).
  - [x] **Edge Registration:** All 6 new edges registered in `edges.yml` with `status: active`, added to discovery template mutation pool.
  - [x] **Discovery Orchestration:** `run_backtest.py --discover` now runs: regime detection -> expanded feature hunt -> GA evolution -> 4-gate validation -> auto-promotion. JSONL audit logging via `DiscoveryLogger`.
  - *9 new files created, 6 files modified. See `lessons_learned.md` 2026-04-17 entry.*
- [x] **Architectural Refactoring — 7 Structural Fixes.**
  - [x] Fix 1: Single PnL path — `PortfolioEngine.apply_fill()` stamps `fill["pnl"]` as sole source of truth. Removed fallback computations from backtest_controller and logger.
  - [x] Fix 2: Paper mode SL/TP parity — `PaperTradeController` now has trailing stop management + SL/TP evaluation matching BacktestController. Removed incorrect forced-exit-all logic.
  - [x] Fix 3: Metrics consolidation — `MetricsEngine` is sole calculator; `cockpit/metrics.py` delegates via cached `_engine_metrics()`. Removed inline metrics from `run_benchmark.py`.
  - [x] Fix 4: Scripts → orchestration — All backtest orchestration (warmup, edge registry, governor init, discovery) moved to `ModeController.run_backtest()`. `run_backtest.py` slimmed to ~87 lines.
  - [x] Fix 5: Edge feedback → Engine F — Core feedback loop moved from `analytics/edge_feedback.py` to `governor.py` as `update_from_trade_log()`. Thin shim preserved for backward compat.
  - [x] Fix 6: BacktestController method extraction — 831-line `run()` refactored into 8 private methods. Pure refactor, no behavior change.
  - [x] Fix 7: Logger snapshot cleanup — Removed portfolio valuation fallback from `log_snapshot()`. Logger is now a pure recorder.
  - [x] Audit Correction A: Stop/TP propagation — `ExecutionSimulator.fill_at_next_open()` now preserves `stop`/`take_profit` from order to fill dict.
  - [x] Audit Correction B: Metrics index alignment — Fixed NaN-dropped equity row misalignment in timestamp mapping.
  - *See `lessons_learned.md` 2026-04-18 entry for full details and architectural takeaways.*
- [ ] Develop advanced edges: News Sentiment/Geopolitical scrapers, Grey edge data sources.

### Phase 4.5: Engine E Enhancements (Deferred)
- [ ] **HMM cross-validator:** Add Hidden Markov Model (hmmlearn) as a parallel statistical detector to validate rule-based regime classifications.
- [ ] **Cap-weighted sector returns:** Use market-cap-weighted (not equal-weighted) sector return series in CorrelationDetector. Requires market cap data integration.
- [ ] **Hurst exponent:** Add Hurst exponent computation in TrendDetector for trend quality/mean-reversion tendency assessment.
- [ ] **Credit spreads (HYG/LQD):** Add credit spread monitoring as additional forward stress input in ForwardStressDetector.
- [ ] **SKEW index:** Integrate CBOE SKEW index for tail-risk demand measurement in ForwardStressDetector.
- [ ] **F1 evaluation against NBER dates:** Formal calibration of macro regime classifications against NBER recession dates for accuracy scoring.
- [ ] **Full regime probability blending in Alpha (A):** Enable Engine A to weight forecasts by macro regime probability distribution (not just hard gate).

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
