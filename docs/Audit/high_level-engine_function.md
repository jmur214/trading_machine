# System Core Functional Blueprint

> **This document describes how each engine works TODAY in the actual code.** For the target design (what each engine *should* do after refactoring), see `engine_charters.md`. The gap between these two files represents the refactoring work remaining.

*This document rigorously maps the exact high-level business rules and functional logic of each core engine, completely separated from their low-level code implementation.*

## Engine A: Alpha Generation (The Brain)
**Primary Responsibility:** Convert raw mathematical predictions from various "edges" into standardized, risk-aware, portfolio-ready signals (Long/Short/None with a Conviction Strength).

**Core High-Level Business Rules:**
1. **Signal Collection:** Queries all active active sub-strategies (edges like Mean Reversion, Momentum, News Sentiment) to gather raw prediction scores for each ticker. Ensures input market data is strictly formatted (OHLCV).
2. **Cognitive Gating (Macro-Regime):** Analyzes the overall market benchmark (e.g., SPY) to determine the global regime. 
    - *Defense Mechanism:* If the global market is in a "Bear" regime, it aggressively cuts the strength of all LONG signals. If the market is in "High Volatility", it shrinks the strength of *all* signals globally to force smaller positioning.
3. **Hygiene & Micro-Regime Filtering:** Evaluates the specific ticker being traded.
    - If the ticker lacks sufficient historical data, signals are dropped.
    - If the ticker itself is exhibiting unfavorable trend or extreme localized volatility, the raw edge scores are penalized ("shrunk").
4. **Ensemble Aggregation & Normalization:** 
    - Converts wild, boundless raw scores from different edges into a standardized `[-1.0, +1.0]` scale.
    - Aggregates the edges using weighted averages, applying "shrinkage" (ridge-style penalty) to prevent the engine from becoming overly confident.
5. **Machine Learning & Governor Overrides:** 
    - Uses a trained ML Predictor (Random Forest) as a final gate. If the ML model severely disagrees with a LONG signal, it cuts the strength. If it strongly agrees, it boosts the strength.
    - Applies dynamic edge-weights optionally dictated by Engine D (The Governor).
6. **Threshold Formatting:** Converts the final continuous aggregate score into a discrete structural request `{'side': 'long'|'short'|'none', 'strength': [0, 1]}`. It enforces a "flip cooldown" to prevent whipsawing (rapidly changing from long to short on back-to-back days).

## Engine B: Risk Management (The Executor)
**Primary Responsibility:** Size positions dynamically, enforce portfolio-wide risk constraints, manage liquidity caps, and attach strict risk parameters (Stop Loss/Take Profit) to signals emitted by Engine A.

**Core High-Level Business Rules:**
1. **Dynamic Position Sizing:** 
    - Sizes trades based on a fixed risk budget per trade (e.g., risk 2.5% of equity) adjusted by Average True Range (ATR).
    - Dynamically scales position sizing up or down based on Market Regime (e.g., widening stops in high volatility) and AI Confidence (e.g., increasing size if Machine Learning confidence is exceptionally high).
2. **Portfolio Constraints & Safety Limits:**
    - Actively rejects Alpha signals if accepting them would breach global risk parameters:
        - *Max Gross Exposure:* Prevents the portfolio from exceeding a set limit (e.g., 100% capacity).
        - *Sector Concentration Limits:* Rejects trades if a single sector exceeds its maximum allocation (e.g., >30% in Technology).
        - *Directional Limits:* Rejects short signals if a strict "Long Only" policy is active.
3. **Liquidity Defense (Professional Checks):**
    - Audits the proposed trade size against the stock's Average Daily Volume (ADV). Clips the order size if it exceeds a safe percentage of daily volume to prevent severe market-impact slippage.
4. **Lifecycle & Trailing Stops Management:**
    - Continuously monitors open positions. Once a trade reaches a specific profit threshold, it activates a Trailing Stop, stepping the stop-loss level upward (or downward for shorts) mathematically to lock in profits while letting winners run.

## Engine C: Portfolio Management (The Accountant)
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
3. **Drift & Rebalance Governance:** 
    - Continuously measures the "drift" between the current actual portfolio weights and the optimal target weights. Only triggers a rebalance request if the deviation crosses a meaningful threshold (e.g., >2%), preventing excessive commission churn from hyperactive adjustments.

## Engine D: Research & Strategy Governor (The Hunter)
**Primary Responsibility:** Act as the self-referential performance monitor and continuous optimizer of the machine. It tracks the real-world performance of every edge and autonomously promotes or demotes them.

**Core High-Level Business Rules:**
1. **Continuous Observer Loop:** Runs asynchronously in the background, constantly watching the system's trade logs and portfolio snapshots for new entries.
2. **Edge Profitability Analytics:** 
    - Groups every historical trade by its originating strategy/edge (e.g., "RSI Mean Reversion", "News Sentiment", "Random Forest Proxy").
    - Computes ironclad performance metrics for each edge in isolation: Win Rate, Sharpe Ratio, Max Drawdown, and Total Realized PnL.
3. **Autonomous Edge Weighting (Promote & Demote):** 
    - Uses the gathered performance metrics to generate a "global multiplier" for every edge.
    - *Promotion:* If an edge exhibits a high Sharpe ratio and low drawdown, its multiplier is increased (e.g., 1.5x), granting it more capital and trust system-wide.
    - *Termination (Demotion):* If an edge's drawdown exceeds acceptable limits or its Win Rate collapses, the Governor slashes its multiplier toward 0.0—effectively executing a bloodless kill switch that stops the bleeding strategy without manual human intervention.
4. **State Publishing:** Synthesizes all system equity curves and edge weights into a single master `system_state.json` payload, which acts as the source data feed for external GUIs and the Cockpit dashboard.

## Data Manager (The Librarian)
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
