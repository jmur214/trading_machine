Trading Machine Master Context

Purpose and Vision

Trading Machine is a modular Python‐based quantitative trading framework designed to research, test and execute multiple trading strategies (“edges”) while continually learning from its own performance.  It integrates data ingestion, signal generation, risk management, execution simulation, portfolio accounting, feedback learning and dashboard visualization into a single end‑to‑end system.  The long‑term goal is to build an autonomous, adaptive portfolio manager capable of discovering profitable patterns, allocating capital intelligently and compounding returns across multiple assets and strategies.  The system operates in three modes—backtest, paper trading and (future) live—using the same internal logic while swapping data sources and execution adapters ￼.

This document provides a stable, always‑loaded reference for AI agents and developers working on the Trading Machine codebase.  It describes how the system works, the responsibilities and interfaces of each component, the data flow, architectural invariants, and the overarching design principles.  Use this document to orient yourself before diving into individual modules or implementing new features.

High‑Level System Flow

The trading machine follows a pipeline in which market data flows through a series of engines, ultimately producing trades, updating the portfolio and feeding back performance information:
	1.	DataManager – Fetches and normalizes historical or live price data into a consistent OHLCV format, computing derived indicators like ATR and storing caches for reuse ￼.
	2.	AlphaEngine (Engine A) – Executes each active edge (strategy) against the latest slice of data, normalizing and aggregating raw signals into a list of discrete trading signals (ticker, side, strength, metadata) ￼.  It applies regime gates and governor weights and enforces signal hygiene and cool‑downs.
	3.	RiskEngine (Engine B) – Converts signals into executable orders, choosing the appropriate quantity and stops/targets based on portfolio equity, volatility, risk limits and cooling periods ￼.
	4.	ExecutionSimulator – In backtest mode, simulates fills at the next bar’s open price (with configurable slippage and commission), and evaluates stop‑loss/take‑profit intrabar ￼.  Future modes will use unified order adapters (SimExecutionAdapter for backtest, AlpacaExecutionAdapter for paper/live).
	5.	PortfolioEngine (Engine C) – Maintains positions, cash and equity; applies each fill, tracks realized/unrealized PnL and produces time‑stamped snapshots of the portfolio state ￼.  In v2 it will manage sleeves (core holdings, tactical edges, experimental) with target weights and drift control ￼.
	6.	CockpitLogger – Persists trades and snapshots to structured logs (CSV today; DuckDB in the future), ensures schema integrity and run‑level isolation and provides run identifiers (run_id) ￼.  Logs feed the dashboard and analytics modules.
	7.	PerformanceMetrics & EdgeFeedback – Reads trade logs and snapshots to compute portfolio‑ and edge‑level statistics such as Sharpe ratio, maximum drawdown, trade count and correlation ￼.  The analytics/edge_feedback.py module updates the governor’s edge weights based on these metrics, writes history logs and supports merging external recommendations ￼.
	8.	StrategyGovernor (Engine D) – Updates the relative weights of each edge based on their risk‑adjusted performance and diversification, applying a policy such as Sharpe‑weighted softmax with bounds and decorrelation penalties ￼.  The governor then feeds these weights back into the AlphaEngine for the next run, creating a learning feedback loop.
	9.	Dashboard (Cockpit) – Presents an interactive interface (Dash/Plotly) to monitor equity curves, drawdown, edge attribution, performance metrics, benchmark comparisons and governor state.  Different tabs display PnL history, analytics, edge intelligence (e.g. news summarizer) and settings.  Paper and live modes will reuse the same UI with real‑time data adapters.

Conceptual Data Flow
Market data (Yahoo/Alpaca/CSV) → DataManager → Edge modules → SignalCollector → AlphaEngine → RiskEngine → ExecutionSimulator → PortfolioEngine → CockpitLogger → PerformanceMetrics → StrategyGovernor → (feedback to AlphaEngine)
Modes and Uniform Contracts

All modes (backtest, paper, live) share the Order → Fill → Position → Snapshot contracts to guarantee consistent behavior across environments ￼.  Only the data source (historical vs real‑time) and execution adapter (simulator vs Alpaca API) differ ￼.  In backtest mode, orders are executed at the next bar’s open with simulated slippage; in paper/live mode, orders are sent via Alpaca and fills are returned asynchronously.

Core Engines and Interfaces

AlphaEngine (Engine A)
	•	Purpose: Generate trading signals by running multiple edges on the latest historical or live data slice.
	•	Inputs: slice_map (dict of ticker → DataFrame up to current time), timestamp, optional governor weights.
	•	Outputs: A list of signal dictionaries {'ticker': str, 'side': 'long'|'short'|None, 'strength': float, 'meta': dict} ￼.
	•	Responsibilities:
	•	Dynamically load and execute edge modules, handling variations in API (compute_signals returns numeric scores; generate_signals returns rich dicts).
	•	Normalize raw scores to [–1, 1], apply regime gates and hygiene checks, and convert aggregate scores into discrete sides/strengths ￼.
	•	Combine edge outputs using the governor’s weights and enforce cooldown periods to avoid flip‑flopping.
	•	Key Considerations:
	•	All edges should implement compute_signals(data_map, now) → dict[str, float] returning numeric scores per ticker.  Optionally, they may implement generate_signals() for rich outputs ￼.  Edges returning lists of signal dicts must be converted to numeric scores in the collector ￼.
	•	When implementing new edges, avoid silently returning non‑numeric structures; test with test_edge_outputs_extended.py to verify API compliance.
	•	The SignalCollector merges outputs from all edges, normalizing tickers and preventing invalid keys ￼.
	•	The SignalProcessor applies ensemble shrinkage and regime filters, while the SignalFormatter discretizes scores into actionable signals.

RiskEngine (Engine B)
	•	Purpose: Convert signals into orders while enforcing position sizing rules, risk caps and trading constraints. ￼
	•	Inputs: Signal dicts, current portfolio equity, historical price data, current positions, optional target weights.
	•	Outputs: Order dicts {'ticker': str, 'side': 'long'|'short'|'exit', 'qty': float, 'stop': float, 'take_profit': float}.
	•	Responsibilities:
	•	Calculate position sizes based on risk parameters such as ATR‑based volatility targets, Kelly fraction, maximum gross exposure, sector caps and per‑trade risk percentage.
	•	Generate exit orders when signals flip or risk parameters are violated; enforce cooldown periods to avoid churning.
	•	Optionally incorporate sleeve‑level targets in v2 (core/tactical/experimental), ensuring capital is allocated according to portfolio policy ￼.
	•	Future Enhancements:
	•	Support adjustable risk profiles (conservative/balanced/aggressive/degen) with per‑profile settings for leverage, gross/net exposure and allowed instruments ￼.
	•	Add vol‑targeting, beta caps and drawdown brakes as part of RiskEngine 2.0 ￼.

ExecutionSimulator
	•	Purpose: Simulate realistic order fills and stop/target triggers for backtesting ￼.
	•	Inputs: Order dict or position, next‑bar OHLC data, previous close price.
	•	Outputs: Fill dict {'ticker': str, 'side': str, 'qty': float, 'price': float, 'commission': float}.
	•	Responsibilities:
	•	Execute entries and exits at the next bar’s open price (fallback to close if open is unavailable).  In v1, the simulator uses the raw open price; v2 will incorporate a configurable slippage model (fixed bps, spread‑based, volume‑dependent) to adjust fill prices ￼.
	•	Check intrabar stops and targets using the same bar’s high/low; apply conservative tie‑breakers—stop triggers fire before targets.
	•	Handle gaps between bars by passing the previous close to warn about overnight moves.
	•	Provide stub functions for partial fills and advanced order types (limit, stop‑limit) for future OMS support ￼.

PortfolioEngine (Engine C)
	•	Purpose: Track positions, cash, market value, equity and realized/unrealized PnL; apply fills and produce snapshots ￼.
	•	Inputs: Fill dicts, price map for snapshotting.
	•	Outputs: Snapshot dict {'timestamp': ts, 'cash': float, 'equity': float, 'positions': dict}.
	•	Responsibilities:
	•	Maintain a ledger of open positions (symbol, quantity, average price, unrealized PnL).  Update positions on each fill: buys increase quantity and adjust average price; sells reduce quantity and realize PnL; exits close positions and realize profit/loss.
	•	Update cash and equity after each fill; ensure the invariant equity ≈ cash + market_value holds to within numerical tolerance ￼.
	•	Provide snapshots at every bar to the CockpitLogger; compute realized/unrealized PnL, gross/net exposure, and per‑edge open positions.
	•	In v2, manage sleeves and target allocations; compute drift relative to targets and output rebalance orders ￼.
	•	Invariants:
	•	The equity drift fix ensures that realized PnL is only updated on exit events and that cash and market value are recomputed from fresh prices each snapshot ￼.
	•	Each run must produce one snapshot per bar (no missing timestamps), with no duplicate timestamps ￼.

CockpitLogger
	•	Purpose: Persist trades and portfolio snapshots to durable storage for analytics and dashboard consumption ￼.
	•	Inputs: Trade dicts and snapshot dicts; optional portfolio reference for derived metrics.
	•	Outputs:
	•	data/trade_logs/trades.csv: Each row contains run_id, timestamp, ticker, side, quantity, price, fill_price, commission, edge_id, sleeve, realized PnL, meta.
	•	data/trade_logs/portfolio_snapshots.csv: Each row contains run_id, timestamp, cash, equity, market value, realized PnL, unrealized PnL, gross exposure, net exposure, positions (as JSON) and open positions by edge.
	•	Responsibilities:
	•	Validate and heal schemas (auto‑add missing columns), enforce numeric types and ensure no negative or NaN values in critical fields.
	•	Isolate runs by run_id; promote per‑run folders to the top‑level only once the run ends (prevents stale file overwrites ￼).
	•	Provide immediate or batched flushes to disk.  In v2, logging will mirror into DuckDB/Parquet via DataStore for improved scalability and queryability ￼.
	•	Invariants:
	•	Every trade and snapshot row must contain a valid run_id; no duplicate or missing run_id entries ￼.
	•	Schema must remain stable across runs; avoid adding ad‑hoc columns without updating logging code and test schemas.

PerformanceMetrics & EdgeFeedback
	•	Purpose: Analyze backtest results to compute risk‑adjusted performance metrics and update edge weights ￼.
	•	Inputs: Trades and snapshots from the latest run; current governor settings.
	•	Outputs:
	•	edge_metrics.json: Per‑edge metrics such as Sharpe ratio, maximum drawdown, correlation penalties and trade counts ￼.
	•	edge_weights.json: Updated weights for each edge; stored under data/governor.
	•	feedback_history.log: Time‑stamped JSON lines recording previous weights, updated weights, metrics and merged recommendations for traceability【16†L1-L1】.
	•	Responsibilities:
	•	Compute portfolio returns and risk metrics: Sharpe ratio (mean return / standard deviation × √252), maximum drawdown, hit rate, volatility and others.
	•	Attribute realized PnL to each edge using edge_id in trades and open positions by edge in snapshots; calculate per‑edge Sharpe and drawdown and penalize highly correlated edges ￼.
	•	Merge external evaluator recommendations (e.g. research optimizer outputs) with current weights using configurable rules ￼.
	•	Persist updated weights and metrics; provide a CLI interface to view history or run updates manually.

StrategyGovernor (Engine D)
	•	Purpose: Adaptively reweight edges based on their performance, diversification and risk.  Acts as the high‑level portfolio manager.
	•	Inputs: Per‑edge metrics and aggregated portfolio metrics from PerformanceMetrics; configuration parameters (softmax factor, minimum/maximum weights, decorrelation penalty) ￼.
	•	Outputs: Weight dictionary mapping edge_id to float (0–1) and optional rationale metadata, stored in data/governor/edge_weights.json ￼.
	•	Responsibilities:
	•	Compute softmax‑weighted scores of edges using Sharpe ratios, applying bounds and a decorrelation penalty to favour diversification ￼.
	•	Optionally incorporate sleeve budgets, ensuring each sleeve (core, tactical, experimental) respects minimum and maximum allocation limits ￼.
	•	Update the AlphaEngine’s weighting configuration so that more capital flows to stronger edges in the next run.
	•	Maintain a history of weight changes and rationales for dashboard transparency.
	•	Invariants:
	•	The sum of weights should equal 1.0 (or 100%); the governor renormalizes weights after applying penalties and limits.
	•	Edges with no trades or extremely poor performance may receive a minimal weight, but should not be completely disabled without explicit configuration.

DataManager and Data Layer
	•	Purpose: Provide a unified interface for data ingestion, caching and normalization across backtest and live modes ￼.
	•	Inputs: Ticker list, timeframe, start/end dates, API credentials, optional universe name.
	•	Outputs: Dict[str, pd.DataFrame] containing OHLCV bars (and optionally derived columns like ATR, previous close) for each ticker.  Missing columns raise a KeyError during normalization ￼.
	•	Responsibilities:
	•	Fetch data from Alpaca (paper/live) or fallback to local CSV caches; implement caching to avoid redundant downloads.
	•	Normalize time indexes to naive pd.DatetimeIndex and sort them chronologically ￼.
	•	Compute additional indicators (ATR, returns, volatility) used by edges and risk engine.
	•	In v2, integrate with a DuckDB/Parquet DataStore to read/write bars, trades and snapshots with run_id keys ￼.

Architectural Invariants and Rules

To maintain consistency and reliability across the system, several invariants and rules must always be respected:
	1.	Equity Consistency: At every snapshot, equity ≈ cash + market value within a numerical tolerance.  Violations indicate accounting errors and must be fixed immediately ￼.
	2.	Run Isolation: Each backtest or paper session is associated with a unique run_id.  Trades and snapshots must be logged with this run_id and never overwritten by subsequent runs ￼.
	3.	One Snapshot per Bar: The logger must record exactly one snapshot per trading bar (daily bar in v1).  Missing or duplicate timestamps break performance metrics ￼.
	4.	Unified Edge API: Every edge module must implement a compute_signals function returning a dict[str, float].  The collector should gracefully handle lists of rich signal dicts by converting them into numeric scores ￼.  Mismatches lead to dropped signals and empty trades.
	5.	Order–Fill–Position Contracts: All modes must use the same Order, Fill and Position dataclasses defined in the unified OMS.  Do not create ad‑hoc dicts for orders or fills; use the standard models to ensure consistent handling across simulators and brokers ￼.
	6.	No Side‑Effects in Edges: Edges should be pure functions of the input data slice and current timestamp.  They must not modify shared state or rely on external network calls during backtests.  For heavy computations (e.g. ML), precompute features offline and supply via CSV/Parquet.
	7.	Configurable Realism: Execution realism (slippage, commissions, market impact) is controlled via configuration.  Do not hard‑code slippage or stop logic inside the core engines; instead implement pluggable models as described below ￼ ￼.
	8.	Logging and Metrics Schema: The schema of trades and snapshots must be kept stable.  Adding new columns or changing types requires updating logger, metrics, tests and documentation accordingly.  When migrating to DuckDB, mirror writes to both CSV and DB for a few sprints to ensure parity ￼.
	9.	Edge Attribution: Fills and snapshots must record which edge generated a trade via edge_id and which edge currently holds an open position (open_pos_by_edge).  This enables per‑edge performance measurement and governor weighting ￼.
	10.	Safety and Risk Controls: RiskEngine must enforce maximum leverage, per‑asset exposure caps and drawdown halts.  Do not bypass these constraints even in debug runs; they protect the portfolio from catastrophic losses and unrealistic scaling.

Extensibility Guidelines

Adding New Edges
	1.	Create a new module under engines/engine_a_alpha/edges/ or similar.  Implement compute_signals(data_map: dict[str, DataFrame], now: pd.Timestamp) -> dict[str, float].  Optionally implement generate_signals(data_map, now) -> list[dict] for rich dashboards.
	2.	Use only data provided in data_map.  If the strategy requires external features (news sentiment, fundamentals, AI scores), precompute them and store in data/research/<source>.csv so they can be joined inside compute_signals.
	3.	Include metadata in signal dicts (e.g., RSI values, breakout levels, “edges_triggered”) for dashboard explanations.
	4.	Register the edge with an EdgeSpec in the EdgeRegistry so that the AlphaEngine discovers it automatically.  Provide edge_id, edge_name, category (“technical”, “fundamental”, “news”, “ai”), default parameters and descriptions.
	5.	Write unit tests verifying that compute_signals returns a dict with finite floats and that generate_signals (if present) contains valid sides and confidences.
	6.	Document parameters and expected behavior in docs/EDGE_SYSTEM.md (to be created as part of the documentation plan).

Extending the Risk Engine
	1.	Support risk profiles (conservative, balanced, aggressive, degen) by loading a risk_profiles section from configuration and selecting per‑profile parameters such as per‑trade risk percentage, maximum gross/net exposure, leverage, and allowed asset classes ￼.
	2.	Implement vol‑targeting and beta caps: size orders so that the ex‑ante portfolio volatility matches a target (e.g., 10%) and the beta to a benchmark remains below a threshold.  Use historical volatility or EWMA models to estimate ex‑ante risk.
	3.	Add drawdown brakes: if the portfolio’s peak‑to‑trough drawdown exceeds a configured limit, pause new entries or scale down positions until recovery.
	4.	Introduce sector caps and asset caps: limit exposure to any sector or individual ticker, using classification data from the universe file.
	5.	Expose these controls in the configuration (JSON/YAML) and in the dashboard.

Execution Realism and Market Impact
	1.	Implement a SlippageModel (engines/execution/slippage.py) with a base interface get_fill_price(side, raw_price, bar, notional) -> float.  Provide models:
	•	fixed_bps: apply a fixed basis point adjustment based on trade side and notional ￼.
	•	spread_half: use the bar’s high/low/close to estimate bid/ask and execute buys at the ask and sells at the bid.
	•	impact_bps: adjust slippage based on trade size relative to average daily volume (ADV); larger trades in illiquid names incur higher impact ￼.
	2.	In the backtester, replace raw fill price assignments with calls to slippage_model.get_fill_price() and pass notional and side. ￼
	3.	Later, build a MarketImpactModel that adds extra bps based on notional / (ADV * price) ￼.  Keep this pluggable so that different strategies or markets can use different impact assumptions.
	4.	When moving to live trading, reuse the same models to adjust order placement (e.g., decide between market and limit orders) and to estimate expected fill prices.

Portfolio Engine 2.0 and OMS
	1.	Refactor PortfolioEngine to manage sleeves: core holdings (longer‑term positions), tactical edges (swing/short‑term strategies) and experimental edges.  Each sleeve has target min/max weights and drift limits ￼ ￼.
	2.	Implement set_targets(targets: dict[str, float]) to specify desired allocations per edge; compute drift by comparing current weights with targets and generate rebalancing orders via compute_rebalance_orders() ￼.
	3.	Introduce a Unified OMS under portfolio/ that defines standard Order, Fill and Position dataclasses and adapters for simulation and Alpaca (paper/live) execution ￼.  The backtest loop should call oms.submit_orders() and receive fills, which are then applied to the portfolio.
	4.	Wrap the existing ExecutionSimulator into SimExecutionAdapter.  For paper/live modes, implement AlpacaExecutionAdapter that uses Alpaca’s REST/Streaming API and returns standardized fill objects ￼.
	5.	Use a DataStore (DuckDB/Parquet) to persist runs with run_id, trades, snapshots, weights and metrics.  Mirror writes to both CSV and DB during the migration phase and update DataManager and dashboard to read from DB when available ￼.

Governor Evolution and Learning Engine
	1.	Enhance the governor to compute per‑edge metrics (Sharpe, MDD, hit rate, trade count, correlation) using the analytics module.  Use these metrics to derive weights via a policy such as softmax of Sharpe ratios with minimum/maximum weights and decorrelation penalty ￼.
	2.	Incorporate sleeve budgets: after computing raw weights, group edges by sleeve and renormalize to satisfy the configured min/max allocation per sleeve ￼.
	3.	Record rationales for weight changes (e.g. “Edge momentum_trend outperformed with Sharpe 1.2; correlation with value_edge = 0.3; weight increased to 0.35”).  Persist rationales alongside weights for dashboard explainability ￼.
	4.	Provide CLI and API endpoints to inspect governor history and to run the feedback update manually (python -m analytics.edge_feedback --history).
	5.	In later phases, experiment with Bayesian updating or reinforcement learning to adjust weights based on PnL distributions and risk preferences.

Dashboard and User Experience
	1.	Expand the dashboard to include new tabs: “Recommended Trades” showing top signals per day with entry/stop/target and meta reasons ￼, “Health Checks” summarizing data, portfolio and risk integrity ￼, and “Governor” showing sleeve totals, diversification scores and weight rationales ￼.
	2.	Integrate the TradingView charting library for high‑quality charts; overlay trades, signals and edge triggers.  Use TradingView alerts and webhooks to feed external signals into the system (e.g. Pine Script strategies) for additional edges.
	3.	Provide a health_check.py script that verifies data integrity (no NaNs, no duplicate timestamps), portfolio consistency (equity = cash + market value), PnL consistency and risk sanity (no position or leverage violations) ￼.
	4.	Support multiple universes (e.g., SP500, crypto) via config/universe.json; update DataManager to load all tickers in the chosen universe and ensure position sizing scales appropriately ￼.
	5.	Build a context document repository (in /docs) including ARCHITECTURE_OVERVIEW.md, EDGE_SYSTEM.md, LOGGING_INVARIANTS.md and CONTRIBUTING.md to reduce context drift and ease onboarding ￼.

Current State and Known Issues (as of 11 Dec 2025)

The 11‑December progress report confirms that the system now produces consistent trades, snapshots and performance metrics.  Key fixes included eliminating equity drift in PortfolioEngine, refactoring CockpitLogger to use per‑run folders, ensuring run_id propagation, standardizing fill dictionaries and validating snapshot continuity ￼ ￼ ￼.  The entire backtest loop is now end‑to‑end functional: signals produce orders, fills update the portfolio, trades log correctly, snapshots reflect positions and metrics are meaningful ￼.  The system therefore provides a solid foundation for further development.

Remaining issues and tasks are tracked in the dynamic roadmap (see trading_machine_ROADMAP.md).  Major areas include implementing slippage and market impact models, expanding the universe of tickers, supporting adjustable risk profiles, adding new edges (news, fundamentals, AI), migrating to a unified OMS and DuckDB storage, and enhancing the governor and dashboard for explainability and user experience.

Conclusion

The Trading Machine is a sophisticated research and execution platform aimed at creating an intelligent, self‑learning portfolio manager.  Its modular architecture—comprising the DataManager, AlphaEngine, RiskEngine, ExecutionSimulator, PortfolioEngine, CockpitLogger, PerformanceMetrics and StrategyGovernor—provides clear interfaces and responsibilities ￼.  A rigorous logging and feedback loop ensures that every trade is recorded, every snapshot is consistent and every edge is evaluated.  By adhering to the invariants and extensibility guidelines outlined in this document and by following the roadmap of future enhancements, developers and AI agents can evolve the system toward a robust, production‑ready quant platform capable of adaptive multi‑edge trading across multiple asset classes.