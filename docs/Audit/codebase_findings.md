# Architectural Audit: Codebase Findings

**INSTRUCTIONS FOR AI AGENT:**
1. This is a living document. The goal is to track findings, architectural flaws, weak points, and disconnects as we review the codebase folder by folder.
2. By the end of the audit, this document must provide a full picture of every folder, file, problem, and issue currently in the system.
3. If an initial assumption is proven incorrect by later research (e.g., discovering a script is actually a legacy unused file instead of a core bug), you MUST update this document to correct the record.
4. Highlight critical weaknesses (e.g., CSV reliance, bypasses, circular dependencies) clearly.

---

## 1. Documentation & Execution Manual (`docs/Core/`)
* **`execution_manual.md`:** A comprehensive command dictionary. It clarifies the system intent significantly. It maps commands into logical groups: Autonomous, System Health, Core System, Research, Evolution, Shadow Trading, and Data.

## 2. Scripts & Entry Points (`scripts/`)
* **Initial Observation Corrected:** I previously assumed `run_shadow_paper.py` was a hacky script circumventing `ModeController`. Upon reading the execution manual, this is actually the intended **Phase 2: Research & Shadow Trading** mechanism. It is explicitly designed to bypass the traditional 4-Engine risk pipelines to act as a lightweight "Hunter" simulation using a dummy `ShadowBroker` for evaluating ML decision trees.
* **The "One Button" Execution (`run_autonomous_cycle.py`):** This is the master orchestrator for the entire machine learning loop. It runs an infinite loop consisting of 5 steps: 1) Update Data, 2) The Hunter (Discovery), 3) Backtest Validation (Evolution), 4) Learning (Harvest & Train SignalGate), 5) Execution (Shadow Trading). 
* **Disconnect:** The `run_autonomous_cycle` relies almost exclusively on the ML/Discovery codebase. It does not utilize `ModeController.run_live()` or the classical 3-Engine pipeline for execution. The repository operates as two separate products: The Core Backtester and the ML Hunter-Gatherer loop.

## 3. Verification & Tests (`tests/`)
* **Critical Weak Point:** `test_alpha_engine.py`, `test_portfolio.py`, and `test_backtest_controller.py` are basically empty (39-byte stubs). There is near-zero unit test coverage for the core engines.
* **Bug Documentation:** `test_golden_path.py` explicitly reproduces and asserts the existence of two known, critical bugs:
  1. **Bagholder Bug:** The system holds positions permanently if data goes missing (gaps), rather than panic-exiting.
  2. **Vanity Bug:** Equity curves during data gaps remain flat or rely on stagnant `avg_price`, masking true risk.
* **Actionable Insight:** The user's system cannot safely scale to live execution until the Bagholder Bug is fixed and comprehensive unit tests exist for Engine B (Risk) and Engine C (Portfolio).

## 4. Orchestration (`orchestration/`)
* **`mode_controller.py`:** A well-architected abstraction designed to route Backtest, Paper, and Live modes through a unified Execution Adapter layer. However, initial findings suggest some newer scripts ignore it. We must track exactly *what* calls `ModeController`.

## 5. Data & Storage (`engines/data_manager/`, `data/`)
* **`DataManager` (The God Class):** This is a monstrous 719-line class doing way too much. It handles caching (writing both Parquet *and* CSV strings to disk simultaneously), REST API querying for Alpaca, REST API fallbacks for `yfinance`, and generating synthetic data.
* **Fundamental Scraping Bloat:** `DataManager` contains a 200-line `fetch_historical_fundamentals` function that manually downloads quarterly income/balance sheets via `yfinance`, reindexes them, lags them by 45 days, computes Trailing-Twelve-Month (TTM) math, and joins them back to price data. This logic should absolutely be in a separate `FundamentalProcessor` service.
* **CSV/Parquet Duplication:** Every single data fetch triggers a save to both Parquet and CSV on disk manually.
* **Risk:** The sheer weight of this class makes tracking data integrity bugs extremely difficult.

## 6. Core Portfolio Accounting (`engines/engine_c_portfolio/`)
* **`PortfolioEngine`:** Surprisingly clean and well-structured compared to other engines. It maintains the absolute accounting identity (`equity = cash + Σ(qty * price)`).
* **The Vanity Bug Patch:** There is explicit source code in `snapshot()` with a comment `[VANITY FIX] Use last_price if available, else 0.0. NEVER avg_price.` This proves the system is aware of the Vanity Bug (where disconnected prices create flat equity curves) and attempts to handle it by marking assets to 0.0 or last known price during data gaps.
* **Trail Tracking:** It tracks `highest_high` and `lowest_low` per position, meaning trailing stop logic relies on Engine C to maintain state.

## 7. Alpha Generation (`engines/engine_a_alpha/`)
* **`AlphaEngine` (God Class):** 815 lines long. It handles config loading, edge instantiation, data normalization, regime detection, and ML inference all in one place.
* **Cross-Engine Dependency:** It explicitly imports `RegimeDetector` from `engine_d_research`, breaking the strict separation of concerns.
* **ML Integration:** It attempts to load `data/models/rf_model.pkl` to act as a gate on signals (e.g., cutting size if ML confidence is low). This confirms that "shadow trading" models do interface with the core logic.

## 8. Risk & Sizing (`engines/engine_b_risk/`)
* **`RiskEngine` (God Class):** 787 lines. Handles volatility-scaled sizing (ATR), sector exposure limits (via `sector_map.json`), and liquidity constraints (ADV limits).
* **Architectural Leak (State Mutation):** In `manage_positions()` for trailing stops, the code notes that the backtester doesn't handle `update` orders well, so RiskEngine just directly mutates `pos.stop` in the `PortfolioEngine`'s state. This is a massive violation of the CQS (Command/Query Separation) principle and makes tracing state changes extremely difficult.

## 9. Orchestration (`orchestration/mode_controller.py`)
* **Unified Pipeline:** Successfully aggregates the 4 main engines for Backtest, Paper, and Live modes.
* **Hidden Feedback Loop:** It explicitly calls `update_edge_weights_from_latest_trades()` after every PAPER and LIVE run. This means the system is silently mutating its own configuration state (`edge_weights.json`) behind the scenes based on recent performance.
* **Brittle Live Feed:** Includes a `CachedCSVLiveFeed` class that literally polls CSV files constantly to simulate live trading, which is highly unstable.

## 10. Research & Discovery (`engines/engine_d_research/`)
* **The "Hunter":** `discovery.py` uses a `DecisionTreeScanner` to crunch a massive joined DataFrame of all tickers to find universal technical/fundamental patterns, then spins up a mini-Backtester to validate them.
* **Ghost Isolation:** This entire module runs in total isolation (via `run_autonomous_cycle.py`) and only interacts with the core engines by mutating config files (`edges.yml`, `rf_model.pkl`).

## 11. System Governor (`engines/engine_d_research/governor.py` & `system_governor.py`)
* **Dynamic Reweighting:** `governor.py` computes rolling Sharpe, Drawdowns, and correlations from recent trade logs. It applies a "kill-switch" if MDD hits -25%, and applies penalties for highly correlated edges.
* **The Daemon Engine:** `system_governor.py` acts as a file-watching daemon. It polls the `trade_logs` directory and automatically re-writes `data/governor/edge_weights.json` and `system_state.json`.

## 12. Core Simulator (`backtester/backtest_controller.py`)
* **The Monolith (1073 lines):** Orchestrates the `Alpha -> Risk -> Portfolio` loop historically by creating slow `slice_map` views of the data for every single bar. 
* **Bagholder/Data Gap Patches:** Contains explicit inline patches (lines 390-500) to detect data gaps and manually inject "Zero/Panic" signals if an asset stops trading.
* **AI Signal Gating:** It intercepts signals emitted by `AlphaEngine` and runs them through a `SignalGate` AI model to block "bad" signals.

## 13. User Intent & Architectural Vision (From Archived Transcripts)
By mining `docs/Archive/Other/chat_transcripts/`, the overarching goal of the system becomes explicit:
* **Definition of an "Edge":** The user views an edge not just as a technical indicator, but across 6 categories: Technical (RSI, breakouts), Fundamental, News-based, Stat/Quant (seasonality), Behavioral/Psychological, and "Grey" (e.g., congressional trades, non-public hacks). A **"True Edge"** is a combination of these.
* **The "Intelligent Portfolio" Mandate:** The user explicitly states: *"We want to have a machine that acts somewhat similar to an investment banker/automated financial advisor... almost like Schwab Intelligent Portfolio but much better."* It must be able to create a diverse portfolio, allocate risk across sectors, mix short-term trading with buy-and-hold investing, and act like a *"real fund manager."*
* **The Core Problem Identified by the User:** *"Right now we aren't even acting like a hypothetical portfolio... our machine barely is working."* The user rightfully notes that before we can have a *"top tier software professional finding new edges,"* we must *"grow the bones of this thing that at least would hypothetically work."*

## 14. Active Intelligence & Research (The ML Loop)
* **Intelligence (`intelligence/`):** Contains `news_collector.py`, a robust web scraper that pulls RSS feeds, computes VADER sentiment scores, limits by ticker, and saves "intel" snapshots. It fulfills the user's mandate for "News/Event-Driven" edges.
* **Research (`research/`):** The `edge_harness.py` script is a massive 800+ line parameter sweeper. It runs walk-forward backtests across different market regimes (Bull/Bear/High Vol/Low Vol) and automatically promotes the best parameters to `config/edge_config.json`.
* **Live Trader (`live_trader/` & `core/`):** Mostly barren stubs. The transition from Paper to Live remains unbuilt, further proving the user's point that the core "bones" need solidifying before focusing entirely on ML.

## 15. Root Utilities & Diagnostic Stragglers (`debug/`, `.agent/`, Root Scripts)
After a comprehensive root-directory scan, the following unsorted utilities were mapped:
* **`.agent/rules.md` (Golden Invariants):** Establishes strict architectural rules for AI edits, mandating that `equity` absolutely must equal `cash + market_value`, and pure functional edges.
* **`debug/`:** A scratchpad directory containing 16 standalone diagnostic scripts (e.g., `test_alpaca_live.py`, `verify_momentum.py`). Highly disjointed but useful for isolating API connection issues.
* **Root Utility Scripts:**
  * `clean_data.py`: A nuclear wipe script that resets all CSV logs and JSON governor states back to empty headers/dictionaries.
  * `debug_config.py`: A centralized environment toggle for console verbosity across all engines.
  * `seed_governor_data.py`: Injects synthetic weights into the `data/governor/` JSON files for offline UI testing.
  * `reproduce_fundamentals.py`: A unit test checking if Yahoo Finance fundamental scraping is working properly.

## 16. Runtime Execution & Test Coverage (Phase 5)
By executing the system's test suite (`pytest -v tests/`), we exposed severe runtime architectural disconnects:
* **The "Fake" Passes:** 12 tests technically "PASSED", but files like `test_portfolio.py` and `test_backtest_controller.py` are empty 39-byte stubs containing only a `def test_placeholder(): pass`. This creates a false sense of security.
* **The Golden Path Failure:** `test_golden_path.py::test_bagholder_and_vanity_bugs` explicitly FAILED with an `AssertionError: Bug not reproduced!`. The explicit accounting bugs the system was designed to handle are currently not triggering or not being mitigated correctly.
* **Edge Engine Crashes:** All primary edges (`RSIBounceEdge`, `ATRBreakoutEdge`, `BollingerReversionEdge`) crashed with a `TypeError: float() argument must be a string or a real number, not 'Series'`. This proves that the data structures output by `DataManager` (which now pull MultiIndex/Series from `yfinance`) are completely incompatible with Engine A's math. The core signal generation pipeline is currently severed.
* **Diagnostics False Positives:** Running `python -m scripts.run_diagnostics` outputs a reassuring "Overall system health: 99.8%". However, reading the trace output reveals it achieves this by passing `Mock Alpha Logic`, completely bypassing the fatal math crashes in the real Edge code.
* **ML Hunter Unrunnable:** Executing the autonomous loop (`python scripts/run_shadow_paper.py`) instantly crashes with `ModuleNotFoundError: No module named 'ta'`. The ML environment dependencies (`requirements.txt`) were not kept in sync with the new `feature_engineering.py` module, rendering Phase 2 research entirely unbootable to a fresh clone.

## 17. Repository Cleanup & Bloat (Phase 6)
A massive full-repository scan revealed significant structural bloat acting as technical debt and confusing the AI context context windows:
* **Legacy UI:** `cockpit/dashboard/` still exists despite `docs/Core/agent_instructions.md` explicitly defining it as obsolete. Active dev is in `dashboard_v2`.
* **Massive Docs Dumps:** `docs/Core/extensive_files.md` is a 382,000-byte raw concatenated code dump. This provides zero structural intelligence and massively bloats the context window.
* **Script Graveyard:** `scripts/` contains over 30 files, many of which are dead proof-of-concept scripts (`poc_fundamentals.py`) or literal placeholder warnings (`optimize_stub.py`). 
* **Archival Bloat:** `docs/Archive/` contains 44 historical markdown files. While git-ignored, they clutter the root directory tree.

## 18. Detailed Legacy UI Analysis (`cockpit/dashboard/`)
* **`dashboard.py` (110KB+ Monolith):** A massive, 2,400+ line Dash application. It contains built-in data managers, Alpaca WebSocket streaming classes, and complex FIFO PnL matchers nested directly inside the UI code. 
* **User Intent Confirmation:** The user mapped this as legacy but kept it, likely because it contains valuable logic for calculating KPI cards, rendering PnL decompositions, and polling Alpaca. However, it violates separation of concerns by containing backend data processing logic. With `dashboard_v2` actively taking over, this folder is a prime candidate for archival once its core logic is safely ported or deemed redundant.

## 19. Detailed Script Graveyard Analysis (`scripts/`)
We exhaustively mapped all 30 files in the `scripts/` directory to categorize them for eventual cleanup or archival. The folder is a chaotic mix of vital orchestrators and literal dead code:
* **The "One-Button" Orchestrators:** 
  * `run_autonomous_cycle.py`: The single-button master loop for ML (Update > Discover > WFO > Harvest > Shadow).
  * `run_evolution_cycle.py` & `optimize.py`: Darwinian testing loops promoting or killing candidate edges based on out-of-sample consistency.
* **Core Execution Wrappers:** 
  * `run.py`: A simple wrapper for `ModeController`.
  * `run_backtest.py`: The explicit CLI entry point for the classical 4-Engine backtester.
  * `run_paper_loop.py` & `start_stack.py`: Scripts to spin up local background processes for paper trading and the UI.
* **Redundant Data Fetchers:** 
  * `fetch_all.py`, `fetch_data.py`, `update_data.py`: Three separate scripts that all basically interface with Alpaca or `DataManager` to download OHLCV CSVs. They should be consolidated.
* **ML Training & Harvesting:** 
  * `harvest_data.py`: Runs a backtest to extract technical features vs PnL outcomes for ML targets.
  * `train_gate.py` & `train_signal_gate.py`: Two redundant scripts taking that harvested data to train the `SignalGate` RandomForest model.
* **Validation & Diagnostics:** 
  * `run_diagnostics.py` & `run_healthcheck.py`: Two separate health check scripts. `diagnostics` gives a false 99.8% positive, while `healthcheck` actually checks core math invariants (Equity == Cash + Market Value).
  * `audit_data_gaps.py`: Scans data CSVs for >20% gaps and attempts repairs (clipping).
  * `validate_active_edges.py`, `validate_complementary_discovery.py`, `validate_phase2_math.py`: Hardcoded test scripts that run synthetic data loops to verify logic math.
  * `system_validity_check.py`: Tests Regime, Portfolio Parrondo Policy, and Governor correlation logic. 
* **Literal Graveyard / Dead Code:** 
  * `optimize_stub.py`: An empty placeholder.
  * `poc_fundamentals.py` & `show_fundamentals.py`: Pointless legacy proof-of-concept scrapes of Yahoo Finance.
  * `prune_strategies.py`: A utility script called "The Reaper" designed to delete Python files of strategies that failed ML tests.

---

### Conclusion & Primary Weak Points (The Hitlist)
1. **The God Engine Problem:** `alpha_engine.py`, `risk_engine.py`, `backtest_controller.py`, and `data_manager.py` are massive, intertwined classes that violate single-responsibility principles. The risk engine directly mutates portfolio state.
2. **Brittle Data Feeds:** "Live" mode reading from CSVs via a polling loop is dangerous and unscalable. Parquet/DB is mandatory.
3. **The "Two Universes":** The ML hunting loop operates completely outside the 4-engine architecture, passing "knowledge" only via JSON/Pickle files. Lookahead bias in the ML loop won't be caught by the standard pipelines.
4. **Testing Black Hole:** Core pipeline logic has 0 test coverage (empty 39-byte files), yet complex ML loops are running on top of it.
5. **Slow Simulation:** `BacktestController`'s reliance on slicing pandas DataFrames bar-by-bar is inherently slow and unscalable for high-frequency or multi-asset tests.
6. **Misaligned Priorities:** As the user noted in transcripts, the system rushed to build an autonomous ML "Hunter" loop before the core trading "bones" (the Portfolio/Risk engines acting as a real Fund Manager) were solid and tested.
