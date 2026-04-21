# Lessons Learned & Technical Retrospectives

This document serves as the historical memory of the Trading Machine for all developers (AI and human). 

Whenever a significant bug is fixed, a new operational paradigm is adopted, or an attempt to use a specific library/strategy completely fails, log it here. This prevents the system from repeating past mistakes and ensures that "best practices" constantly evolve.

### Active Logs

*(Log format: Date | Subject | Lesson)*
- **2026-03-25 | Documentation |** Established `ROADMAP.md` completely for forward-looking progress, leaving this `lessons_learned.md` exclusively for historical tracking and mistake prevention.

- **2026-04-16 | Engine E Advisory Wiring — Signal Scaling |** Wired Engine E's 5-axis advisory (`risk_scalar`, `edge_affinity`) into `SignalProcessor` to replace the old binary regime cuts (bear -50%, high-vol -25%). Three key findings from iterative backtest comparison:
  1. **Constant `risk_scalar` dampening hurts in benign markets.** When 87% of bars are "transitional" (no clear macro regime), applying `risk_scalar ~0.85` on every bar creates persistent drag that erodes returns. Solution: only apply `risk_scalar` as a brake in `stressed`/`crisis` regime summaries.
  2. **Edge affinity boost is counterproductive with low win-rate edges.** With 26% win rate, amplifying signals for "favorable" edge-regime combos just amplifies losses. Edge affinity should be deferred until Governance (F) proves which edges are actually regime-conditional winners. Don't amplify what isn't working yet.
  3. **The brake-only approach outperforms all alternatives.** Final results: brake-only (-0.95% return, Sharpe -0.40) vs. legacy binary (-1.82%, -0.56) vs. always-on risk_scalar (-4.27%, -0.93). The improvement comes from Engine E's 5-axis regime detection providing more accurate `stressed`/`crisis` identification than the old 2-axis (trend+vol) binary check.

  **Architectural takeaway:** Regime intelligence adds the most value as a *downside protector* (brake in crisis) rather than an *upside amplifier* (boost in calm). The amplifier role requires proven edge-regime profitability data, which is a Governance (F) responsibility.

- **2026-04-16 | Engine E — `scripts/run_backtest.py` Missing Wiring |** `scripts/run_backtest.py` creates `BacktestController` directly without going through `ModeController`, so `regime_detector` was never passed (defaulted to `None`). Engine E was completely inactive during backtests run via the script. Fixed by instantiating `RegimeDetector` in `run_backtest.py`. **Rule: any new entry point that creates `BacktestController` must also pass `regime_detector`.**

- **2026-04-16 | Backtest Non-Determinism |** Backtests have meaningful run-to-run variance (~3-5% return spread). Root cause: `FundamentalValueEdge` fetches live fundamentals from yfinance during backtest (network timing, rate limits). This makes A/B comparisons unreliable without multiple runs. Future fix: cache fundamentals to disk per backtest period, or exclude fundamental edges from deterministic comparison tests.

- **2026-04-16 | Double-Counting Discovery |** SignalProcessor (Engine A) and RiskEngine (Engine B) both independently penalize high-volatility trades — SignalProcessor cuts signals 25%, RiskEngine widens stops (reducing size). Removing the SignalProcessor cut alone made things *worse* (Sharpe -1.07 -> -1.29) because RiskEngine's stop widening alone isn't enough protection. The proper fix was replacing both binary cuts with Engine E's multi-axis `risk_scalar`, which is more accurate but applied selectively (stressed/crisis only).

- **2026-04-16 | Governor Feedback Loop — Five Critical Bugs |** Deep audit of the self-learning pipeline revealed five interconnected failures preventing the system from learning:
  1. **Governor MDD kill-switch was permanent.** `atr_breakout_v1` had Sharpe 1.29 but MDD -43%, triggering the -25% kill-switch → weight zeroed permanently even after recovery. Fix: separated SR kill-switch (hard zero for losing edges) from MDD (soft proportional penalty). Now distinguishes "currently underwater" (heavy penalty) from "historically had a bad drawdown" (proportional to severity).
  2. **Governor sum-to-1.0 normalization crushed all weights.** With 11 edge entries (including stale ones), normalization compressed every weight to ~0.1 regardless of quality. Fix: removed sum-to-1.0 constraint. Weights are now independent quality scores in [0, 1], not portfolio allocations.
  3. **`gate_confidence` was never set — dynamic sizing was inert.** RiskEngine's sizing used `signal.get("gate_confidence", 0.5)` which always returned 0.5 (default), locking risk_scaler at 0.5 regardless of signal quality. No ML gate or SignalGate was active. Fix: use `strength` as primary sizing input when `gate_confidence` isn't explicitly set, and multiply by `governor_weight` from signal meta.
  4. **Config hardcoded edge weights to 0.0.** `alpha_settings.prod.json` set `rsi_bounce_v1: 0.0` and `bollinger_reversion_v1: 0.0`, silencing those edges at the aggregation level. Fix: `run_backtest.py` now passes equal weights (1.0) for all loaded edges, overriding config defaults. Governor handles quality differentiation through post-aggregation strength scaling.
  5. **`EdgeRegistry.get_all_specs()` method missing.** Called in `run_backtest.py`'s override_params code path but didn't exist, causing silent failures when injecting candidate edges. Fix: added the method.

  **Architectural takeaway:** The system had all the right components (Governor, Discovery, Registry) but the feedback loop was broken at every junction. Weights were computed but never loaded; sizing was dynamic but the input was always constant; edges were registered but silenced by config. **Rule: after adding any self-learning component, trace the full loop end-to-end and verify data actually flows through.**

- **2026-04-16 | Discovery Wiring |** Engine D (Discovery) had a complete pipeline — `hunt()` for decision-tree pattern detection, `generate_candidates()` for template mutation, `validate_candidate()` for quick backtest + PBO robustness, WFO walk-forward validation — but nothing ever called it. Wired into `run_backtest.py` as a `--discover` post-backtest phase: hunt → save candidates → validate queued → promote winners to active. Capped at 10 validations per cycle to limit compute.

- **2026-04-17 | Engine D Discovery & Edge Ecosystem Overhaul |** Comprehensive overhaul of the discovery system and edge ecosystem. Two parallel tracks completed:

  **Track A — Better Pattern Detection:**
  1. **Feature Engineering (18 → 40+):** Added 5 new feature categories to `FeatureEngineer`: calendar/seasonality (DOW, month, quarter-end, OpEx proximity), microstructure (overnight gap, close location, intraday range, gap fill), inter-market (SPY/TLT/GLD returns and correlations — gracefully degrades when assets unavailable), regime context (bull/bear/range flags, vol-high/low, stability, risk scalar), and cross-sectional (percentile ranks across universe per date).
  2. **Two-Stage ML Pipeline:** Replaced single decision tree with LightGBM screening for feature importance (top-K selection) followed by shallow `DecisionTree(max_depth=4)` for interpretable rule extraction. Added `TimeSeriesSplit(n_splits=5, gap=6)` for honest cross-validated accuracy. Vol-adjusted target labels scale thresholds by rolling ATR% (prevents regime-dependent labeling).
  3. **Genetic Algorithm Engine:** Created `genetic_algorithm.py` — tournament selection (k=3), single-point crossover, Gaussian mutation (sigma=10%), operator flip (5%), gene add/delete (10%), direction mutation (5%), elitism (top 3). Population persists in `ga_population.yml` across cycles. Seeds from existing composite edges on first run.
  4. **4-Gate Validation Pipeline:** Upgraded from quick-backtest + PBO(5) to: Gate 1 (Sharpe > 0) → Gate 2 (PBO 50 paths, survival > 0.7) → Gate 3 (WFO degradation ratio > 0.6) → Gate 4 (Monte Carlo permutation test p < 0.05 + MinTRL). Candidates must pass ALL gates for promotion.
  5. **Expanded Gene Vocabulary:** CompositeEdge now evaluates 7 gene types: technical, fundamental, regime, calendar, microstructure, intermarket, behavioral. Weighted random generation in `_create_random_gene()`.

  **Track B — New Alpha Sources (6 Core Edges taxonomy → mostly implemented):**
  6. **Stat/Quant Edges:** `SeasonalityEdge` (calendar seasonality by day-of-week or month-of-year), `GapEdge` (overnight gap fill with ATR-scaled threshold + optional volume spike filter), `VolumeAnomalyEdge` (two modes: spike_reversal for mean reversion, dryup_breakout for Bollinger squeeze anticipation).
  7. **Behavioral Edges:** `PanicEdge` (multi-condition extreme reversion: RSI + vol z-score + BB lower + ATR expansion), `HerdingEdge` (cross-sectional herding detection — contrarian on extreme movers when breadth > threshold), `EarningsVolEdge` (pre-earnings vol compression, post-earnings drift/PEAD).
  8. **Registration & Orchestration:** All 6 new edges registered in `edges.yml` with `status: active`, added to discovery template mutation pool. `run_backtest.py --discover` now runs full 5-step cycle: regime → features → hunt → evolve → validate/promote. JSONL audit logging via `DiscoveryLogger`.

  **Key architectural decision:** Inter-market genes needed data_map access, but CompositeEdge gene evaluation only receives per-ticker DataFrame. Solved by storing `self._current_data_map = data_map` at the start of `compute_signals()`.

  **Files:** 9 new files created (`genetic_algorithm.py`, `significance.py`, `discovery_logger.py`, `seasonality_edge.py`, `gap_edge.py`, `volume_anomaly_edge.py`, `panic_edge.py`, `herding_edge.py`, `earnings_vol_edge.py`), 6 existing files modified (`feature_engineering.py`, `tree_scanner.py`, `discovery.py`, `composite_edge.py`, `run_backtest.py`, `edges.yml`).

- **2026-04-18 | Architectural Refactoring — 7 Structural Fixes + 2 Audit Corrections |** After implementing the three-pronged performance improvement (trailing stops, directional bias, fundamentals pipeline), an architectural audit revealed 7 structural issues: duplicated logic, misplaced responsibilities, and missing parity across execution modes. All 7 fixes were implemented and verified via benchmark.

  **Fix 1 — Single PnL Computation Path:**
  PnL was computed in 3 places with different logic: `portfolio_engine.py` (authoritative), `backtest_controller.py` (fallback), and `cockpit/logger.py` (`_calc_realized_pnl()`). Now `PortfolioEngine.apply_fill()` stamps `fill["pnl"] = round(realized, 2)` as the single source of truth. Removed PnL fallback blocks from `backtest_controller.py`. Gutted `logger._calc_realized_pnl()` to a pure reader that returns `fill.get("pnl")`.
  **Files:** `engines/engine_c_portfolio/portfolio_engine.py`, `backtester/backtest_controller.py`, `cockpit/logger.py`.

  **Fix 2 — Stop/TP Evaluation in PaperTradeController:**
  `PaperTradeController` had NO stop-loss or take-profit evaluation — positions never got stopped out in paper mode. Added trailing stop management via `risk.manage_positions()` and SL/TP evaluation via `exec.check_stops_and_targets()`, mirroring BacktestController's pattern. Removed the forced exit-all-positions logic (lines 322-332) which incorrectly closed any position without a new order on the same bar.
  **Files:** `orchestration/mode_controller.py`.

  **Fix 3 — Metrics Consolidation:**
  Metrics were computed in 3 places: `cockpit/metrics.py`, `core/metrics_engine.py`, and inline in `scripts/run_benchmark.py`. Made `MetricsEngine` the single source of truth. `PerformanceMetrics` now delegates all metric calculations to `MetricsEngine` via a cached `_engine_metrics()` method while keeping its own CSV I/O, FIFO trade pairing, and summary formatting. Removed inline `sortino_ratio()` and `calmar_ratio()` from `run_benchmark.py`.
  **Files:** `cockpit/metrics.py`, `scripts/run_benchmark.py`.

  **Fix 4 — Move Orchestration Logic Out of Scripts:**
  `scripts/run_backtest.py` contained unique orchestration logic (warmup period, edge registry loading, governor init, discovery cycle) not available through `ModeController`. Moved all orchestration into `ModeController.run_backtest()` with full parameter support. Slimmed `run_backtest.py` from ~448 lines to ~87 lines — now a thin CLI wrapper. `run_backtest_logic()` preserved as backward-compatible entry point that delegates to `ModeController`.
  **Files:** `orchestration/mode_controller.py`, `scripts/run_backtest.py`.

  **Fix 5 — Move Edge Feedback to Engine F (Governance):**
  `analytics/edge_feedback.py` directly instantiated `StrategyGovernor` and ran the feedback loop — governance logic living in the wrong directory. Moved core logic into `governor.py` as `update_from_trade_log()` method. Replaced `edge_feedback.py` with a thin shim that delegates to governor. CLI entry point preserved.
  **Files:** `engines/engine_f_governance/governor.py`, `analytics/edge_feedback.py`.

  **Fix 6 — Extract BacktestController Business Logic:**
  `BacktestController.run()` was 831 lines mixing orchestration with inline business logic. Extracted into 8 private methods: `_detect_regime()`, `_update_trailing_stops()`, `_generate_signals()`, `_prepare_orders()`, `_execute_fills()`, `_evaluate_stops()`, `_log_snapshot()`, `_post_run()`. Pure refactoring — no behavior change. `run()` is now a readable pipeline.
  **Files:** `backtester/backtest_controller.py`.

  **Fix 7 — Remove Portfolio Valuation from Logger:**
  `CockpitLogger.log_snapshot()` had a fallback that recomputed `market_value`, `equity`, `unrealized_pnl` from the portfolio's positions — portfolio accounting logic in a logging class. Removed the fallback entirely. Logger now records snapshots as-is. All callers already provide complete snapshots via `PortfolioEngine.snapshot()`.
  **Files:** `cockpit/logger.py`.

  **Audit Correction A — Stop/TP Propagation Gap:**
  Post-implementation audit discovered `ExecutionSimulator.fill_at_next_open()` was not copying `stop` and `take_profit` from the order dict to the fill dict. Since `PortfolioEngine.apply_fill()` reads `fill["stop"]` and `fill["take_profit"]` to set on Position objects, positions never had stops — making ALL SL/TP evaluation inert across both controllers. Fixed by adding stop/take_profit preservation in `execution_simulator.py`. **Impact: benchmark return dropped from 13.84% to 6.72% because stops now correctly fire from entry. Max DD improved to -4.08% — this is the *correct* behavior, the previous higher return was from stops never triggering.**
  **Files:** `backtester/execution_simulator.py`.

  **Audit Correction B — Metrics Index Misalignment:**
  When the equity Series had NaN-dropped rows, `cockpit/metrics.py` used `self.snapshots["timestamp"].values[:len(eq_series)]` which took the first N timestamps instead of the timestamps aligned to the surviving rows. Fixed by using `self.snapshots.loc[eq_series.index, "timestamp"].values`.
  **Files:** `cockpit/metrics.py`.

  **Performance after all fixes:** Return: 6.72%, Sharpe: 0.919, Sortino: 1.025, Win Rate: 70%, Profit Factor: 1.44, Max DD: -4.08%.

  **Architectural takeaways:**
  1. **Trace the full data flow, not just the component.** Fix 1 (PnL) and Audit Correction A (stop propagation) both involved data that was correctly computed in one place but never reached its destination. Adding a method that computes the right value is worthless if the pipeline doesn't carry it through.
  2. **Parity between execution modes is non-negotiable.** BacktestController had full SL/TP evaluation; PaperTradeController had none. Any behavior difference between modes means paper trading results are meaningless for validating backtest results.
  3. **"Correct" sometimes means worse numbers.** The 13.84% → 6.72% return drop was the right outcome — stops that never fire produce artificially inflated returns. Max DD improving from unchecked to -4.08% confirms the risk management is now actually working.
  4. **Single source of truth eliminates drift.** Three PnL implementations, three metrics implementations — each slightly different. Consolidating to one canonical source (PortfolioEngine for PnL, MetricsEngine for metrics) eliminates the class of bugs where implementations diverge over time.

- **2026-04-18 | Regime-Conditional Edge Management + Portfolio Management (8-Phase Implementation) |** Implemented end-to-end regime-adaptive system across 8 phases. The core problem: edges like momentum have +2.0 Sharpe in bull and -1.5 in bear, but the Governor computed one blended weight. Now the system automatically adapts to the current regime.

  **Key architectural decisions:**
  1. **Welford's online algorithm for regime stats** — `RegimePerformanceTracker` uses running mean/variance without storing raw trades. Memory-efficient for indefinite accumulation. Persisted to JSON.
  2. **Blended weights with graceful fallback** — `alpha * regime_weight + (1-alpha) * global_weight` where `alpha = 0.7`. Falls back to global when regime has < `min_trades_per_regime` (default 8). System works identically until regime data accumulates.
  3. **Trade fills tagged at execution time** — Every fill now carries `regime_label` from the macro regime. No reliance on post-hoc timestamp joins. This is the foundation for organic regime performance data.
  4. **Learned affinity replaces static tables** — `MACRO_EDGE_AFFINITY` in advisory.py was a hardcoded guess. `get_learned_affinity()` computes data-driven per-category multipliers (clamped 0.3-1.5x) by comparing regime-specific to global performance.
  5. **Advisory constraints can only tighten** — Risk Engine's dynamic `max_positions`, `max_gross_exposure`, `sector_cap` from advisory are floored by config values. Engine E can recommend caution but never increase risk beyond configured limits.
  6. **Vol targeting as portfolio overlay** — `w @ cov @ w` portfolio vol estimation applied as a scalar (0.3-2.0x) to align actual vol with target. Runs after mode-specific allocation (adaptive/MVO) but before exposure cap.
  7. **Allocation discovery is evaluate-only by default** — `auto_apply_allocation: false`. The system recommends but doesn't act without explicit opt-in. Composite scoring: `0.4*Sharpe + 0.3*Calmar - 0.2*|MDD| - 0.1*turnover`.

  **Files created:** `engines/engine_f_governance/regime_tracker.py`, `engines/engine_c_portfolio/allocation_evaluator.py`.
  **Files modified:** `governor.py`, `alpha_engine.py`, `signal_processor.py`, `risk_engine.py`, `policy.py`, `portfolio_engine.py`, `backtest_controller.py`, `governor_settings.json`.

  **Lessons:**
  - **Backward compatibility is free with defaults** — all new parameters default to `None`. Without regime data, the system behaves identically to before. No migration required.
  - **"Amplify winners" requires proven data** — The 2026-04-16 lesson about edge affinity being counterproductive at 26% win rate is now addressed: affinity is only applied when backed by regime-specific trade statistics, not static assumptions.
  - **Portfolio-level vol targeting addresses concentration risk** — Individual position sizing (Risk Engine) doesn't prevent overall portfolio vol from spiking when positions are correlated. The overlay in policy.py addresses this at the portfolio level.

- **2026-04-20 | Regime Classification Threshold Fix |** The macro regime classifier in `advisory.py:_compute_macro_regime()` had a "transitional" default that dominated 89% of all bars in 2024 — a clear bull year. Two structural issues:
  1. **High confidence threshold (0.40):** The classifier required >40% probability to assign a regime. With 5 axes that can partially conflict (e.g. bull trend + narrow breadth + elevated correlation), no single regime won decisively. The 0.40 bar was too high for a 5-way classification where probability mass is naturally spread.
  2. **Transitional base score (0.30) was too competitive:** "Transitional" was seeded at 0.30 before normalization, nearly matching the score of real regimes when axes partially agreed. This let it win ties.

  **Fix:** Lowered transitional base score to 0.15, threshold to 0.25. Multi-year validation (2021-2024) confirmed: 2021 bull → mostly robust_expansion/emerging_expansion, 2022 → emerging_expansion with cautious_decline/market_turmoil appearances, 2023 → mixed cautious_decline and expansion, 2024 → expansion. Regime labels now match intuitive market character across all 4 years.

  **Before/After (2024-only backtest):** Return 1.77% → 4.56%, Sharpe 0.397 → 1.161. This isn't from overfitting — the improvement comes from the regime-conditional infrastructure (Phases 1-8) finally being activated instead of running in perpetual "transitional" fallback mode.

  **Files:** `engines/engine_e_regime/advisory.py`.

- **2026-04-20 | Governor Regime Tracker Window Bug |** The Governor's regime tracker was being fed from `dfw` (the 90-day rolling window subset) instead of `df` (all trades). Since the tracker uses Welford's online algorithm designed for indefinite accumulation, restricting it to 90 days meant only ~7 trades reached it out of 53. Fixed by iterating `df` instead of `dfw` at governor.py line 317. The rolling window correctly limits *edge weight computation* (recency matters for weights), but the regime tracker needs all historical data to learn regime-specific patterns.

  **Files:** `engines/engine_f_governance/governor.py`.

- **2026-04-20 | CockpitLogger regime_label Column Missing |** `TRADE_COLUMNS` class attribute in `cockpit/logger.py` didn't include `"regime_label"`. The column was added to the row dict in `log_fill()` but `_ensure_csv_headers()` wrote headers without it at init time, and `_flush_buffer()` writes with `header=False`. Result: regime_label data was silently dropped from all trade CSVs. Fix: added `"regime_label"` to `TRADE_COLUMNS`. **Rule: when adding a new field to any CSV row dict, always update the corresponding COLUMNS class attribute.**

  **Files:** `cockpit/logger.py`.

- **2026-04-20 | Multi-Year Backtest — Short Bias Discovery (OPEN) |** Running the first multi-year backtest (2021-2024) revealed a critical structural bug: the system is **massively short-biased**. Over 4 years: 87 shorts vs 34 longs. From 2022-2024, effectively zero long entries. `rsi_bounce` (which should buy oversold stocks) is 98% short (44 shorts vs 1 long). `atr_breakout` is 78% short. This is not a parameter issue — it's a structural inversion somewhere in the signal-to-side conversion pipeline. The result: -$3,186 over 4 years while the S&P returned ~60%.

  **Per-year impact:**
  - 2021 (strong bull): -4.07% — momentum_edge lost $2,653 on 29 trades (34% WR), mostly shorting into a rally
  - 2022 (bear): -0.03% — only 12 entries, near-flat (ironically, shorts should have helped here)
  - 2023 (recovery): -0.64% — 21 entries, all short
  - 2024 (bull): +1.58% — some improvement from regime-conditional logic but still short-heavy

  **Status: UNRESOLVED.** Root cause is in the signal generation or signal-to-side conversion pipeline. Needs end-to-end trace from edge signal → SignalProcessor → SignalFormatter → BacktestController to find where positive signals become short entries.
