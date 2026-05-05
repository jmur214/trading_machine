# System Core Functional Blueprint

> **This document describes how each engine works TODAY in the actual code.** For the target design (what each engine *should* do after refactoring), see `engine_charters.md`. The gap between these two files represents the refactoring work remaining.

*This document rigorously maps the exact high-level business rules and functional logic of each core engine, completely separated from their low-level code implementation.*

## Engine A: Alpha Generation (The Researcher)
**Location:** `engines/engine_a_alpha/`
**Primary Responsibility:** Convert raw mathematical predictions from various "edges" into standardized, risk-aware, portfolio-ready signals (Long/Short/None with a Conviction Strength).

**Core High-Level Business Rules:**
1. **Signal Collection:** Queries all active sub-strategies (edges like Mean Reversion, Momentum, News Sentiment) to gather raw prediction scores for each ticker. Ensures input market data is strictly formatted (OHLCV).
2. **Cognitive Gating (Macro-Regime):** Receives regime state from ModeController (Engine E) via the `regime_meta` parameter. Falls back to internal detection if not provided.
    - *Defense Mechanism:* If the global market is in a "Bear" regime, it aggressively cuts the strength of all LONG signals. If the market is in "High Volatility", it shrinks the strength of *all* signals globally to force smaller positioning.
3. **Hygiene & Micro-Regime Filtering:** Evaluates the specific ticker being traded.
    - If the ticker lacks sufficient historical data, signals are dropped.
    - If the ticker itself is exhibiting unfavorable trend or extreme localized volatility, the raw edge scores are penalized ("shrunk").
4. **Ensemble Aggregation & Normalization:**
    - Converts wild, boundless raw scores from different edges into a standardized `[-1.0, +1.0]` scale.
    - Aggregates the edges using weighted averages, applying "shrinkage" (ridge-style penalty) to prevent the engine from becoming overly confident.
5. **Machine Learning & Governance Overrides:**
    - Uses a trained ML Predictor (SignalGate in `engine_a_alpha/learning/`) as a final gate. If the ML model severely disagrees with a LONG signal, it cuts the strength. If it strongly agrees, it boosts the strength.
    - Applies dynamic edge-weights from Engine F (Governance) via `edge_weights.json`.
    - Applies **learned edge affinity** multipliers from Governor's `RegimePerformanceTracker`: per-edge-category weights (0.3-1.5x) based on how that category has historically performed in the current regime.
6. **Threshold Formatting:** Converts the final continuous aggregate score into a discrete structural request `{'side': 'long'|'short'|'none', 'strength': [0, 1]}`. It enforces a "flip cooldown" to prevent whipsawing (rapidly changing from long to short on back-to-back days).

## Engine B: Risk Management (The Risk Manager)
**Location:** `engines/engine_b_risk/`
**Primary Responsibility:** Size positions dynamically, enforce portfolio-wide risk constraints, manage liquidity caps, and attach strict risk parameters (Stop Loss/Take Profit) to signals emitted by Engine A.

**Core High-Level Business Rules:**
1. **Dynamic Position Sizing:**
    - Sizes trades based on a fixed risk budget per trade (e.g., risk 2.5% of equity) adjusted by Average True Range (ATR).
    - Dynamically scales position sizing up or down based on Market Regime (from Engine E) and AI Confidence.
    - Applies Engine E advisory `risk_scalar` to ATR sizing budget — automatically reduces position sizes in stressed/crisis regimes.
2. **Portfolio Constraints & Safety Limits:**
    - Actively rejects Alpha signals if accepting them would breach global risk parameters:
        - *Max Gross Exposure:* Prevents the portfolio from exceeding a set limit (e.g., 100% capacity). Dynamically tightened by Engine E's `suggested_exposure_cap`.
        - *Max Positions:* Dynamically tightened by Engine E's `suggested_max_positions` advisory.
        - *Sector Concentration Limits:* Rejects trades if a single sector exceeds its maximum allocation. Dynamically adjusted by correlation regime: dispersed → relaxed to 40%, elevated/spike → tightened to 20%.
        - *Directional Limits:* Rejects short signals if a strict "Long Only" policy is active.
3. **Liquidity Defense (Professional Checks):**
    - Audits the proposed trade size against the stock's Average Daily Volume (ADV). Clips the order size if it exceeds a safe percentage of daily volume to prevent severe market-impact slippage.
4. **Lifecycle & Trailing Stops Management:**
    - Continuously monitors open positions. Once a trade reaches a specific profit threshold, it activates a Trailing Stop, stepping the stop-loss level upward (or downward for shorts) mathematically to lock in profits while letting winners run.

## Engine C: Portfolio Management (The Accountant + PM)
**Location:** `engines/engine_c_portfolio/`
**Primary Responsibility:** Act as the ultimate, tamper-proof source of truth for the system's accounting state (Cash, Positions, Realized/Unrealized PnL) and intelligently determine the optimum capital allocation matrix across all assets.

**Core High-Level Business Rules:**
1. **Irrefutable State Accounting:**
    - Processes incoming trade "fills" to update the ledger.
    - Strictly enforces the fundamental accounting identity: `Total Equity = Cash + Unrealized PnL`.
    - Handles complex partial-fills, position reversals (closing a long and immediately opening a short), and commission extraction.
2. **Dynamic Capital Allocation (Portfolio Policy):**
    - Determines the theoretical target percentage of equity a stock *should* command using one of two intelligent models:
        - *Mean-Variance Optimization (MVO):* Uses the AI edge signals as Expected Returns (Mu) and historical asset covariance (Sigma) to build mathematically optimal allocation weights, heavily penalizing assets that are too correlated with each other.
        - *Inverse-Volatility (Adaptive):* A heuristic model that sizes inversely to volatility (Signal Strength / Annualized Volatility). Erratic, highly volatile assets get less capital; stable, trending assets get more.
    - **Portfolio-Level Vol Targeting:** After computing raw weights, estimates portfolio volatility via `w @ cov @ w` and scales all weights so the portfolio matches `target_volatility` (default 15%). Scalar clamped to 0.3-2.0x.
    - **Advisory Exposure Cap:** Enforces Engine E's `suggested_exposure_cap` by proportionally scaling all weights when gross exposure exceeds the advisory limit.
    - **Regime-Specific Config Overrides:** Loads per-regime allocation recommendations from `AllocationEvaluator` and temporarily overrides policy config (mode, max_weight, target_vol, rebalance_threshold) for the current regime.
3. **Drift & Rebalance Governance:**
    - Continuously measures the "drift" between the current actual portfolio weights and the optimal target weights. Only triggers a rebalance request if the deviation crosses a meaningful threshold (e.g., >2%), preventing excessive commission churn from hyperactive adjustments.
4. **Autonomous Allocation Discovery:**
    - `AllocationEvaluator` tests 384 parameter combinations across 5 dimensions (mode, max_weight, target_vol, rebalance_threshold, risk_per_trade_pct).
    - Scores each combo by composite metric: `0.4 * Sharpe + 0.3 * Calmar - 0.2 * |MDD| - 0.1 * turnover`.
    - Finds optimal configs globally and per regime. Recommendations persisted to `data/research/allocation_recommendations.json`.
    - Integrated into Governor's `update_from_trade_log()` feedback loop. `auto_apply_allocation` defaults to false for human review.

## Engine D: Discovery & Evolution (The Edge Hunter)
**Location:** `engines/engine_d_discovery/`
**Primary Responsibility:** Hunt for new trading edges through ML scanning and genetic evolution, validate candidates through a multi-gate pipeline, and output validated candidates for Governance (Engine F) to evaluate and activate.

**Core High-Level Business Rules:**
1. **Two-Stage ML Pattern Detection (The Hunter):**
    - **Stage 1 — Feature Screening:** Fits a LightGBM classifier (fallback: sklearn GradientBoosting) on 40+ engineered features to rank by importance. Uses time-series cross-validation (`TimeSeriesSplit` with purge gap) for honest accuracy.
    - **Stage 2 — Rule Extraction:** Fits a shallow `DecisionTreeClassifier(max_depth=4)` on top-K screened features. Recursively traverses tree paths to extract human/machine-readable rules with probability thresholds.
    - Vol-adjusted target labeling: thresholds scaled by rolling ATR% so a 5% move in TSLA is treated differently from 5% in KO.
2. **Genetic Algorithm Evolution:**
    - Maintains a persistent population of `CompositeEdge` genomes in `data/governor/ga_population.yml`.
    - **Selection:** Tournament selection (k=3) based on fitness (Sharpe from validation).
    - **Crossover:** Single-point gene swapping between parents. Cap offspring at 1-4 genes.
    - **Mutation:** Gaussian threshold perturbation (sigma=10%), window +/-5, operator flip (5%), gene addition/deletion (10%), direction mutation (5%).
    - **Elitism:** Top 3 genomes preserved unchanged across generations.
    - Seeds from existing composite edges on first run; evolves from persisted population on subsequent runs.
3. **Expanded Feature Engineering (40+ features across 7 categories):**
    - Technical (18): RSI, MACD, Bollinger, ATR, SMA distances, momentum, volume z-score, etc.
    - Fundamental: PE, PS, PB, PFCF, Debt/Equity ratios (from DataManager).
    - Calendar/Seasonality: Day-of-week (cyclical sin/cos), month, quarter-end proximity, options expiration proximity.
    - Microstructure: Overnight gap, intraday range, close location in bar, gap fill indicator.
    - Inter-Market: SPY/TLT/GLD rolling returns, SPY-TLT correlation (gracefully degrades when assets unavailable).
    - Regime Context: Bull/bear/range flags, vol-high/low flags, correlation spike, stability, transition risk, risk scalar.
    - Cross-Sectional: Percentile ranks of momentum, volatility, relative strength, ATR across universe per date.
4. **4-Gate Validation Pipeline:**
    - **Gate 1 — Quick Backtest:** Sharpe > 0 (cheap filter to reject obvious losers).
    - **Gate 2 — PBO Robustness:** 50 synthetic paths, survival rate > 0.7.
    - **Gate 3 — WFO Degradation:** OOS Sharpe must be >= 60% of IS Sharpe.
    - **Gate 4 — Statistical Significance:** Monte Carlo permutation test p-value < 0.05. Also computes Minimum Track Record Length (Bailey & Lopez de Prado).
    - Candidates must pass ALL gates to be promoted to `active`.
5. **Template Mutation:**
    - Generates candidate parameter variants from 9 edge templates (RSI Bounce, ValueTrap, FundamentalRatio, Seasonality, Gap, VolumeAnomaly, Panic, Herding, EarningsVol).
    - Random hyperparameter sampling from each template's defined parameter space.
6. **Candidate Output & Logging:**
    - Writes validated candidates to `edges.yml` with status `candidate` — promotes to `active` only if all gates pass.
    - Stores `validation_sharpe` in candidate params for GA fitness tracking.
    - Logs all discovery activity to `data/research/discovery_log.jsonl` via `DiscoveryLogger` (hunt results, GA generations, validation outcomes, cycle summaries).
    - D is an **offline engine** — it operates on historical data and does not participate in the live trading loop.

## Engine E: Regime Intelligence (The Macro Thinker)
**Location:** `engines/engine_e_regime/`
**Primary Responsibility:** Detect and classify the current market environment (trend direction, volatility level) and provide a structured regime state object with non-binding advisory hints for downstream engines.

**Core High-Level Business Rules:**
1. **Market Regime Detection:**
    - Analyzes broad market benchmark data (SPY) to classify the current trend regime (bull/bear/neutral) and volatility regime (high/normal/low).
    - Uses moving averages and ATR-based volatility measures for classification.
    - Enforces hysteresis to prevent single-bar regime flips.
2. **Advisory Policy Hints:**
    - Publishes non-binding suggestions alongside descriptive regime data (e.g., suggested exposure caps, edge affinity scores).
    - Advisory hints are explicitly non-binding — each downstream engine retains full authority over its own decisions.
3. **Regime as a Service:**
    - ModeController calls `RegimeDetector.detect_regime()` once per bar and passes the regime state to A, B, and F.
    - Runtime engines do not import RegimeDetector directly — E is consumed as a service through ModeController, reducing coupling.
    - D (Discovery) may import RegimeDetector directly for offline research use.

## Engine F: Governance (The Performance Reviewer)
**Location:** `engines/engine_f_governance/`
**Primary Responsibility:** Act as the self-referential performance monitor and lifecycle manager of the machine. It tracks edge performance, autonomously reweighs edges, and manages the full edge lifecycle (candidate → active → paused → retired).

**Core High-Level Business Rules:**
1. **Edge Profitability Analytics:**
    - Groups every historical trade by its originating strategy/edge (e.g., "RSI Mean Reversion", "Momentum").
    - Computes performance metrics for each edge in isolation: Win Rate, Sharpe Ratio, Sortino Ratio, Max Drawdown, Total Realized PnL, and Expectancy.
    - Uses `MetricsEngine` from `core/` for standardized metric computation.
2. **Autonomous Edge Weighting (Promote & Demote):**
    - Uses EMA-smoothed performance metrics to generate a global multiplier for every edge.
    - *Promotion:* If an edge exhibits high Sharpe and low drawdown, its multiplier is increased, granting it more capital and trust.
    - *Kill-Switch:* If an edge's max drawdown exceeds -25%, it is immediately paused to stop the bleeding.
    - Weight updates are capped (±15% per cycle) and require minimum evidence (≥50 trades, ≥30 days) to prevent overreaction.
3. **Regime-Conditional Edge Weighting:**
    - `RegimePerformanceTracker` records per-edge, per-regime trade statistics using Welford's online algorithm (running mean/variance without storing raw trades).
    - `get_edge_weights(regime_meta)` returns blended weights: `alpha * regime_weight + (1-alpha) * global_weight` where `alpha = 0.7` (configurable). Falls back to global weights when regime data is sparse (< `min_trades_per_regime`).
    - Trade fills are tagged with `regime_label` from the macro regime at execution time, enabling organic accumulation of regime-specific performance data.
    - **Learned edge affinity:** `get_learned_affinity(regime_label)` computes per-edge-category average weights for a regime, replacing the static `MACRO_EDGE_AFFINITY` table. Injected into `regime_meta["advisory"]["learned_edge_affinity"]` and consumed by SignalProcessor as 0.3-1.5x multipliers.
    - Persisted to `data/governor/regime_edge_performance.json`.
4. **Regime-Aware Attribution:**
    - Uses `RegimePerfAnalytics` and `RegimePerformanceTracker` to break down edge performance by market regime (consuming E's regime history).
    - Distinguishes "edge is fundamentally broken" from "edge is out of phase with current regime" — an edge that only fails in bear markets is not necessarily bad, just regime-conditional.
5. **Autonomous Allocation Evaluation:**
    - Runs `AllocationEvaluator` during `update_from_trade_log()` to test allocation parameter combinations and save per-regime recommendations.
    - `auto_apply_allocation` (default: false) controls whether recommendations are automatically applied to portfolio policy config.
4. **Edge Lifecycle Management:**
    - Manages the full lifecycle: candidate → active → paused → retired.
    - Reviews validated candidates proposed by Discovery (Engine D) via `edges.yml` and decides whether to activate them.
    - Writes `status` field changes and weight assignments to `edges.yml`. Does not modify D's candidate specs or metadata.
5. **State Publishing:**
    - Synthesizes all system equity curves and edge weights into a master `system_state.json` payload for dashboards and monitoring.
    - Publishes `edge_weights.json` consumed by Engine A during signal generation.

## Data Manager (The Librarian)
**Location:** `engines/data_manager/`
**Primary Responsibility:** Act as the centralized data acquisition, caching, and normalization layer. It abstracts away the complexity of external APIs and provides clean, uniform dataframes to the rest of the system.

**Core High-Level Business Rules:**
1. **Data Normalization & Repair:**
    - Ingests raw historical price data (OHLCV) from various sources and aggressively sanitizes it.
    - Standardizes column names, forces strict timezone-naive timestamps, drops corrupt rows, and automatically attempts to scale bizarrely massive stock prices resulting from bad API data splits.
2. **Indicator Precomputation (ATR):**
    - Precomputes the Average True Range (ATR) directly into the price dataframe, ensuring all downstream engines calculate scale and risk using the exact same underlying volatility metric. Enforces a strict 14-bar warmup period so engines never trade on unstable data.
3. **Waterfall Fetching & Fallbacks:**
    - First attempts to fetch institutional-grade data via primary brokers (e.g., Alpaca).
    - If the primary API fails, hits a rate limit, or is offline, it seamlessly falls back to secondary open-source scrapers (yfinance), or generates deterministic Synthetic data on the fly (for `SYNTH-` tickers).
4. **Aggressive Smart Caching:**
    - Saves all successfully fetched data to local disk (preferring high-speed Parquet formats over CSV) to eliminate redundant API calls across backtests, drastically accelerating research cycles.
5. **Deep Fundamentals Assembly:**
    - Synthesizes scattered, quarterly corporate reporting data (Income statements, Balance sheets) into a continuous, daily-interpolated time-series.
    - Calculates and appends critical valuation and health ratios (P/E, Debt-to-Equity, Free Cash Flow Yield) directly onto the price dataframe for fundamental value edges to consume.
