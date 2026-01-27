Trading Machine Dynamic Roadmap

This living document tracks ongoing work, planned enhancements and research directions for the Trading Machine project.  Items are grouped into phases but may be reprioritized as development progresses.  Use this roadmap to coordinate development, avoid duplicating efforts and ensure the system evolves toward its long‑term vision of a self‑learning portfolio manager.

Recently Completed (Foundation)

These milestones have been achieved as of 11 December 2025 and form the baseline for future work:

***Table***

With these foundations, the system is ready for new features and research.

Phase 1 – Realism & Risk (High Priority)
	1.	Implement Slippage Models ￼
	•	Create engines/execution/slippage.py with a base BaseSlippageModel and concrete implementations: fixed_bps, spread_half, and impact_bps.
	•	Modify ExecutionSimulator (and later OMS adapters) to compute fill prices via the configured slippage model: fill_px = slippage_model.get_fill_price(side, raw_px, bar, notional).
	•	Add configuration fields in config/backtest_settings.json or system config: e.g., "slippage": {"model": "fixed_bps", "bps": 5}.
	2.	Expand Universe of Tickers ￼
	•	Introduce config/universe.json defining named universes (e.g., SP100, SP500, Crypto10, Top300_US).
	•	Update DataManager to load all tickers in the selected universe, cache OHLCV data and handle large portfolios (vectorization, memory management).
	•	Ensure RiskEngine scales position sizing appropriately across more symbols and prevents concentration.
	3.	Adjustable Risk Profiles ￼
	•	Define a risk_profiles section in configuration with per‑profile settings: per‑trade risk percentage, max gross exposure, max leverage, allowed instruments (crypto/options).
	•	Expose a high‑level risk_profile parameter for users to choose between conservative, balanced, aggressive and degen modes.
	•	Modify RiskEngine to read the current profile and enforce appropriate limits; adjust universe filters accordingly (e.g., allow crypto only in certain profiles).
	4.	Market Impact Model ￼
	•	Extend the SlippageModel to incorporate market impact based on trade size relative to average daily volume (ADV).  Calculate impact_bps = impact_k × (notional/(ADV × price)) and add this to the base slippage.
	•	Maintain a lookup of ADV per ticker (CSV or DataStore table) and update regularly.
	•	Use the same model for paper/live trading to estimate expected fill prices and adjust order types accordingly.
	5.	Monte Carlo Simulation ￼
	•	Build a module to resample per‑trade or per‑day returns and simulate thousands of equity paths.  Compute distributions of final return and maximum drawdown.
	•	Generate summary statistics (5th/50th/95th percentiles) and visualizations (histogram, fan chart).
	•	Include the Monte Carlo summary in analytics reports and optionally on the dashboard.

Phase 2 – Research & Multi‑Edge Expansion
	1.	Formalize Edge Registry and API ￼
	•	Define an EdgeBase abstract class with compute_signals() returning numeric scores and optional generate_signals() returning rich outputs.
	•	Create an EdgeRegistry to register available edges, their IDs, categories and parameter defaults.
	•	Refactor existing edges to conform to the unified API; update tests accordingly.
	2.	Add New Edge Types ￼
	•	News Edge: Read data/research/news_scores.csv containing sentiment scores, source counts and headline risk; produce long or short signals based on thresholds.
	•	Fundamental Edges: Read fundamentals.csv with PE, PB, ROE, debt-to-equity and growth metrics; implement ValueEdge and QualityEdge and combine with technical signals.
	•	AI Feature Edge: Ingest offline AI‑scored features (e.g., management quality, regulatory risk) from ai_features.csv; map high scores to long/short biases.
	•	Ensure each new edge conforms to the unified API and is registered with EdgeRegistry.
	3.	Per‑Edge Attribution and Weighting ￼
	•	Compute realized and unrealized PnL by edge using edge_id in trades and open_pos_by_edge in snapshots.  Calculate per‑edge Sharpe, drawdown and trade counts.
	•	Extend the governor to update weights using these metrics; implement smoothing (e.g. exponential moving average) and correlation penalties ￼.
	•	Persist rationales for weight changes and display them in the dashboard.
	4.	Tax‑Aware Analysis ￼
	•	Design a tax_config.json specifying federal/state brackets and short/long‑term rates.
	•	Implement a tax_analyzer module to classify realized gains as short or long term, estimate tax liability and suggest candidates for tax loss harvesting.
	•	Provide hooks in the strategy/exit logic to consider holding period before converting unrealized gains into short term.
	5.	Stop‑Hunt & Volatility Handling ￼
	•	Create a StopPolicy component that computes stop distances based on ATR and current volatility regime; widen stops in high vol regimes and narrow them in low vol.
	•	Introduce time‑based filters to avoid placing stops near the open or during macro events.
	•	Implement partial take‑profit and trailing stops to lock in gains and reduce the impact of intraday spikes.
	6.	Fundamental & Cross‑Sectional Research ￼
	•	Treat fundamentals as slow‑moving state; avoid over‑trading on small changes.  Use factor models for value, quality, growth and risk.
	•	Combine fundamental scores with technical momentum/reversion to identify robust opportunities.
	•	Ensure portfolio constraints prevent excessive allocation to “junk” stocks and encourage diversification across fundamentals and technical edges.

Phase 3 – User Experience & Documentation
	1.	Health Checks & Diagnostics ￼
	•	Implement scripts/health_check.py to validate data integrity (no NaNs, no duplicate timestamps), portfolio accounting (equity consistency), PnL consistency and risk limits.
	•	Generate a health_report.json after each run; display a summary (“System Health: ✅ / ⚠️ / ❌”) on the dashboard.
	2.	Dashboard Enhancements ￼ ￼
	•	Add a “Recommended Trades” tab showing top signals with entry/stop/target, confidence and combined edge reasons; allow simulation of hypothetical PnL if taken.
	•	Enhance the Governor tab to show sleeve totals, diversification scores and rationales for weight changes; visualize weight evolution over time.
	•	Integrate the TradingView charting library for professional charts; overlay signals and governor state.
	•	Provide run comparison tools (select two run_ids and compare performance metrics, weight trajectories and trade distributions) ￼.
	3.	Documentation & Context Packaging ￼
	•	Create a /docs folder with: ARCHITECTURE_OVERVIEW.md, EDGE_SYSTEM.md, LOGGING_INVARIANTS.md, CONTRIBUTING.md and TASK_HISTORY.md summarizing major changes.
	•	Write developer guides for run_id usage, DataStore migration, and edge development guidelines.
	•	Maintain this roadmap as part of the repo; update it whenever tasks are completed or new priorities emerge.

Phase 4 – Hygiene & Hardening
	1.	Code Cleanup & Testing ￼
	•	Wrap all print statements with debug flags; remove obsolete modules and engines.
	•	Apply formatting (e.g. black, ruff) and enforce linting.
	•	Expand the test suite: unit tests for PortfolioEngine, CockpitLogger, RiskEngine, Governor; integration tests for the backtest loop and edge APIs; golden run fixtures to catch regression ￼.
	2.	Continuous Validation & Alerts ￼
	•	Implement scripts/continuous_validation.py to monitor runs periodically; check for lack of trades, stale weights, or abnormal performance.
	•	Integrate alerting (e.g. Discord/Telegram) for live mode when the portfolio deviates from expected exposures or risk limits.
	3.	Data & Storage Migration ￼
	•	Introduce DataStore backed by DuckDB/Parquet; mirror writes from logger, metrics and governor; assign run_id keys for easy queries.
	•	Gradually migrate dashboards and analytics to read from the DB, with CSV fallback until parity is confirmed.
	•	Version configs by computing a hash of the configuration dictionary and storing it with each run. ￼
	4.	Unified OMS & Portfolio ￼ ￼
	•	Create portfolio/ directory with order_types.py (Order, Fill, Position enums), oms.py (base OMS), sim_adapter.py (wraps ExecutionSimulator) and alpaca_adapter.py (Alpaca broker wrapper).
	•	Refactor BacktestController to use the new OMS: call oms.submit_orders() to receive fills; apply them to the portfolio; snapshot; log via CockpitLogger or DataStore.
	•	Introduce sleeves.py to manage sleeve definitions and targets; integrate with PortfolioEngine to compute drift and generate rebalance orders.
	5.	Risk Engine 2.0 ￼
	•	Enforce portfolio‑level limits: gross and net exposure, per‑sector caps, turnover limits, drawdown brakes and beta caps.
	•	Implement vol‑targeting such that position sizes scale with target portfolio volatility.
	•	Provide configuration hooks for these limits and expose them in the dashboard.

Longer‑Term & Experimental Directions
	1.	Live Trading & Alpaca Integration
	•	Develop AlpacaExecutionAdapter to send and manage live orders via Alpaca’s API.  Handle streaming of quotes and fills; implement rate‑limit retries and error handling ￼.
	•	Build an event‑driven loop for paper/live mode that streams price updates, triggers signal generation and sends orders asynchronously.
	•	Integrate nightly governor updates and daily health checks for live trading.
	2.	Machine Learning & Reinforcement Learning Edges
	•	Incorporate advanced ML models (e.g. XGBoost, LSTM, Transformers) trained on price/volume/fundamental features with walk‑forward validation to avoid lookahead bias ￼.
	•	Explore reinforcement learning for position sizing and dynamic hedging; implement meta‑learning ensembles to adapt to regime changes【4†L0-L0】.
	•	Integrate external ML frameworks (TensorFlow/PyTorch) while maintaining reproducibility and run_id tracking.
	3.	Bayesian & RL Governor Policies
	•	Research Bayesian updating of edge weights, modelling uncertainty in performance estimates and adjusting weights accordingly.
	•	Consider reinforcement learning policies that reward long‑term PnL and risk management, penalising volatility and correlation.
	•	Experiment with multi‑armed bandit approaches to allocate capital among edges.
	4.	Advanced Risk & Capital Allocation
	•	Implement hierarchical risk parity (HRP) and modern portfolio optimization techniques (Black–Litterman, minimum variance, max diversification) for portfolio construction【chat1】.
	•	Introduce risk contributions per edge and per sleeve; adjust allocations to equalise risk contributions (risk parity) rather than capital weights.
	•	Explore dynamic rebalancing schedules based on market regimes (volatility, momentum, macro indicators).
	5.	Cross‑Asset & Multi‑Timeframe Support
	•	Add crypto, forex and futures to the universe; handle different trading hours and venue behaviours.  Provide toggles to include/exclude asset classes by risk profile.
	•	Allow edges to specify the timeframe they operate on (e.g. daily, 1h, 5m); update DataManager to fetch appropriate bars and extend the backtester to iterate over intraday bars.
	•	Implement cross‑timeframe signal aggregation and weighting in AlphaEngine.
	6.	Tax & Compliance
	•	Continue to develop tax‑aware heuristics; eventually integrate with tax reporting tools.
	•	Incorporate wash‑sale rules and regulatory constraints for US accounts.
	•	Document compliance obligations for algorithmic trading systems.

Maintenance & Ongoing Tasks
	1.	Documentation upkeep: Keep the master context and roadmap documents updated whenever the architecture changes or tasks are completed.  Ensure developers read and understand these references before contributing.
	2.	Unit & integration testing: Expand tests as new modules are added; run regression tests after significant changes.
	3.	Performance monitoring: Profile the backtester and dashboard performance on large universes; optimise data loading and vectorised computations.
	4.	Security & credentials: Safeguard API keys (.env) and avoid committing secrets; implement rate‑limit handling and secure storage.
	5.	Community feedback: Incorporate feedback from users and collaborators to refine the roadmap and prioritise features.

⸻

This roadmap represents the current priorities and long‑term vision for the Trading Machine.  It should be revised regularly as work progresses, new challenges arise and market conditions change.
