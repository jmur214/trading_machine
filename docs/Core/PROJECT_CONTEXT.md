# Trading Machine: Project Context & Philosophy

## What is the Trading Machine?
The Trading Machine is a professional-grade, autonomous algorithmic trading system. Its ultimate goal is to discover market edges, actively learn, compound returns, manage risk, and significantly outperform the market. It merges research, backtesting, and live execution into a single, cohesive, self-evolving pipeline.

The Trading Machine is a modular Python trading research and execution framework. It is intended to be a full-spectrum, self-updating trading lab that merges algorithmic precision with human-level transparency. 

It is designed to eventually function like a "Schwab Intelligent Portfolio" (SIP) crossed with an adaptive Quant Fund. It does not just hold passive ETFs; it actively generates "signals" across different sleeves of capital (Technical, Fundamental, True Edge) and dynamically rebalances its trust in those strategies based on how well they perform in current market regimes.

## The 4-Engine Architecture
The system is built on four core pillars:

1. **Engine A: Alpha Generation (The Brain)**
   - Responsible for identifying opportunities (Signals).
   - Utilizes pluggable "Edges" (strategies based on mean reversion, momentum, sentiment, or news).
   - Generates ranked candidate trades and emits signal dicts.

2. **Engine B: Risk & Order Placement (The Safety Net & Executor)**
   - Converts theoretical signals into actionable orders and executes them with the broker.
   - Enforces position sizing (e.g., ATR-based, volatility-adjusted, Kelly criterion).
   - Manages strict stop-loss, take-profit rules, and portfolio exposure limits.

3. **Engine C: Portfolio Management (The Accountant)**
   - *Planned:* Will manage portfolio "Sleeves", breaking the single custodial account into virtual sub-accounts (e.g., specialized equity, fixed-income, or core/satellite sleeves) that can be tracked and managed independently. This will enable specialized, concurrent management of different assets, specialized accounting, and independent rebalancing.
   - Keeps track of global account balance, equity, realized/unrealized P&L, and position states.
   - Does *not* generate signals or place orders; strictly manages the holistic portfolio picture.

4. **Engine D: Strategy Governor & Research (The Meta-Brain)**
   - **Governance:** Tracks the performance of every edge (Sharpe, Max Drawdown, Win Rate). Dynamically reweighs capital allocation and decides which edges should be active, inactive, or retired based on recent performance and market regimes. For instance, if the "Mean Reversion" edge stops working in a trending market, the Governor removes capital from it and routes it to an edge that *is* working.
   - **Discovery & Evolution:** Autonomously hunts for new edges via Decision Tree scanning and genetic programming (composite "genome" mutation). Validates candidates through walk-forward optimization and robustness testing (Probability of Backtest Overfitting).
   - **Research Infrastructure:** Provides centralized metrics computation (Sharpe, Sortino, Calmar, VaR, Kelly), feature engineering for ML models, and a time-decay scoring system for ranking edges across research runs.
   - **Regime Detection:** Houses the current `RegimeDetector` (trend + volatility classification via SMA/ATR on SPY). This functionality is planned to eventually graduate into its own Engine E.
   - Creates a continuous, autonomous learning loop where the system discovers, validates, adapts, and evolves.

## Supporting Infrastructure & Ecosystem
While the 4 Engines govern trading logic, the broader system heavily relies on:
- **Data Ingestion & Management:** Standardizes external market/alternative data into clean, highly optimized formats (e.g., Parquet).
- **The Backtester:** A rigorous, high-fidelity historical simulator that replays data to validate edge hypotheses, built with strict cross-validation guardrails to prevent overfitting.

## Orchestration Layer
The `ModeController` (`orchestration/mode_controller.py`) binds the engines together. It allows the exact same logic pipeline to run in:
- **Backtest Mode:** Slices data bar-by-bar locally.
- **Paper Mode:** Streams data via websockets and simulates execution.
- **Live Mode:** Plumbs the final Portfolio engine diffs straight to Broker REST APIs.

## Planned: Engine E — Regime Intelligence
> A 5th engine (Regime Intelligence) has been formally chartered but **not yet implemented**. It is designed to be the system's single official source of macro/environmental truth — classifying market regimes (trending, mean-reverting, high volatility, crisis) so other engines can condition their behavior. See `docs/Audit/engine_charters.md` for the full charter.

## Current State

| Component | Status | Notes |
|-----------|--------|-------|
| Engine A (Alpha) | ✅ Functional | Signal filtering may need to be loosened |
| Engine B (Risk) | ✅ Functional | ATR sizing, exposure caps, trailing stops |
| Engine C (Portfolio) | ✅ Functional | Ledger/Allocation wall not yet enforced |
| Engine D (Governor & Research) | ✅ Functional | Autonomous governance + edge discovery/evolution pipeline |
| Engine E (Regime) | 📋 Chartered | `RegimeDetector` exists in Engine D as a module; not yet a standalone engine |
| Data Manager | ✅ Functional | Alpaca + cache + normalization |
| Backtester | ✅ Functional | Walk-forward capable |
| Dashboard (V2) | ✅ Functional | V1 deprecated |
| Live Trading | ⚠️ Scaffolded | Broker interface exists, not fully tested |

## What is an Edge?
At its core, an **Edge** is simply *a pattern that produces profitable trades*. It is not restricted to complex mathematical equations; it is a vast net of independent, real-world anomalies that can be cataloged and exploited. It is a repeatable factor that lets you consistently make money over many trades, and produces a positive expected value (EV).

There are **6 Core Edges** the system must track:
1. **Price / Technical:** Patterns (e.g., RSI bounces, Bollinger Band breakouts, mean reversion, and trend following) that are statistically more likely to work than random chance.
2. **Fundamental:** Value discrepancies, balance sheet strength, growth metrics, or DCF models that identify mispriced assets relative to their intrinsic worth.
3. **News-Based / Event-Driven:** Real-world event triggers (e.g., political tweets, macroeconomic shifts, specific corporate lawsuits).
4. **Stat/Quant:** Pure historical probability vectors (e.g., seasonal patterns, overnight gap fills, option flow anomalies).
5. **Behavioral/Psychological:** Exploiting human panic, herding, or pre/post-earnings options volatility vs. market sentiment.
6. **"Grey":** Information that is almost like insider trading without being illegal, just less common/priced-in information (e.g., tracking politician stock purchases, or non-public corporate hacks).
- **Execution:** While another form of an edge, outside of proper coding, we will not be able to compete with HFTs and large firms on this so it will not be a focus. However, it can be seen as gaining fractions of a percent through smarter routing or lower slippage.

**The "True Edge"**:
The ultimate goal of the system is to combine these individual edges. The holy grail of the system, a "True Edge", does not rely on a single edge; but instead activates when multiple independent categories (e.g., a strong technical setup aligns perfectly with positive news sentiment and favorable macro conditions) align simultaneously to create a high-conviction, massive-win-rate signal.


## The Long-Term Vision
- **The "Real Fund Manager" Mentality:** The system must act as a true institutional fund manager—prioritizing deep architectural planning over rushed coding, and brutal realism regarding system capabilities.
- **Live Operations:** Seamlessly transition from Backtesting (local CSVs) -> Paper Trading (Alpaca) -> Live Execution with real capital.
- **Self-Evolution:** Use machine learning to detect market regimes (high vol, low vol, trend, chop) and autonomously discover or prioritize edges.
- **NOT overfit:** The system must be designed to avoid overfitting to historical data using techniques such as cross-validation and walk-forward analysis.
- **Explainability:** Provide clear UI attribution (Cockpit Dashboard) detailing exactly *why* a trade fired, and *which* edge was responsible.
- **Resilience:** Operate with institutional-grade safety guardrails preventing catastrophic drawdowns.
