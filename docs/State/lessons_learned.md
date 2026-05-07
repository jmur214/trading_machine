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

- **2026-04-21 | Short Bias Bug — RESOLVED |** The 72% short bias was not a single inversion — it was four compounding layers each silently overriding user intent. Tracing the signal pipeline end-to-end found zero inversion; the bug was in the *configuration* plumbing:

  1. **`orchestration/mode_controller.py` hardcoded all edge weights to 1.0** at both `__init__` and `run_backtest()` entry points, ignoring `config/alpha_settings.{env}.json`. This made `rsi_bounce_v1: 0.0` (a deliberate silence) effectively `1.0`, reactivating the worst-performing edge. Fix: load edge weights from config, default to 1.0 only for edges the config doesn't mention.
  2. **`alpha_settings.prod.json` had diverged from the tuned `alpha_settings.validated.json`** — all edges at 1.0 instead of the curated weights (atr_breakout=2.5, rsi_bounce=0.0, bollinger_reversion=0.0). The ENV=prod default meant nobody was using the validated settings. Fix: synced prod config.
  3. **`portfolio_settings.json` had `min_weight: -0.05`**, letting MVO allocate small short weights even when the intent was long-only. Path A sizing in risk_engine converted these into short orders. Fix: `min_weight: 0.0` as the baseline (shorts re-enableable when `allow_shorts=true` is intentional).
  4. **Stale governor `edge_weights.json` from the broken system** had learned `atr_breakout=0.055`, `momentum=0.09` — quality scores from a period when the system was actively losing money while short. These persisted across runs and muted the edges even after code fixes. Fix: reset (moved to `.bak`) so the governor learns fresh from the corrected pipeline.

  **Architectural takeaway:** No single layer was "wrong" — each was doing its job locally. The bug lived in the handoffs. When `mode_controller` quietly supplies 1.0 defaults, when `prod.json` quietly drifts from `validated.json`, when MVO quietly accepts `min_weight=-0.05`, and when the governor quietly remembers old weights, the user's carefully tuned config becomes a fiction. **Rule: for any config value that flows through 3+ layers, write a single integration assertion that round-trips the value from config file → live engine — otherwise silent overrides accumulate.**

  **Post-fix 4-year backtest:** +0.26% return, Sharpe 0.041, 54% win rate, trades across all 4 years. Short bias eliminated. Performance is alive but weak — exposure and signal-strength tuning are the next bottleneck, not directional bias.

  **Files:** `orchestration/mode_controller.py`, `config/alpha_settings.prod.json`, `config/portfolio_settings.json`, `data/governor/edge_weights.json` (reset).

- **2026-04-22 | Alpha Diagnosis — Deployment Problem, Not Alpha Shortage |** Before optimizing further, pulled per-edge per-regime Sharpe from `regime_edge_performance.json` to check whether the weak global Sharpe reflected weak alpha or poor deployment of existing alpha. Finding: `momentum_edge_v1` has Sharpe **4.97 in `robust_expansion`** and **4.68 in `emerging_expansion`** (strong, clear alpha) but gets diluted to Sharpe 1.29 globally because it's also run in `cautious_decline` (-0.26) and `market_turmoil` (-3.30) where it structurally loses money. `atr_breakout_v1` shows the same pattern — positive Sharpe in expansion regimes, negative in decline regimes.

  **Architectural takeaway:** The alpha exists. The bug is that the governor deploys the same edge into regimes where its tracker-measured Sharpe is negative. Any work on "finding more alpha" is premature until we stop deploying known-losing edges into known-losing regimes. **Rule: measure per-edge per-regime performance before proposing risk-layer patches. If an edge has clear regime-specific profitability, the fix is in the governor's deployment logic (gating), not in risk sizing or portfolio vol targeting.**

- **2026-04-22 | Governor Kill-Switch Dilution Bug |** Original `StrategyGovernor.get_edge_weights()` blended regime-specific and global weights as `alpha * regime + (1-alpha) * global` with `alpha=0.7`. When the regime tracker correctly returned `regime_weight=0.0` for an edge that was structurally unprofitable in a regime (Sharpe ≤ disable threshold), the blend still gave that edge **30% of its global weight** — so a "killed" edge kept taking 30%-sized positions in its adverse regime.

  **Fix:** Kill-switch passthrough in `get_edge_weights()`. If `regime_val <= 1e-9`, return 0.0 directly. Otherwise blend as before. The tracker's `get_regime_weight` already distinguishes "weak regime performance" (soft down-weight at 0.25+) from "structurally unprofitable" (hard zero). The blend should honor that distinction instead of collapsing both cases.

  **Architectural takeaway:** The blend was motivated by wanting robustness when regime data is sparse — a sensible goal — but conflated two very different signals. Don't let a defensive default silently override a deliberate hard decision from a downstream component. **Rule: when blending two signals where one can deliberately emit "off," the blend must preserve the "off" state as a special case.**

  **Files:** `engines/engine_f_governance/governor.py`. Claimed post-fix impact: Sharpe 0.94→1.08, CAGR 7.07%→7.87% — but see 2026-04-22 determinism entry below; this claim needs reconfirmation under pinned-state methodology.

- **2026-04-22 | Adverse-Regime Stop-Tightening — Falsified |** Hypothesis: "tighten trailing stops on open positions whose edge has `regime_weight=0` in the current regime" would cut the residual tail bleed from positions that entered in favorable regimes and then drift through adverse regimes before hitting exits. The kill-switch fix solved *entry* gating; stops on already-open positions sit at wide entry-time levels regardless of current regime.

  **Result:** Falsified. Sharpe 1.08→0.96, CAGR 7.87%→7.27%, MDD -12.33%→-14.17% (worse).

  **Asymmetry discovered:**
  - `market_turmoil` (severe, cliff-fall regime): `atr_breakout_v1` went -$448 → +$670. Tightening helped.
  - `cautious_decline` (mildly adverse, choppy regime): `atr_breakout_v1` exits went -$3,001 → -$18,243. Tightening got whipsawed by normal chop; positions that would have recovered got closed at small losses that accumulated.

  **Architectural takeaway:** This is the same "cut winners short" pattern as the 2026-04-16 signal-exit bleed finding, just expressed through stop-loss mechanics. Any intervention that closes positions earlier in choppy regimes inherits the same problem: you can't distinguish temporary pullbacks from true adverse drift, and the math of asymmetric winners/losers means cutting both classes roughly equally is net-negative. **Rule: don't try to retroactively de-risk open positions when the regime turns against them. Act at entry-gating (the kill-switch layer), not at exit. Future regime-transition de-risking attempts must either (a) condition on severity — only tighten in market_turmoil-like cliff regimes, not cautious_decline-like chop — or (b) operate at a different dimension (portfolio-level exposure cuts, not per-position stops).**

  **Files:** `engines/engine_b_risk/risk_engine.py`, `backtester/backtest_controller.py` — reverted after the falsification.

- **2026-04-22 | Backtest Non-Determinism — State Mutation Between Runs |** Two back-to-back backtest runs with identical code produced Sharpe 0.7536 vs 0.9458 (9912 vs 9915 trades). Investigated RNG (all seeded, none in hot path), `set()` iteration order (only used for debug logging), threading (daemon threads only, not in data flow), and concurrent futures (data prefetch is order-preserving via `asyncio.gather`). None of those explained it.

  **Root cause:** `ModeController.run_backtest()` calls `governor.update_from_trades(...)` + `governor.save_weights()` at the end of every run (unless `--no-governor` is passed). This rewrites `data/governor/edge_weights.json` AND `data/governor/regime_edge_performance.json`. Run 2 therefore reads post-run-1 state from disk, not the same state run 1 read. Verified: `regime_edge_performance.json` (28837 bytes) differs from the pre-run anchor (28871 bytes); `atr_breakout_v1._global.trade_count` went from 7762 → 9056 between runs — exactly the ~1300 trades the first run added.

  **Implication:** ALL prior A/B claims made without pinning governor state before each run are polluted by seed drift. Including the 2026-04-22 kill-switch claim above. They must be re-verified.

  **Fix:** Documented in `execution_manual.md` — use `--no-governor` flag (already exists) combined with manual anchor restoration before each run. `scripts/run_deterministic.py` wrapper automates the anchor save/restore + md5 comparison for reliable A/B testing.

  **Architectural takeaway:** Any component that writes to disk at end-of-run creates implicit state coupling between runs. "The code is deterministic" and "the experiment is deterministic" are different claims. For any A/B methodology going forward, the experiment setup must pin every input that could change between runs — including files the code itself writes. **Rule: before claiming a code change moved a metric, run the experiment with pinned state (`--no-governor` + restored anchor) or the claim is pollution-level noise.**

  **Files:** `docs/Core/execution_manual.md` (methodology), `scripts/run_deterministic.py` (helper).

- **2026-04-23 | Backtest Determinism — Logger Thread Race (final root cause) |** The 2026-04-22 non-determinism fix (anchor + `--no-governor`) got us most of the way, but canonical md5 still diverged across runs. Three additional sources were identified and fixed in sequence: (1) Python randomizes string hash seeds per-process by default, so `set()` iteration order differed across invocations — added `PYTHONHASHSEED=0` self-reexec guard in `scripts/run_deterministic.py`; (2) three `set(a) | set(b)` unions in `engines/engine_f_governance/governor.py` (lines 337, 391, 600) and a `Path.glob()` in `engines/engine_a_alpha/edges/news_sentiment_edge.py:81` fed FP aggregation in insertion order — wrapped in `sorted()`; (3) the real smoking gun was a thread race in `cockpit/logger.py._append_to_csv`, which mutated `self._trade_buffer` without a lock while the background `_auto_flush_loop` thread iterated the same buffer inside the lock. The main thread would append a row with a slightly different column set mid-iteration, producing `ValueError: Length of values (N) does not match length of index (M)` tracebacks and off-by-~30 trade log row counts between runs.
  
  **Diagnosis method:** Five md5 probes at a known divergence bar (2021-02-16) — at SignalCollector output, SignalProcessor output, governor-blended weights, RiskEngine-prepared orders, and sorted-orders — ALL matched across runs, proving the pipeline itself was deterministic. Snapshots canon matched while trades canon diverged. That asymmetry (portfolio state identical, only the trade log content differed) plus the concurrent `ValueError` tracebacks from the logger thread confirmed the race. Fix: wrap the append in `with self._lock:` and defer flush calls until after lock release; wrap `_auto_flush_loop` in try/except (removed the racy `if self._lock.locked(): continue` advisory check).
  
  **Verification:** `PYTHONHASHSEED=0 python -m scripts.run_deterministic --runs 3` now produces identical canon md5 for both `trades.csv` and `portfolio_snapshots.csv` across 3 runs. Raw md5 still diverges (per-run UUID in `run_id` and stringified `meta` — expected).

  **Architectural takeaway:** "Race conditions in CSV writers look like non-determinism but are really data corruption." Any background thread that touches a shared mutable buffer must protect every read AND write with the same lock. Advisory checks like `if self._lock.locked(): continue` don't close the race — they just lower the probability. Writing under a lock and iterating without one is UB regardless of how short the iteration is.

  **Files:** `cockpit/logger.py`, `scripts/run_deterministic.py`, `engines/engine_f_governance/governor.py`, `engines/engine_a_alpha/edges/news_sentiment_edge.py`, `orchestration/mode_controller.py`, `engines/engine_c_portfolio/policy.py`, `docs/Core/execution_manual.md`.

- **2026-04-23 | Kill-Switch Passthrough — Sharpe claim falsified under deterministic methodology |** The 2026-04-22 claim that adding the kill-switch passthrough (`elif regime_val <= 1e-9: return 0.0` in `governor.get_edge_weights`) moved Sharpe 0.94→1.08 was re-measured on the newly-deterministic harness. Result: reverting the passthrough produces **bitwise-identical canon md5s**, Sharpe 0.98 both ways. Delta = 0.00. The prior claim was entirely noise from the logger thread race documented above.
  
  **Why the branch is dormant:** `data/governor/regime_edge_performance.json.anchor` currently contains trade stats for only 3 regimes (`emerging_expansion`, `_global`, `robust_expansion`), all with net-positive per-edge performance. `RegimeTracker.get_regime_weight()` only returns 0.0 when an edge is explicitly killed (negative Sharpe over ≥ `min_trades_per_regime`). No such condition is satisfied by the current anchor. Missing regimes (cautious_decline, stressed, crisis) return `None`, hitting the first `if regime_val is None:` branch, not the passthrough.
  
  **Action:** Passthrough code retained — it's principled defense for when the tracker eventually accumulates kill-condition data. ROADMAP entry updated to reflect the falsification. Memory updated (`project_killswitch_passthrough_win.md` replaced with falsification record).
  
  **Architectural takeaway:** Sharpe deltas under ~0.2 magnitude measured before 2026-04-23 are unreliable. "The code is correct" and "the code moves the metric" are independent claims — verify both under a deterministic harness before citing a number. And when the mechanism-of-action is *conditional* (branch only fires under specific tracker state), check whether that state is reachable in the test data before claiming the branch caused the observed delta. **Rule: any reported metric improvement must include the bitwise-canon md5 delta that accompanied it — if md5s match both before and after the change, the claim is false.**
  
  **Files:** `engines/engine_f_governance/governor.py` (passthrough retained), `docs/State/ROADMAP.md`, memory files.

- **2026-04-23 | Regime-Conditional Activation — Architecture Correct, Inputs Broken |** While investigating why the kill-switch never fired, surfaced a structural gap: `StrategyGovernor._regime_weights` was populated ONLY inside `update_from_trades()`, which (a) runs end-of-backtest and (b) is gated on `not no_governor`. Under the deterministic harness (`--no-governor`) and even in normal runs, regime-conditional weighting was unreachable during trade generation — `get_edge_weights(regime_meta)` always fell through to `self._weights` (global). All three regimes looked identical in A/B tests because they were.

  **Architecture fix:** Added `_rebuild_regime_weights_from_tracker(edge_names)` method and called it from `__init__` after `regime_tracker.load()`, gated on `regime_conditional_enabled`. `update_from_trades` refactored to reuse it. Determinism preserved: 3-run PASS, canon md5 `f01e7307b37fcd96f2c781458c43b0ca` (different from pre-priming baseline `3bbb650c3df5fba7cfe739ec00a39eb2`, confirming the change actually alters trade behavior).

  **Activation result — catastrophic:** Sharpe 0.98 → **-0.368**, return +7.2% → -5.07%, MDD -12.78% → -16.67%, trade volume 9865 → ~2500. Delta measured under pinned deterministic harness, so this is real, not noise.

  **Root cause — kill-switch over-pruning (single issue; initial "phantom amplification" hypothesis FALSIFIED).** Re-measured under clean edge_weights.json (phantom entries removed, see next entry): canon md5 is **bitwise-identical** with vs. without phantoms (`f01e7307b37fcd96f2c781458c43b0ca` both times). Phantoms had zero effect on trade behavior because signal_processor never looked up their non-matching names. The entire Sharpe crash is the kill-switch itself, not weight amplification.

  What actually happens: activation populates `_regime_weights` from the anchor. `get_edge_weights(regime_meta)` returns weight 0.0 for any edge whose in-regime sr ≤ `disable_sr_threshold` (0.0 default). In `cautious_decline`, atr_breakout_v1 (sr -1.97), momentum_edge_v1 (sr -0.28), Unknown (sr -2.02) all get killed. Same for `market_turmoil`. Trade volume drops 9865 → ~2500 (75% reduction). Sharpe 0.98 → -0.368.

  The anchor's regime-conditional Sr values are mathematically correct — those edges DO lose money in those regimes on average. But two factors make a hard kill net-negative:
  1. **Over-pruning.** Killing 75% of trade volume to avoid the 15% worst bucket means we also kill 60% of profitable trades. The losing trades in cautious_decline are real but outweighed in the pre-activation baseline by profitable trades in other regimes; the kill cuts both indiscriminately.
  2. **Classifier label drift at the margins.** `cautious_decline` in 2023-2024 includes brief pullback days inside overall bull runs (~10-18% of 2023-2024 trading days). These days are marginally down but recover quickly. Bull-entries on those days would have recovered if held. The kill closes them at pullback lows. This is the same failure mode already acknowledged at [signal_processor.py:225-228](engines/engine_a_alpha/signal_processor.py#L225) ("Regime detection misclassifies 2023-2024 bull markets as 'cautious_decline'"), re-opened through the kill-switch door after directional suppression was already disabled for it.
  3. **Same asymmetric-chop-hurt pattern as the 2026-04-22 stop-tightening falsification** (`project_adverse_regime_stop_tighten_falsified.md`). Cliff regimes (`market_turmoil`) may reward de-risking; chop regimes (`cautious_decline`) punish it because you can't distinguish temporary pullbacks from true adverse drift.

  **Action:** `regime_conditional_enabled: false` in [config/governor_settings.json](config/governor_settings.json). Priming code retained (zero cost when disabled). Do NOT re-enable without first changing the kill semantics — candidates to measure: (a) soft-kill (weight 0.25-0.33 instead of 0.0) to preserve pullback-recovery signal; (b) severity-gated kill (hard only in market_turmoil, soft in cautious_decline); (c) classifier fix to narrow cautious_decline. Pick per principled rule change, not hand-chosen threshold.

  **Architectural takeaway:** "The regime-conditional Sr values are correct" ≠ "a hard kill on that signal helps overall returns." The math of asymmetric wins/losses means binary policies (0 vs 1) are often net-negative compared to soft-weighted policies even when the underlying signal is real. **Rule: when a historical-average says regime X is bad for edge Y, that is evidence for a soft weight reduction, not for a hard kill. Binary policies need binary evidence (e.g. MDD > 20% sustained), not average-SR evidence.**

  Also: **before attributing a regression to hypothesis H, run the A/B with H removed.** I initially attributed this Sharpe crash partly to phantom weight amplification. Running the test with phantoms cleaned showed canon md5 identical — falsifying H. The crash is 100% the kill-switch. Saved time by checking before building atop the bad hypothesis.

  **Files:** `engines/engine_f_governance/governor.py` (priming method retained, disabled via config), `config/governor_settings.json`, memory `project_regime_conditional_activation_blocked_2026_04_23.md`.

- **2026-04-23 | Phantom Placeholder Edge Weights — Pollution Closed |** During the regime-conditional activation investigation, noticed that `data/governor/edge_weights.json` contained entries for `another_edge: 0.99` and `edge_name: 0.97` — edges that don't exist anywhere in the codebase. Tracing with a `traceback.print_stack` patched onto `save_weights` showed two writes happen inside every backtest:

  1. [backtester/backtest_controller.py:816](backtester/backtest_controller.py#L816) `_post_run()` called `analytics.edge_feedback.update_edge_weights_from_latest_trades()` unconditionally — bypassing the `--no-governor` flag that mode_controller's separate gated call (line 847-849) respected. This meant every deterministic run still mutated governor state despite `--no-governor`, which the whole `scripts/run_deterministic.py` wrapper is built to prevent.
  2. `update_from_trade_log` → `merge_evaluator_recommendations` reads `data/research/edge_recommendations.json` and EMA-blends its `recommended_weights` into the governor. That file (from 2025-10-22) contained literal placeholder content: `{"recommended_weights": {"edge_name": 0.42, "another_edge": 0.8}}`. Months of backtest runs EMA-accumulated these placeholders into the persistent governor state.

  **Fix:** (a) Removed the redundant `_post_run` call — mode_controller already handles governor feedback post-backtest with proper `--no-governor` gating, so this was duplicated work AND a gate bypass. (b) Moved `data/research/edge_recommendations.json` → `.stale-placeholder` (inspection-safe, not deleted).

  **Falsification side-effect:** The phantom entries turned out to have zero impact on trade behavior — canon md5 is bitwise-identical with or without them, because signal_processor's edge-lookup loop never matched those names. They were cosmetic pollution in the state file, not a semantic bug. Initially hypothesized they were "~2300x amplifying real edges under the blend"; the with/without A/B falsified that. The real regime-conditional issue is entirely the kill-switch policy (see entry above).

  **Architectural takeaway:** "State file looks wrong" and "state file affects outcomes" are separate claims that require separate evidence. Also: **any code path that merges external recommendations into persistent state must validate that the external file is live (not a 6-month-old placeholder).** A one-time file-presence check is not enough. Consider schema-versioning recommendation files or requiring an explicit `updated_at` timestamp newer than N days. **Rule: persistent-state EMA accumulation from an external file is a silent failure mode. If the external file ships broken once, the state carries it forever.**

  **Files:** `backtester/backtest_controller.py` (removed redundant feedback call), `data/research/edge_recommendations.json` (parked as `.stale-placeholder`).

- **2026-04-23 | Regime-Conditional Walk-Forward — Mechanism Falsified OOS |** After three in-sample A/B variants (baseline 0.98, hard-kill -0.37, soft-kill 0.83, all on the same 2021-2024 window that the anchor was trained on), built a walk-forward harness at [scripts/walk_forward_regime.py](scripts/walk_forward_regime.py). Phase 1 trains the regime_tracker on 2021-2022 only (governor ON, regime_conditional ON so stats accumulate, tracker starts empty so kill-switch is inert during training). Phases 2-4 restore that OOS anchor and evaluate the three policy variants on held-out 2023-2024 with `--no-governor`. Config + governor state auto-restored on exit via try/finally.

  **First run found a harness bug:** Phase 1 had `regime_conditional_enabled=false`, but [governor.py:351-352](engines/engine_f_governance/governor.py#L351) only calls `regime_tracker.record_trade(...)` when this flag is True. The trained anchor was empty → all three eval phases produced bitwise-identical results. Fixed by setting the flag True during training (the tracker starts empty, so kill-switch is inert regardless — the flag just gates accumulation, not application-while-empty).

  **Results — three walk-forward splits:**

  | Split | Train | Eval | Baseline | Soft-kill | Δ |
  |---|---|---|---|---|---|
  | A | 2021-2022 | 2023-2024 | 1.92 | 1.42 | **-0.50** |
  | B | 2021-2023 | 2024-2025 | 1.025 | 1.201 | **+0.18** |
  | C | 2021-2024 | 2025 | 0.66 | 0.451 | **-0.21** |

  Central tendency: 2 of 3 negative. Split B is a positive outlier that overlaps 2024 with both negative splits — so it's not a clean "mechanism helps in regime X" pattern.

  **Mid-session corrections:**
  - After Split A: declared "mechanism falsified OOS" (decisively -0.50 Sharpe). Updated memory + ROADMAP + PROJECT_CONTEXT accordingly. **Premature** — one split.
  - After Split B: result flipped to +0.18. Retracted "falsified", rewrote docs as "split-dependent". Still inadequate evidence either way.
  - After Split C: returns to negative -0.21. Three-split central tendency: net-negative with one outlier. Rewrote docs again as "net-negative with noise, consider redesigning signal source rather than iterating policy".

  **Architectural takeaway:** For a conditional mechanism, one walk-forward split is not enough evidence. Two splits can disagree; three splits give central tendency. The OOS window's own regime mix interacts with the mechanism's trigger conditions — so OOS evaluation windows must be diverse in their regime composition for the walk-forward to be meaningful.

  **Methodology lesson (3x self-correction in same session):** After Split A, the -0.50 Sharpe delta felt decisive — large enough to declare a falsification. Writing it down in memory + 3 other docs within minutes was the mistake. Split B flipped the sign; Split C returned to negative; now the picture is "net-negative with noise." Each documentation cycle I did could have been deferred until ≥3 data points existed. **Rule: for any conditional mechanism's walk-forward verdict, require ≥3 splits with different eval-regime compositions before writing the verdict into durable docs. "Decisive-feeling" single-split results have 30%+ probability of being reversed.**

  **Files:** `scripts/walk_forward_regime.py` (reusable walk-forward harness, `--train-start/--train-end/--eval-start/--eval-end` args), docs + memory updated three times (falsified → split-dependent → net-negative with noise).

- **2026-04-24 | Learned Edge Affinity — In-Sample Load-Bearing, Data Source Unreliable |** Added `learned_affinity_enabled` config flag to `GovernorConfig` + gated the injection in `backtester/backtest_controller.py:308` so this advisory layer can be A/B'd. Regression check confirmed default True preserves baseline canon md5 `3bbb650c3df5fba7cfe739ec00a39eb2` / Sharpe 0.98.

  **3-run A/B under deterministic harness (in-sample 2021-2024):**
  - Affinity ON: Sharpe 0.98, CAGR 7.20%, MDD -12.78%, WR 45.12%.
  - Affinity OFF: Sharpe 0.866, CAGR 6.28%, MDD -12.56%, WR 45.72%.
  - Delta: **-0.114 Sharpe, -0.92% CAGR** when disabled. The feature IS contributing something in-sample.

  **Interpretation caveat:** The feature reads from `regime_tracker._data` — the same per-edge per-regime sr stats we just walked-forward (3 splits) and showed net-negative for the per-edge-per-regime kill-switch. The in-sample 0.11 Sharpe gain could well be circular — the tracker accumulated its stats on the very trades we're now evaluating, applied as a 0.3-1.5x multiplier on the signals that generated those trades. Until a walk-forward run compares affinity-ON vs affinity-OFF on held-out windows, treat the 0.11 in-sample gain as suspect.

  **Action:** Flag retained at default True (so baseline unchanged). Walk-forward variant for affinity-specifically NOT yet built. Do NOT cite "affinity adds 0.11 Sharpe" as a validated claim.

  **Architectural takeaway:** The same failure mode likely applies to every feature whose config flag is "enabled" today and whose signal comes from `regime_tracker`: learned_affinity, the regime_conditional kill-switch, any exposure-cap overlay that indexes by regime label. They all share the same potentially-overfit data source. Walk-forward is the only way to know which are real and which are circular.

  **Rule:** An in-sample A/B where feature-ON beats feature-OFF is **not** evidence that the feature helps. It's evidence that SOMETHING differs when it's on. For features that train and apply on the same window, that "something" is often just the model fitting its own history.

  **Files:** `engines/engine_f_governance/governor.py` (added `learned_affinity_enabled` to `GovernorConfig`), `backtester/backtest_controller.py` (gated affinity injection), `config/governor_settings.json` (added flag, default True), memory `project_learned_affinity_in_sample_load_bearing.md`.

- **2026-04-24 | First Autonomous Lifecycle Action — `atr_breakout_v1` Auto-Paused |** After shipping Phase α/β/γ of the lifecycle plan (benchmark gates, evolution_controller plumbing fix, LifecycleManager) and flipping `lifecycle_enabled: true`, ran a full backtest (no `--no-governor`). The system performed its first autonomous lifecycle action in project history:

  ```
  edge_id: atr_breakout_v1
  old_status: active → new_status: paused
  triggering_gate: loss_fraction_-0.41
  edge_sharpe: -0.33   benchmark_sharpe: 0.87
  trade_count: 1274   days_active: 1455
  ```

  The pause gate fired because the trailing 30-trade `pnl_sum / abs_volume` was -0.41 — the edge lost 41% of recently deployed capital. Well below the -0.30 pause threshold. This edge had been in `active` status since project genesis, losing money consistently, with nothing in the code able to touch it. Until now.

  **Post-pause deterministic run (canon `5e2ae40a6b5049b4bba71681903d94aa`):**
  - Sharpe 0.98 → **0.862** (-0.12)
  - CAGR 7.20% → 6.14%
  - MDD -12.78% → **-10.47%** (+2.3pp better)
  - WR 45.12% → 48.74% (+3.6pp better)

  The canon md5 is **bitwise-identical** to an earlier manual `atr_breakout=0` experiment — confirming the lifecycle pause correctly silences the edge via `registry.list(status="active")` filter at [mode_controller.py:604](orchestration/mode_controller.py#L604).

  **The lifecycle mechanism works. The system is now meaningfully autonomous.** But the aggregate Sharpe dropped, which teaches an important composition lesson:

  **Architectural takeaway — aggregate effects of pruning:** Killing a losing edge doesn't automatically lift system Sharpe when the system's Sharpe is partially leverage-driven. `atr_breakout_v1` contributed 63% of all trade opens (5027 out of ~8000) in the baseline. Its per-trade PnL was negative, but its trade VOLUME was what the vol_target (2x cap) and risk_scalar (1.2x in benign) leverage stack rode on. Remove the volume, the amplifiers have less to amplify. **Rule: when retiring edges from a leverage-composed system, simultaneously add replacement alpha sources — otherwise you prune the denominator of the amplification ratio and the aggregate effect is negative even though each individual decision was correct.**

  **Design issue discovered — "revival deadlock":** The current lifecycle implementation treats "paused" as a full trading halt. The edge is filtered out of `registry.list(status="active")`, so no new signals are generated → no new trades → no data for the revival gate. The gate requires "last 20 post-pause trades show Sharpe > 0.5" — but there are no post-pause trades because the edge can't trade. Paused edges stay paused until human intervention. Fix (Phase α v2, deferred): implement "soft pause" — paused edges trade at 0.25x weight rather than being silenced entirely. Revival gate then has continuous data. Retired edges are the hard stop.

  **Why this matters for the roadmap:** Phase ε (demote the 12 remaining base edges + re-validate via Phase γ) is blocked until Phase α v2 lands the soft-pause. Otherwise mass demotion creates 12 more revival-deadlocked edges. The prudent next step is either (a) soft-pause implementation, or (b) Phase ζ replacement alpha templates that can fill the volume vacuum that pruning creates.

  **Rule of composition:** In a system with aggregate-level amplification (vol targeting, risk scaling), per-edge metrics underestimate the cost of removing that edge. A single-edge audit shows "atr_breakout loses money" → conclusion "retire it." A system-level audit shows "retiring atr_breakout costs 0.12 Sharpe." Both are true. The first is necessary; the second is sufficient. Always measure aggregate impact after any autonomous action.

  **Files:** `engines/engine_f_governance/lifecycle_manager.py` (new), `engines/engine_f_governance/governor.py` (evaluate_lifecycle method), `orchestration/mode_controller.py` (wired lifecycle into backtest path), `core/benchmark.py` (new), `engines/engine_d_discovery/discovery.py` (benchmark Gate 1), `engines/engine_f_governance/evolution_controller.py` (fixed missing subprocess), `scripts/run_evolution_cycle.py` (benchmark Gate 1), `config/governor_settings.json` (lifecycle_enabled:true, lifecycle_retirement_margin, lifecycle_min_trades, lifecycle_min_days), `data/governor/lifecycle_history.csv` (new audit trail), memory `project_first_autonomous_pause_2026_04_24.md`.

- **2026-04-24 | Soft-Pause Fix (Phase α v2) — Pareto Improvement Over Baseline |** The first-pause test revealed a revival deadlock: paused edges were filtered out of `registry.list(status="active")`, so they couldn't trade, so the revival gate (requires 20 recent trades with Sharpe>0.5, WR>0.45) never had data to fire. Paused was a one-way trip to silence.

  **Fix** (~10 LOC across 2 files): `EdgeRegistry.list_tradeable()` returns active+paused; `ModeController.run_backtest` applies a 0.25x weight multiplier to paused edges after constructing the config-weight dict. The 0.25x multiplier matches `sr_weight_floor` (the soft-kill floor in the regime_tracker mapping that we validated in walk-forward earlier).

  **3-variant A/B (deterministic harness, same anchor, atr_breakout_v1 paused):**

  | Variant | Sharpe | CAGR | MDD | WR |
  |---|---|---|---|---|
  | Baseline (all edges full weight) | 0.98 | 7.20% | -12.78% | 45.12% |
  | Hard-pause (silenced entirely) | 0.862 | 6.14% | -10.47% | 48.74% |
  | **Soft-pause (0.25x weight)** | **0.979** | **7.14%** | **-12.39%** | **50.48%** |

  Soft-pause is a Pareto improvement vs baseline: Sharpe matched (noise-level delta), MDD +0.39pp better, WR +5.36pp better. The system autonomously acted on a losing edge AND preserved aggregate Sharpe. First time this session a lifecycle change hasn't involved a tradeoff.

  **Why this works** (the aggregate-leverage rule from the first-pause lesson applied correctly): `atr_breakout_v1` contributed 63% of trade volume. Its per-trade PnL was negative, but its volume fed the `vol_target` (2x cap) + `risk_scalar` (1.2x benign) amplification stack. Hard-pause removes 100% of that volume → amplifiers have less to amplify → Sharpe drops 0.12. Soft-pause removes 75% of the per-trade risk while keeping 25% of the volume feeding the amplifiers → Sharpe preserved, loser exposure reduced.

  **Architectural takeaway — the correct semantics of "pause":** Paused should NOT mean silenced. It should mean "reduced trust, still participating, eligible for revival based on new evidence." This maps cleanly to how a human PM would manage a struggling strategy: not fire it, not give it full book, but let it prove itself at reduced size. **Rule: in any autonomous lifecycle system, "pause" is an information-preserving demotion, not a binary mute. Retirement is the binary mute.**

  **Meta-lesson on autonomy design:** The first-pause test looked like a mixed result (autonomy worked but Sharpe dropped). The second iteration (soft-pause) made the result a clean win. The lesson: when a first attempt at autonomy appears to cost something, examine whether the cost is inherent to the autonomy or just the first implementation. Often a refinement (soft-pause here, benchmark-relative gates earlier this session) turns a tradeoff into an improvement.

  **Files:** `engines/engine_a_alpha/edge_registry.py` (added `list_tradeable` + multi-status `list`), `orchestration/mode_controller.py` (soft-pause weight multiplier block), memory `project_soft_pause_win_2026_04_24.md`.

  **New post-autonomy baseline canon:** `d3799688ad14921a3e27e70231013d70`. Track all future Phase ε/δ/ζ deltas against this, not against pre-autonomy `3bbb650...`. The system is measurably better now (same Sharpe, better drawdown + win rate, AND autonomously demonstrating edge lifecycle management).

- **2026-04-24 | Portfolio Vol Targeting Is Leverage Amplification, Not Vol Targeting |** Added `vol_target_enabled` flag to `PortfolioPolicyConfig`, gated the overlay at [engines/engine_c_portfolio/policy.py:239-240](engines/engine_c_portfolio/policy.py#L239). Regression-matched baseline canon `3bbb650...` with flag True. 3-run A/B with flag False:

  - Baseline (vol_target ON): Sharpe 0.98, CAGR 7.20%, MDD -12.78%, Realized Vol 7.38%.
  - vol_target OFF: Sharpe 0.857, CAGR 5.99%, MDD -11.99%, Realized Vol 7.10%.
  - Delta: **-0.12 Sharpe, -1.21% CAGR, +0.79pp MDD (better)** when disabled.

  **Discovery about the mechanism:** `vol_scalar = clip(target_volatility / port_vol, 0.3, 2.0)`. With `target_volatility=0.15` in config but realized `port_vol` averaging ~0.076, the ratio is ~2.0x — the upper cap. So `_apply_vol_target` hits its 2.0x ceiling every bar. The "vol targeting" overlay isn't targeting at all; it's always-on 2x leverage. Disabling = native-signal weights. The -0.12 in-sample Sharpe is real-leverage-induced return.

  **Trust comparison with learned_affinity (same in-sample Sharpe magnitude):** learned_affinity depends on `regime_tracker._data` — anchor-fit, circular in-sample, walk-forward showed the data source is unreliable. vol_target depends on runtime-estimated portfolio vol — no historical fit, no circularity. So a +0.12 Sharpe from vol_target IS trustworthy in a way +0.11 Sharpe from affinity is not. Two features with identical in-sample signatures but very different trust levels.

  **Rule:** When auditing a feature's in-sample contribution, classify the data source: (a) runtime-current-state → trust the in-sample result (modulo window-specific vol levels); (b) anchor-fit-from-history → in-sample result is suspect, require walk-forward. Don't treat "feature X contributes Y Sharpe in-sample" uniformly.

  **Interpretation:** If intent was true vol targeting at 15% annualized, the system is currently 0.074/0.15 = 49% of target — the 2x ceiling is the binding constraint, not the target. To actually reach target would need raising `max_weight` (0.30 currently) or widening the `vol_scalar` upper cap (2.0). Current config is best described as "always 2x leverage up to `max_weight` clamps."

  **Files:** `engines/engine_c_portfolio/policy.py` (added `vol_target_enabled` to `PortfolioPolicyConfig`, gated overlay call), `config/portfolio_settings.json` (added flag, default True), memory `project_vol_target_in_sample_measured.md`.

- **2026-04-24 | Advisory Exposure Cap — Legitimate Risk Control |** Added `exposure_cap_enabled` flag to `PortfolioPolicyConfig`, gated `_apply_exposure_cap` call at [policy.py:242-243](engines/engine_c_portfolio/policy.py#L242). 3-run A/B with flag False:

  - Baseline (cap ON): Sharpe 0.98, CAGR 7.20%, MDD -12.78%, Vol 7.38%, WR 45.12%.
  - Cap OFF: Sharpe 0.817, CAGR 7.40%, MDD -14.26%, Vol 9.28%, WR 47.91%.
  - Delta: **-0.16 Sharpe, +0.20% CAGR, -1.48pp MDD (worse)** when disabled.

  Straightforward risk tradeoff: cap gives up 0.20pp CAGR to save 1.48pp MDD. Net Sharpe gain +0.16.

  **Mechanism:** [engines/engine_e_regime/advisory.py:174](engines/engine_e_regime/advisory.py#L174) computes `raw_cap = max(0.3, 1.0 - risk_score * 0.7)` where `risk_score` aggregates current regime-axis states. Runtime-current-state, NOT anchor-fit. [policy.py:332](engines/engine_c_portfolio/policy.py#L332) applies `if gross > cap: scale all weights by cap/gross`. Only binds when gross exposure exceeds the current regime's risk budget.

  **Trust-level classification continues to hold.** After three features audited this session:

  | Feature | Δ Sharpe (OFF) | Trust | Data source |
  |---|---|---|---|
  | learned_edge_affinity | -0.11 | **Suspect** | Anchor-fit (regime_tracker per-category) |
  | vol_target | -0.12 | **Trustworthy** | Runtime (port_vol estimate, clipped 0.3-2.0) |
  | exposure_cap | -0.16 | **Trustworthy** | Runtime (risk_score from regime detection) |

  **Rule reinforced:** The audit consistently separates feature trust by data source — runtime-current-state vs historical-anchor-fit. Two features (vol_target, exposure_cap) sourced from runtime give trustworthy in-sample deltas. One feature (learned_affinity) sourced from anchor needs walk-forward before accepting its in-sample number. The per-edge-per-regime kill-switch (also anchor-sourced) already failed its walk-forward. Infer: **audit by data source first, not by in-sample Sharpe.**

  **Architectural observation:** The two trustworthy overlays compose as: `native_weights → vol_target (2x up) → exposure_cap (clamp if regime risk-off)`. When both fire, they partially cancel (cap claws back vol_target's amplification in adverse regimes). Net system is effectively "trade at 2x leverage in benign regimes, clamp back toward 1x in adverse ones."

  **Files:** `engines/engine_c_portfolio/policy.py` (added flag + gate), `config/portfolio_settings.json` (flag added, default True), memory `project_exposure_cap_legit_risk_control.md`.

- **2026-04-24 | Risk-Engine Advisory Bundle — Largest Single In-Sample Contribution |** Added `risk_advisory_enabled` to `RiskConfig`, gated the 4-way advisory-consumption block at [risk_engine.py:474](engines/engine_b_risk/risk_engine.py#L474). Four mechanisms fire when advisory is consumed: `suggested_max_positions` (tightens concurrent-position count), `suggested_exposure_cap` (order-level gross cap, separate enforcement point from policy layer), `risk_scalar` (0.3-1.2x multiplier on ATR sizing — AMPLIFIES in benign regimes), correlation-regime sector cap adjustment.

  **3-run A/B (in-sample 2021-2024):**
  - Baseline (ON): Sharpe 0.98, CAGR 7.20%, MDD -12.78%, WR 45.12%.
  - OFF: Sharpe 0.736, CAGR 5.66%, MDD -13.25%, WR 41.72%.
  - Delta: **-0.24 Sharpe, -1.54% CAGR, -0.47pp MDD (worse), -3.40pp WR (worse)**. Largest single Sharpe delta in the entire audit session.

  **Mechanism takeaway — composite leverage:** risk_scalar defaults to 1.2x in benign regimes (via `clip(1.2 - risk_score*0.9, 0.3, 1.2)` in advisory.py). vol_target is always 2x (cap-saturated). So in benign regimes the system operates at **~2.4x leverage** (`1.2 × 2.0`). exposure_cap and max_positions then clamp back in adverse regimes. This is NOT "trade at native signal magnitudes" — the system is heavily levered by default and throttled conditionally.

  **End-of-audit scorecard:**

  | Feature | Δ Sharpe (OFF) | Data source | Trust |
  |---|---|---|---|
  | Per-edge-per-regime kill | -0.50 avg OOS (3-split walk-forward) | Anchor-fit | Failed |
  | `learned_edge_affinity` | -0.11 in-sample | Anchor-fit | Suspect — needs walk-forward |
  | `vol_target` | -0.12 in-sample | Runtime | Trustworthy |
  | `exposure_cap` (policy) | -0.16 in-sample | Runtime | Trustworthy |
  | `risk_advisory` (risk engine) | -0.24 in-sample | Runtime | **Trustworthy, largest** |

  **Architectural rule reinforced across 5 audits:** Audit by data source first, not by in-sample Sharpe. All 5 features have similar-magnitude in-sample deltas (0.11-0.50). The ones sourced from runtime-current-state hold up; the ones sourced from historical-anchor-fit need walk-forward and frequently fail it. Before investing in a feature's future, classify: does it read from the current bar only, or does it read from an accumulator trained on prior data? The latter has ~40-50% probability of being overfit to its training window.

  **Files:** `engines/engine_b_risk/risk_engine.py` (added flag + gate), `config/risk_settings.prod.json` (flag added, default True), memory `project_risk_advisory_largest_contribution.md`.

- **2026-04-24 | Learned Affinity — Walk-Forward Upgrades Trust from Suspect to Conditionally Trustworthy |** After classifying `learned_edge_affinity` as "Suspect" because it reads `regime_tracker._data` (same data source as the falsified per-edge-per-regime kill-switch), ran a dedicated walk-forward harness ([scripts/walk_forward_affinity.py](scripts/walk_forward_affinity.py)) across the 3 splits used for kill-switch validation.

  **Affinity walk-forward results:**

  | Split | Affinity ON | Affinity OFF | Δ | Kill-switch Δ (same split) |
  |---|---|---|---|---|
  | A (eval 2023-24) | 1.92 | 1.608 | **+0.312** | -0.50 |
  | B (eval 2024-25) | 1.025 | 0.95 | **+0.075** | +0.18 |
  | C (eval 2025) | 0.66 | 0.793 | **-0.133** | -0.21 |

  Central tendency: mean +0.085, median +0.075, 2 of 3 positive. In-sample -0.11 when disabled. Feature IS genuinely additive most of the time.

  **Key architectural takeaway — same data source, different policy, different OOS behavior:**

  Kill-switch and affinity both read `regime_tracker._data`. The ONLY difference: kill-switch is binary (`weight = 0.0 if sr ≤ 0`), affinity is a clipped soft multiplier (`norm *= clip(affinity, 0.3, 1.5)`). Affinity beats kill-switch on 2 of 3 splits by an average of +0.33 Sharpe. This falsifies my earlier assumption that "data source reliability → feature reliability." A noisy signal can generalize just fine when the policy that consumes it is soft-clipping; the same noisy signal is catastrophic when the policy is hard-binary.

  **Revised heuristic** (supersedes earlier "audit by data source first"):
  - Runtime-current-state features: high-confidence in-sample, trustworthy.
  - Anchor-fit features with soft-clipping policies (bounded multiplier, e.g., 0.3-1.5x): still need walk-forward, but often additive. "Conditionally trustworthy."
  - Anchor-fit features with hard-binary policies (kill = 0.0 / keep = 1.0): usually fail walk-forward because overfit noise gets amplified to 0/1 decisions. Default-skeptical.

  **Trust scorecard updated:**

  | Feature | In-sample Δ | OOS | Trust |
  |---|---|---|---|
  | Per-edge-per-regime kill (hard binary) | ~0 | -0.18 mean | Failed |
  | `learned_edge_affinity` (soft 0.3-1.5x) | -0.11 | +0.085 mean | **Conditionally trustworthy** |
  | `vol_target` (runtime leverage) | -0.12 | (runtime — in-sample trustworthy) | Trustworthy |
  | `exposure_cap` (runtime clamp) | -0.16 | (runtime — in-sample trustworthy) | Trustworthy |
  | `risk_advisory` bundle (runtime) | -0.24 | (runtime — in-sample trustworthy) | Trustworthy |

  **Rule:** Policy design matters as much as data source. Before dismissing a feature because its signal is noisy, check whether the policy that consumes the signal clips damage (soft bounded) or amplifies it (hard binary). The same `regime_tracker._data` produced one feature (kill-switch) that fails walk-forward and another (affinity) that passes 2/3 splits.

  **Files:** `scripts/walk_forward_affinity.py` (new), memory `project_learned_affinity_in_sample_load_bearing.md` (rewritten with OOS results).

- **2026-04-24 | Risk-Engine Advisory — Walk-Forward Exceeds In-Sample (+0.345 OOS mean vs +0.24 in-sample) |** Built [scripts/walk_forward_risk_advisory.py](scripts/walk_forward_risk_advisory.py) parallel to the regime and affinity harnesses, ran across the same 3 splits:

  | Split | ON | OFF | Δ |
  |---|---|---|---|
  | A (eval 2023-24) | 1.92 | 1.024 | **+0.896** |
  | B (eval 2024-25) | 1.025 | 0.875 | +0.150 |
  | C (eval 2025) | 0.66 | 0.671 | -0.011 |

  Mean +0.345, median +0.150, **3 of 3 non-negative**. OOS central tendency EXCEEDS in-sample (+0.24). Feature is more robust than it looked in-sample — not an overfitting artifact.

  **Window dependence is real but bounded.** Split A's +0.90 delta is 3.7x in-sample. Split C's -0.011 is essentially flat. The spread reflects that the advisory bundle's amplification component (risk_scalar 1.2x benign) is especially valuable during sustained trends (2023-2024 bull), while in choppy markets the amplification and the clamping roughly balance (2025). **But crucially, never materially negative across 3 splits.**

  **Confirmation of the revised heuristic from the affinity audit:**

  Pattern consistent across 3 features walk-forwarded so far:

  | Feature | Source | Policy | In-sample Δ | OOS mean Δ | OOS sign |
  |---|---|---|---|---|---|
  | Per-edge-per-regime kill | Anchor | Hard binary | ~0 | -0.18 | 2/3 negative |
  | `learned_edge_affinity` | Anchor | Soft clip 0.3-1.5x | -0.11 | +0.085 | 2/3 positive |
  | `risk_advisory` (bundle) | Runtime | Soft multi-dim | -0.24 | **+0.345** | 3/3 non-negative |

  Runtime-source + soft-policy → most robust. Anchor-source + soft-policy → mixed but net-positive. Anchor-source + hard-policy → usually negative. Soft-policy matters, runtime-source matters — both contribute to robustness independently.

  **Rule reinforced:** For in-sample Sharpe deltas of similar magnitude, OOS outcomes vary wildly based on (source, policy) combination. In-sample A/B alone cannot rank features; walk-forward is required. Three-split walk-forward is the minimum useful evidence.

  **Files:** `scripts/walk_forward_risk_advisory.py` (new), memory `project_risk_advisory_largest_contribution.md` (updated with OOS results).

- **2026-04-24 | Autonomous Lifecycle Is Unimplemented — The Core Reason System Underperforms SPY |** After a ~2-week feature-by-feature audit that proved the advisory stack is fine, shifted focus upstream to why the system still loses to SPY buy-and-hold (in-sample CAGR 7.20% vs SPY 13.94%, OOS Sharpe 0.66-1.92 vs SPY 1.00-1.87 depending on window). The answer was an architectural gap, not a parameter one:

  **Finding 1: Discovery validation is broken.** [evolution_controller.py:101](engines/engine_f_governance/evolution_controller.py#L101) subprocess-calls `scripts/walk_forward_validation.py`. `ls` confirms the script does not exist. Every call fails silently (stderr captured, continues), then reads a stale summary, returns `(False, 0.0, None)`. Every candidate goes straight to `status: failed`. Result in [edges.yml](data/governor/edges.yml): 132 failed / 20 error / 1 candidate / 13 active (all 13 hand-entered from project genesis).

  **Finding 2: No deprecation code exists in Engine F.** `grep -rn "retire\|deprecate\|paused" engines/engine_f_governance/*.py` returns one unrelated comment. Charter describes candidate → active → paused → retired lifecycle. Implementation: only candidate → active | failed. An `active` edge losing money has NO code path that can touch its status. `atr_breakout_v1` has 8234 trades, global Sharpe -0.04, lost -$5,365 in baseline run — and cannot be retired.

  **Finding 3: The 13 base active edges were never validated.** They're hand-typed YAML entries, immortal, unconditionally trusted. The 4-gate validation pipeline (designed for new Discovery candidates) was never applied to them. The current trading roster is a curated hand-list, not an evidence-based selection.

  **Finding 4: Validation thresholds don't beat the trivial benchmark.** Gate 1 = `Sharpe > 0`. SPY's rolling Sharpe has been 0.88-1.87 on test windows. Any edge that passes at Sharpe 0.5 during a bull market is destroying value vs buy-and-hold — but gets crowned active.

  **Why this is the core issue:** The vision per `GOAL.md` / `PROJECT_CONTEXT.md` is "self-evolving portfolio manager that autonomously discovers or prioritizes edges." The two engines charged with that (D Discovery and F Governance) don't actually perform their charter duties. D can't promote anything (Finding 1). F can't retire anything (Finding 2). The existing roster is human-curated (Finding 3). Validation crowns beta-correlated losers (Finding 4).

  **The fix isn't one method — it's 6 phases.** Plan at [docs/Core/Ideas_Pipeline/autonomous_lifecycle_plan.md](docs/Core/Ideas_Pipeline/autonomous_lifecycle_plan.md):
  - **Phase β (1-2 days)**: benchmark-relative gates (SPY Sharpe - 0.2) replace absolute thresholds
  - **Phase γ (2-3 days)**: fix subprocess to missing script — replace with direct `wfo.py` call
  - **Phase α (2-3 days)**: new `lifecycle_manager.py` — gates, audit trail, auto-retirement
  - **Phase ε (1 day)**: demote hand-entered base edges to `candidate`, re-validate all 13
  - **Phase δ (1 week)**: GA fitness = OOS Sharpe + robustness + degradation (not just in-sample Sharpe)
  - **Phase ζ (later)**: new alpha templates (PEAD, factor tilts, cross-sectional momentum)

  **Acceptance**: after α+ε, `atr_breakout_v1` auto-retires on evidence; remaining edges' Sharpe >1.2 in-sample; OOS beats SPY on ≥2/3 walk-forward splits.

  **Architectural takeaway / Rule:** When a system underperforms a trivial benchmark despite being architecturally complex, the failure is almost certainly in the **feedback layer**, not the signal layer. A hand-tuned rules engine wearing an "autonomous" label will underperform — not because the rules are wrong, but because without autonomous retirement the bad rules never leave, and without autonomous promotion the good rules never get trusted. **Before adding more edges or more sophisticated regime detection, verify that the lifecycle machinery for existing edges actually works.**

  **Files:** new memory `project_autonomous_lifecycle_broken_2026_04_24.md`, new plan `docs/Core/Ideas_Pipeline/autonomous_lifecycle_plan.md`. Next work starts with Phase β + γ.

- **2026-04-25 | Registry Status-Stomp Bug — Lifecycle Decisions Were Silently Reverted on Every Import |** During the universe-expansion lifecycle stress test (Sharpe collapsed 0.979 → 0.332 on 109 tickers), the lifecycle correctly identified that both `atr_breakout_v1` and `momentum_edge_v1` should be paused, wrote both transitions to `data/governor/lifecycle_history.csv`, and updated `data/governor/edges.yml`. A subsequent 1-run deterministic to measure post-pause performance produced canon md5 **bitwise-identical to the pre-pause smoke test** — Sharpe 0.332 unchanged, no behavior shift. That should have been impossible (soft-pause multiplies edge weight by 0.25x → different signals → different canon).

  **Root cause:** `engines/engine_a_alpha/edges/momentum_edge.py` lines 61-67 call `EdgeRegistry().ensure(EdgeSpec(..., status="active"))` on every module import. The pre-fix `EdgeRegistry.ensure()` had:

  ```python
  if spec.status:
      s.status = spec.status   # forced override — bug
  ```

  Comment said "keep status as-is unless provided," but `EdgeSpec.status` defaults to `"active"` so callers always provide it. Effect: every backtest startup imported `momentum_edge.py` → ensure() reverted `momentum_edge_v1` from `paused` back to `active` → lifecycle's decision lost.

  **Why this hid for so long:**
  1. `lifecycle_history.csv` recorded pauses cleanly — audit trail looked working
  2. `atr_breakout_v1` escaped because `atr_breakout.py` has no auto-register block, so its pauses persisted. Yesterday's "first autonomous pause" finding for atr_breakout was real and confirmed.
  3. The bug only fires for newer edges with the auto-register-on-import pattern. Only 2 files in the repo have it: `momentum_edge.py` and `momentum_factor_edge.py`.
  4. `momentum_factor_edge.py` had `weight: 0.0` in alpha_settings (separate kill-switch after walk-forward failed it), so even with `status` being stomped, the edge wasn't trading. Bug invisible there too.

  Net effect: every prior lifecycle test that paused atr_breakout was real; every test that would have paused momentum_edge was silently reverted. Including today's stress test before the fix.

  **Fix:** `EdgeRegistry.ensure()` now write-protects `status` for existing specs. New specs (not yet in registry) honor the import-time `status="active"` so newly-added edges register correctly. Existing specs only have non-status fields merged. Only the lifecycle layer (and explicit `set_status()` API) can transition status now, per the explicit `edges.yml` Write Contract documented in `docs/Core/PROJECT_CONTEXT.md` ("F writes: status field changes — neither engine deletes the other's fields").

  **Methodology rules (this is the important part):**

  1. **Bitwise-identical canon md5 when you expected a change is diagnostic evidence.** I expected post-pause Sharpe to differ from pre-pause. The canon md5 was identical. That should have triggered investigation immediately rather than acceptance. The deterministic harness's md5 is a precise instrument — "no change where I expected change" is just as informative as "change where I expected none." **Rule: when a code change should affect trade behavior and canon md5 doesn't shift, treat that as a P0 anomaly, not a non-event.**

  2. **Audit trails record decisions, not effects.** `lifecycle_history.csv` showed pauses firing. That gave a false sense of working autonomy. To prove autonomy is actually working, the audit trail must be cross-checked against the resulting `edges.yml` state AND against trade behavior in the next run. **Rule: document & audit the decision; verify the EFFECT separately.**

  3. **Documented contracts need executable enforcement.** The "F writes status; A doesn't touch status field" contract was documented in `PROJECT_CONTEXT.md` from project start. The actual code (`EdgeRegistry.ensure()`) violated it from day one. No test asserted the contract. Nobody noticed. **Rule: a write-contract that isn't enforced by code (asserts, write-protected APIs, or tests) decays into folklore. Either enforce it or remove it from the doc.**

  4. **Repeated identical lifecycle events for the same edge are a smell.** If `lifecycle_history.csv` shows `momentum_edge_v1: active → paused` on multiple consecutive runs, that's impossible under correct behavior (the second run should see the edge already paused, no transition). The audit trail had this signature; nothing was watching for it. **Future low-priority refinement: lifecycle startup sanity check that flags `<id>: <prev> → <new>` events where `prev` doesn't match the registry's actual current value.**

  **Files:** `engines/engine_a_alpha/edge_registry.py` (fix in `ensure()`), memory `project_registry_status_stomp_bug_2026_04_25.md`. The 2 auto-register sites (`momentum_edge.py:61`, `momentum_factor_edge.py:113`) are now harmless — they register-if-new, no-op for existing.


---

## 2026-05-06 — Trade-log "regenerable" claim is true in spirit, false in practice

**Context:** Disk filled to 100% during active development; needed to clean up `data/trade_logs/` before a 70-min multi-year measurement could run.

**The trap:** CLAUDE.md describes trade_logs as "regenerable output, not source." A naïve reading is "delete freely." A sample test run with `find -mtime +2 | xargs rm -rf` would have deleted **22 dirs that scripts and audit docs explicitly reference by hardcoded UUID** — silently breaking `per_edge_per_year_attribution.py`, `analyze_oos_2025.py`, the multi-year foundation measurement audit, and several Path C audit docs.

**The actual rule:** trade_logs are regenerable IN SPIRIT (you can re-run a backtest and get fresh logs) but NOT regenerable AS HISTORICAL ARTIFACTS (the run that produced specific trades.csv on April 24 used April-era code; today's code can't recreate it). And several scripts/docs **hardcode specific run UUIDs** as their input or cited reference data — those refs go dead silently if the UUID dir is deleted.

**The procedure (now codified in `docs/Core/SESSION_PROCEDURES.md` § "Trade-log cleanup"):**
1. Grep for every UUID-format string across `scripts/ engines/ orchestration/ core/ docs/`
2. Subtract that referenced set from the on-disk set
3. Delete only the unreferenced
4. Verify all referenced UUIDs still on disk after cleanup

**Today's cleanup result:** 364 total → 76 referenced (kept) + 288 unreferenced (deleted) = 3 GB freed.

**Why the user's instinct mattered:** when I proposed mass-deleting old runs, the user asked "would the system lose context for what worked vs didn't work?" The answer turned out to be partially yes — not because the system "learns from old trade_logs" (it doesn't, governor state mutates separately), but because **scripts and docs treat specific runs as data sources by UUID**. That category-4 dependency is invisible to size/age heuristics; only a reference scan finds it.

**Files:** `docs/Core/SESSION_PROCEDURES.md` § "Trade-log cleanup procedure" has the full grep + diff + delete workflow.

---

## 2026-05-06 — Don't measure observability-only layers by flipping flags

**Context:** Wanted to test whether WS-C cross-asset confirmation adds Sharpe over the 1.296 multi-year baseline. Patched `regime_settings.json` to enable `cross_asset_confirm_enabled`, kicked off the 70-min multi-year measurement.

**The trap:** After 5 minutes (year 2021 rep 1 complete), canon md5 was bitwise identical to baseline. The flag was on, but no trade decisions changed.

**Why:** The WS-C agent's brief explicitly stated "default OFF on main: cross-asset confirmation function exists but isn't wired into the live decision path until director approves." The function computes its output and writes it to `advisory["cross_asset_confirm"]`, but **Engine B does not read that field for risk decisions**. Flipping the flag changes a side-channel value that nothing consumes.

**The lesson:** When a workstream ships with "observability-only" or "default OFF, not wired into the decision path" semantics, the **flag does not toggle alpha contribution** — it toggles whether a side-channel field gets populated. To actually measure the layer's Sharpe impact, you need to first integrate it into the live decision path (a separate, propose-first design decision). Running the harness with just the flag flipped is a structural no-op.

**Procedure update:** Before kicking off a measurement run to test a flag, read 2-3 lines of integration code to confirm the flag actually drives a decision-path branch. Specifically grep for whether the relevant `advisory["X"]` field is consumed by `engine_b_risk/` or by the policy code that scales / vetoes trades. If no consumer, flipping the flag is observation-only.

**Cost saved by catching it early:** ~65 minutes of wasted backtest compute. 1 rep was enough evidence (canon md5 match = no behavior change at all).

**What this didn't change:** WS-C (3 cross-asset features + confirmation function + tests) is still valid groundwork for the regime-conditional wash-sale gate when tax-drag work unfreezes. Don't revert. The alpha contribution is just structurally unmeasurable until someone scopes the Engine-B integration as separate work.

## 2026-05-09 — The substrate was the alpha (universe COLLAPSES verdict)

**Context:** F6 from the 2026-05-06 audit identified that every Sharpe quoted to date — including the 1.296 Foundation Gate baseline that suspended the kill thesis — was conditional on a static 115-name S&P 500 mega-cap config (`config/universe.json`). The UniverseLoader (`engines/data_manager/universe.py:226-240`) had been built 2026-04-24 but never wired. B1 wired it and re-ran multi-year on the 476-503 historical S&P 500 union.

**Verdict: COLLAPSES.** Mean Sharpe 1.296 → 0.507 (−61%). 4 of 5 years collapse 3-11× outside the noise band. Only 2023 holds within ±0.15.

**What's specifically falsified:**
- The 1.296 Foundation Gate "kill thesis SUSPENDED" framing
- The 1.666 / 1.890 / 0.954 per-year baselines that V/Q/A and HRP slice work measured against
- The "Path 1 ship" deployment narrative
- ~30 days of measurement campaign comparisons that all used the static-109 substrate
- The interpretation that V/Q/A's sustained-scores fix "closes the drag" — the FIX is software-correct, but the magnitudes are unknown on substrate-honest universe

**What's NOT falsified:**
- Infrastructure investments: Foundry, determinism harness, decision diary, gauntlet, lifecycle automation, edge graveyard, code-health, doc lifecycle. All catch-the-system-lying machinery worked correctly today.
- The discipline framework. Today is its highest-value moment. No live capital was risked on the biased measurement.
- Edge code itself (it computes correctly; the issue is what it computed against)
- The 2023 hold (-0.095 within noise) — this is itself a falsifiable hypothesis worth running down

**The 2023 anomaly's smoking gun:** The static-109 config carries 6 non-S&P 500 ultra-volatility names — **COIN, MARA, RIOT, DKNG, PLTR, SNOW**. The historical S&P 500 universe excludes them by definition. Trading-system + momentum/volatility edges happily concentrated capital into these names during their explosive periods (2021 crypto IPOs, 2024 PLTR/COIN rallies). 2023 was the one year these 6 names were dormant — both substrates captured 2023's NVDA + Mag-7 rally equivalently, hence the small Δ.

**The deeper lesson — substrate selection is part of strategy, not a precondition:**

For ~6 weeks the team treated the static-109 config as a fixed, neutral input — "this is the universe; the strategy is what we build on top." The substrate-honest finding shows that **picking the universe IS strategy**: a 6-name asymmetric-upside lottery dressed up as 109 mega-caps was a different system than what the documentation described. When you measure performance on the same substrate that defines the system's opportunity set, you measure how well the strategy exploits its own assumptions, not whether those assumptions are honest.

**Procedural update going forward:**

1. **No headline measurement on a hand-curated universe.** Default substrate is `use_historical_universe=true`. The static config is for diagnostic comparisons only (e.g., "what's the alpha-attribution to the 6 names").
2. **Per-year volatility checks before reporting a multi-year mean.** The 2024 1.890 and 2024 0.268 are 1.6 Sharpe apart on the same edges with different substrates. If per-year sigma is comparable to the mean, the mean is uninformative. Standard going forward: report per-year + sigma alongside any multi-year mean.
3. **Universe additions by default-false flags.** When the static substrate is being used (research / diagnostics), the user should have to explicitly add non-S&P names (like the 6 in the current config). Anything not in the historical S&P 500 universe should be a deliberate choice with a rationale, not a config-list inclusion.
4. **Honest about kill-thesis state.** Foundation Gate at 0.507 is nominally a pass (≥0.5) but the per-year volatility is high enough that the threshold is meaningless on this substrate. Honest restatement of kill criteria on the substrate-honest universe is owed before the next commitment cycle.

**Cost / outcome:** ~30 days of measurement narrative now needs reframing. No live capital lost (the discipline framework caught the bias before deployment, which is what the framework is FOR). Approximately 6-8 hours of audit work queued (C-collapses-1) to determine what survives. The infrastructure investment was the right bet — without it, you'd be paper-trading a strategy that loses on representative universes.

**What this enables:** The substrate-honest substrate is now the default research substrate. Future edge construction can be honest from day 1. The framework that produced this finding is the framework that protects future findings from the same trap.
