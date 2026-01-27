# ==========================================================
# Trading Machine — MAN PAGE
## Key Features
*   **Deep Value**: P/E < 5, High Volume, Oversold RSI.
*   **Momentum**: Cross-Sectional Momentum (Winners keep winning).
*   **News Sentiment (Macro)**: Analyze headlines for Geopolitical, Monetary, and Economic Systemic Risks using `config/macro_impact.json`.
*   **Fundamental Ratios**: Sales Growth, PEG validation.

## Developer Command Reference
# ==========================================================

# --- ENVIRONMENT SETUP ------------------------------------
python3 -m venv .venv
source .venv/bin/activate            # macOS / Linux
# .venv\Scripts\activate             # Windows
pip install -r requirements.txt

# --- SYSTEM HEALTH & DIAGNOSTICS ---------------------------

# Run full system health diagnostics (edges, backtest, governor, trades)
python -m scripts.run_diagnostics

# Run diagnostics in sandbox mode (isolated governor updates)
python -m scripts.run_diagnostics --mode sandbox

# Run edge feedback update in sandbox mode (safe learning)
python -m analytics.edge_feedback --mode sandbox

# Verify recency-decay weighting behavior
python -m analytics.edge_feedback --mode sandbox --debug


# Run continuous validation (periodic system health monitoring)
python -m scripts.continuous_validation

# Run once and exit
python -m scripts.continuous_validation --once

# Set custom interval (minutes between runs)
python -m scripts.continuous_validation --interval 30

# Skip pytest checks for faster runs
python -m scripts.continuous_validation --no-tests

# Enable verbose debug output
python -m scripts.continuous_validation --debugt

# --- CORE SYSTEM COMMANDS ---------------------------------

# Run full backtest (Alpha → Risk → OMS → Portfolio → Governor)
python -m scripts.run_backtest

# Run with fresh logs (clears prior trades/snapshots)
python -m scripts.run_backtest --fresh

# Run AlphaEngine signal generation only (diagnostic)
python -m scripts.run_backtest --mode alpha --alpha-debug
python -m scripts.run_backtest --mode alpha --debug # (Legacy)

# Launch Cockpit dashboard V2 (Modern)
python -m cockpit.dashboard_v2.app
# Launch on custom port (default 8050)
python -m cockpit.dashboard_v2.app --port 8055

# Launch Cockpit dashboard in live/paper mode
python -m cockpit.dashboard --live

# Run Governor weight update from latest results
python -m analytics.edge_feedback
python -m analytics.edge_feedback --history     # show weight history


# --- RESEARCH & EDGE HARNESS -------------------------------

# Run parameter sweep / walk-forward for a single edge
python -m research.edge_harness \
  --edge <EDGE_NAME> \
  --param-grid config/grids/<EDGE>.json \
  --walk-forward "YYYY-MM-DD:YYYY-MM-DD" \
  --backtest-config config/backtest_settings.json \
  --risk-config config/risk_settings.json

# Inspect global edge research database
python -m research.edge_db_viewer

# Clear old research results
rm -rf data/research/*


# --- EVOLUTION & OPTIMIZATION (DARWIN) ---------------------

# 1. GENERATE CANDIDATES (Discovery Engine)
# Uses templates to actuate new edge variants into the registry.
python -m engines.engine_d_research.discovery

# 2. VALIDATE CANDIDATES (Evolutionary Selector)
# Runs walk-forward optimization on 'candidate' edges.
# Promotes winners to 'active' status.
python -m scripts.optimize

# 3. ML DATA HARVEST (Experimental)
# Collects trade signals and outcomes for ML training
python -m scripts.harvest_data


# --- DATA & MARKET INTELLIGENCE -----------------------------

# Fetch entire universe history (defined in config/backtest_settings.json)
python scripts/fetch_all.py

# Fetch specific normalized OHLCV data (via Alpaca or Yahoo fallback)
python scripts/fetch_data --tickers AAPL MSFT SPY \
  --start 2022-01-01 --end 2025-01-01 --timeframe 1d

# Verify DataManager integrity and source availability
python debug/verify_dm_integrity.py

# Collect and summarize latest financial news
python -m intelligence.news_collector
python -m intelligence.news_summarizer


# --- ANALYTICS & PERFORMANCE -------------------------------

# Analyze performance summary from latest run
python -m analytics.performance_summary

# View research and backtest outputs
cat data/trade_logs/trades.csv
cat data/trade_logs/portfolio_snapshots.csv
cat data/research/edge_results.parquet
cat data/governor/edge_weights.json


# --- DEBUGGING & DIAGNOSTICS -------------------------------

# The 'debug/' folder contains ad-hoc verification scripts
# moved from root to reduce clutter.

# Verify Assets API (Alpaca)
python debug/verify_assets_api.py

# Run full system diagnostics
python -m scripts.run_diagnostics


# --- PYTEST QUICK REFERENCE --------------------------------

# Run all system tests (full regression)
pytest -v

# Run specific subsystem tests
pytest -v tests/test_edge_outputs_extended.py        # Edge output format
pytest -v tests/test_collector_integration.py        # SignalCollector
pytest -v tests/test_alpha_pipeline.py               # AlphaEngine pipeline
pytest -v tests/test_portfolio.py                    # Portfolio accounting
pytest -v tests/test_backtest_controller.py          # Backtest orchestration
pytest -v tests/test_governor_feedback.py            # Governor feedback loop

# Typical Usage:
#   After editing an edge → test_edge_outputs_extended.py
#   After modifying pipeline logic → test_alpha_pipeline.py
#   Before committing code → pytest -v


# --- DATASTORE & MIGRATION COMMANDS ------------------------

# Initialize or inspect DuckDB data store
python -m datastore.inspect --path data/trading.duckdb
python -m datastore.migrate --mirror-csv true

# View active run registry
duckdb data/trading.duckdb "SELECT run_id, mode, started_at FROM runs;"


# --- UTILITY & CLEANUP -------------------------------------

# Backup and start fresh backtest
python -m scripts.run_backtest --fresh

# View logs in real time
tail -f data/logs/latest.log
grep ALPHA data/logs/latest.log | tail

# Clean generated files
rm -rf data/trade_logs/*
rm -rf data/research/*
rm -rf data/governor/*


# --- ENVIRONMENT MANAGEMENT -------------------------------
deactivate

## File Structure Reference

### `scripts/`
*   `analyze_edges.py`: Analyzes edge performance and generates insights.
*   `audit_data_gaps.py`: Checks for missing data in the historical dataset.
*   `continuous_validation.py`: Runs periodic validation checks to ensure system stability.
*   `evolve_loop.py`: Continuous evolutionary loop for strategy improvement.
*   `fetch_all.py`: Bulk data fetcher for the entire universe.
*   `fetch_data.py`: Targeted data fetcher for specific tickers/ranges.
*   `harvest_data.py`: Collects training data for ML models from backtest runs.
*   `optimize.py`: Optimizes parameters for specific strategies.
*   `poc_fundamentals.py`: Proof-of-concept for fundamental data integration.
*   `prune_strategies.py`: Removes failed/rejected strategy code and old trade logs to prevent disk bloat.
*   `run_backtest.py`: Orchestrates the full Alpha->Risk->Portfolio->Execution pipeline.
*   `run_diagnostics.py`: Checks health of all engines and data sources.
*   `run_evaluator.py`: Runs the evaluator engine to score strategies.
*   `run_healthcheck.py`: Quick "Heartbeat" check for system status.
*   `show_fundamentals.py`: Utility to display fundamental data for a ticker.
*   `system_validity_check.py`: Comprehensive integration test verifying Alpha logic, Regime gating, Portfolio rebalancing, and Correlation penalties.
*   `train_gate.py`: ML Gate training script.
*   `validate_candidates.py`: Validates newly discovered strategy candidates.
*   `validate_complementary_discovery.py`: Verifies Discovery Engine vocabulary (Regime, Rank, New Math).
*   `validate_phase2_math.py`: Logical check for advanced math indicators.
*   `walk_forward_validation.py`: Performs Walk-Forward Optimization to validate strategy robustness against overfitting.