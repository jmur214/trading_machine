# ==========================================================
# Trading Machine — MAN PAGE (Developer Command Reference)
# ==========================================================

# --- ENVIRONMENT SETUP ------------------------------------
python3 -m venv .venv
source .venv/bin/activate            # macOS / Linux
# .venv\Scripts\activate             # Windows
pip install -r requirements.txt

# --- CORE SYSTEM COMMANDS ---------------------------------

# Run full backtest (Alpha → Risk → OMS → Portfolio → Governor)
python -m scripts.run_backtest

# Run AlphaEngine signal generation only (diagnostic)
python -m scripts.run_backtest --mode alpha --debug

# Launch Cockpit dashboard (Backtest mode)
python -m cockpit.dashboard
python cockpit_dashboard_v2.py

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


# --- DATA & MARKET INTELLIGENCE -----------------------------

# Fetch normalized OHLCV data (via Alpaca or Yahoo fallback)
python -m scripts.fetch_data --tickers AAPL MSFT SPY \
  --start 2022-01-01 --end 2025-01-01 --timeframe 1d

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
python -m scripts.continuous_validation --debug


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