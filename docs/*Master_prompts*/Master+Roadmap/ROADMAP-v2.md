Trading Machine – Dynamic Roadmap

This roadmap tracks completed work, current priorities and long‑term initiatives for the Trading Machine.  It aggregates tasks from chat transcripts, audit reports, system design documents and progress summaries.  Items are grouped by phase and include high‑level descriptions, responsible components and rationale.  The roadmap should be updated regularly as work progresses.

1. Completed Since v1 Launch (2025‑11‑12)

The system transitioned from a partially wired architecture to a functional backtesting pipeline.  Key completed items include:

****TABLE****

2. Immediate Priorities (Phase 1: Realism & Risk)
	1.	Slippage Model Abstraction – Introduce engines/execution/slippage.py with a base class get_fill_price(side, raw_price, bar, notional) and implement:
	•	Fixed bps model (e.g. 5 bps per trade).
	•	Half‑spread model (uses bar’s high/low/close to approximate bid/ask).
	•	Later: impact‑based model using square‑root law impact ≈ c × σ × sqrt(Q/V) with configurable constant c.
Modify ExecutionSimulator or the new OMS to call the slippage model when computing fill prices.
	2.	Expanded Universe – Support backtests on 50–500 tickers.  This requires optimizing DataManager caching, slicing operations in BacktestController, risk engine performance and governor scaling.  Consider asynchronous data loading and vectorized operations for cross‑sectional edges.
	3.	Risk Modes & Regimes – Add multiple risk configurations (conservative, normal, aggressive, crypto) with toggles for allowing shorts, max positions, risk per trade and leverage.  Introduce a regime detector (e.g. based on VIX, breadth, interest rates) that automatically switches risk mode.  Allow the user to select a risk mode via config.
	4.	Market Impact & Liquidity – Implement a simple market impact model using the square‑root law (as described in chat3).  Expose impact_bps = k × sqrt(notional/ADV) and adjust position sizing when impact becomes non‑negligible (>0.1 % of ADV).  Factor ADV and volatility into risk budgeting.
	5.	Monte Carlo Simulation – Develop a Monte Carlo tool to generate alternative PnL paths and stress scenarios.  Use correlated random draws of returns and volatility to evaluate drawdown risk and return distribution for a given strategy.  Integrate this into analytics for risk assessment.
	6.	Intraday Framework Preparation – Begin refactoring DataManager and BacktestController to accept different timeframes (5m, 15m).  Edges should declare their required timeframe; the collector should load appropriate data.  Ensure that risk engine sizing remains consistent across timeframes (e.g. converting ATR from intraday to daily scales).

3. Research & Edge Expansion (Phase 2)
	1.	Formal Edge Registry – Define a Python class Edge with attributes name, category, version, timeframe and a standard compute_signals() signature.  Enforce this interface across all edges and deprecate ad‑hoc generate_signals formats.  Expand edge_registry.py to support versioning, status (active/candidate/retired) and parameter storage.
	2.	News Sentiment Edge – Build a pipeline that scrapes or subscribes to news (e.g. FinViz, StockTwits) and computes sentiment scores per ticker.  Store results in data/research/news_scores.csv.  Implement NewsEdge that goes long when sentiment >0.7 and volume > threshold, short when sentiment <−0.7.  Expose edge_id, edge_group (news) and meta (headline count, average sentiment).
	3.	Fundamental/Factor Edges – Ingest fundamental data such as PE, PB, ROE, earnings growth, debt‑to‑equity.  Create edges like ValueEdge (low PE/PB), QualityEdge (high ROE, low leverage) and Momentum52WeekEdge (buy stocks near 52‑week high as per chat8).  Add them to the registry with proper categories and test them via backtests.
	4.	AI Feature Edges – Develop a process (possibly offline) to assign AI‑generated scores to tickers (e.g. “business moat”, “management quality”, “regulatory risk”).  Store these in data/research/ai_features.csv and create AIEdge that maps scores to long/short signals.  Explore fine‑tuning LLMs or using external APIs for sentiment and risk scoring.
	5.	Cross‑Edge Research Harness – Extend research/edge_harness.py to run multi‑edge experiments: cross‑validate combinations of edges, evaluate correlation and Sharpe improvements, and produce evaluator recommendations.  Add CLI flags for specifying weight blending methods (e.g. equal weight, Sharpe weight, decorrelation penalty).  Save results to data/research/edge_recommendations.json for the governor.
	6.	Per‑Edge Attribution – Modify CockpitLogger and StrategyGovernor to track realized PnL and equity attribution per edge.  Use open_pos_by_edge counts and realized PnL to compute true returns per edge.  This will allow the governor to use real returns rather than pseudo returns (Pnl / MAD) and enable correlation penalties.
	7.	Tax‑Aware Logic (Analysis Mode) – At least in analytics, estimate after‑tax returns by applying capital gains tax rates based on holding period and realized PnL.  For now, treat as post‑processing step in PerformanceMetrics.

4. UX & Product Features (Phase 3)
	1.	Health/System Check – Build scripts/run_diagnostics.py and a dashboard tab that runs automated checks on data integrity (missing bars, outliers), edge output formats, backtester sanity (non‑empty trades, equity continuity), governor state and run_id mismatches.  Provide clear pass/fail messages and suggestions.
	2.	Recommended Trades Tab – In the Cockpit dashboard, create a tab that shows currently recommended trades based on the latest governor weights and current signals, along with meta information (expected Sharpe, drawdown, correlation).  Allow manual override or approval for live mode.
	3.	Context Documents – Expose context files (this master context and roadmap) within the dashboard so users (human or AI) can read them.  Provide search and filter functions.  Update these documents automatically when tasks are completed or new features are added.
	4.	TradingView Integration – Embed TradingView’s charting library into the dashboard.  Overlay signals, governor weights and trades onto high‑resolution price charts.  For live and paper modes, update charts in real time.  Use TradingView alerts (via webhook) as an additional signal source if desired.
	5.	Alerts & Notifications – Implement bots (Discord/Telegram) that notify the user when positions are opened/closed, stops/targets hit, edge weights change significantly, or health checks fail.  Provide configurability for frequency and severity of alerts.

5. Hygiene & Hardening (Phase 4)
	1.	Code Cleanup – Remove stale code paths, unify naming conventions, and eliminate duplicate functionality (e.g. multiple ways to compute PnL).  Use type hints consistently and document functions thoroughly.  Add linting and formatting (black, flake8).
	2.	Test Suite Expansion – Cover new modules (portfolio v2, OMS, sleeves, slippage models) with unit tests.  Write integration tests to ensure that intraday backtests, multi‑edge configurations, and governor feedback loops behave correctly.  Add regression tests for previously fixed bugs (empty trades, equity drift, mis‑shaped edge outputs).  Integrate tests into CI.
	3.	Config & Schema Validation – Implement schema validation for JSON/YAML config files using pydantic or similar.  Prevent invalid values (e.g. negative risk_per_trade_pct) from silently passing through.  Validate CSV/Parquet schemas when reading/writing trade logs and snapshots.  Provide explicit error messages.
	4.	Versioning & Migrations – Establish a versioning system for config files, edge specifications and run data.  Write migration utilities when changing schema (e.g. moving from CSV to DuckDB).  Include run metadata (software version, commit hash) in logs for reproducibility.
	5.	Performance Optimization – Profile the backtest loop to identify bottlenecks.  Use vectorized operations, caching of ATR and rolling indicators, and asynchronous I/O to improve speed when scaling to hundreds of tickers.  Evaluate numba or Cython for tight loops in risk sizing and execution simulation.
	6.	Security & Secrets Management – Ensure API keys (.env) are loaded securely and never committed.  Use environment variables or secret managers when deploying to cloud.  Restrict network access for live mode to prevent unauthorized trades.

6. Long‑Term / Experimental Ideas
	1.	Reinforcement Learning for Position Sizing – Implement RL agents (e.g. PPO, DDPG) that learn to allocate capital across edges or directly choose position sizes based on state features (signals, volatility, drawdown).  Use an environment wrapper around the portfolio engine.  Guard against overfitting via walk‑forward validation.
	2.	Meta‑Learning & Ensemble Optimization – Develop a meta‑learner that learns how to combine edge outputs dynamically, adapting to market regimes.  Techniques could include Bayesian model averaging, online learning with regret bounds, or hierarchical risk parity.
	3.	Cross‑Asset & Multi‑Market Expansion – Extend the platform to futures, options, FX and crypto.  Each asset class has unique tick sizes, hours, margin requirements and borrowing costs.  The risk engine must handle these differences; DataManager must fetch appropriate data; OMS must route orders to corresponding brokers/exchanges.
	4.	Decentralized Data & Execution – Explore using decentralized protocols (e.g. blockchain) for verifiable trade logging, trustless execution and data integrity.  This is speculative but aligns with transparency and auditability goals.
	5.	Investor Reporting & Compliance – Build modules to generate periodic investor reports (monthly/quarterly), including performance attribution, risk metrics, positions lists and compliance status.  Integrate with tax reporting tools for automated filings.
	6.	AI Assistant Integration – Integrate a conversational AI agent into the dashboard that can answer questions about performance, edges, and system health using this context file.  Ensure it has access to real‑time data and can suggest actions subject to user approval.

7. Updating this Roadmap

This document should be updated when:
	1.	A task is completed (move from current to completed section and describe outcomes).
	2.	A new bug or limitation is discovered (add to immediate priorities or hygiene tasks).
	3.	A new edge type or research idea is proposed (add to research section).
	4.	The architecture evolves (e.g. portfolio v2, unified OMS).  Reflect the new responsibilities and remove obsolete tasks.
	5.	Users request new product features or integrations (add to UX section).

When editing, keep descriptions concise but clear.  Use this roadmap alongside the master context to guide development decisions and ensure consistency with the system’s vision and architecture.