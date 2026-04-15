# Trading Machine Execution Manual

> **AI Agent Notice:** Use the commands below as your absolute reference for interacting with the Trading Machine. Never guess arbitrary python scripts or pathways. If you are tasked with a specific operation, search this manual for the exact execution syntax. When using the command line, you must track what works, what fails, and what it does in your reasoning. If you utilize or create a NEW command that is not in this document, you MUST immediately add it here.

---

### AUTONOMOUS MODE (THE "ONE BUTTON")
Runs the full cycle: Data -> Hunt -> Navigate -> Trade
```bash
python scripts/run_autonomous_cycle.py
# Run in infinite loop (Master Controller)
python scripts/run_autonomous_cycle.py --loop
```

### ENVIRONMENT SETUP
```bash
python3 -m venv .venv
source .venv/bin/activate            # macOS / Linux
# .venv\Scripts\activate             # Windows
pip install -r requirements.txt
deactivate                           # Environment Management
```

### SYSTEM HEALTH & DIAGNOSTICS
```bash
# Run full system health diagnostics (edges, backtest, governor, trades)
python -m scripts.run_diagnostics

# Run diagnostics in sandbox mode (isolated governor updates)
python -m scripts.run_diagnostics --mode sandbox

# Run edge feedback update in sandbox mode (safe learning)
python -m analytics.edge_feedback --mode sandbox

# Verify recency-decay weighting behavior
python -m analytics.edge_feedback --mode sandbox --debug

# Run unified health check (pytest + backtest + invariant checks)
python -m scripts.run_healthcheck
python -m scripts.run_healthcheck --skip-tests    # Skip pytest, run backtest only
python -m scripts.run_healthcheck --skip-backtest  # Skip backtest, run pytest only
```

### CORE SYSTEM COMMANDS
```bash
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

# Run Governor weight update from latest results
python -m analytics.edge_feedback
python -m analytics.edge_feedback --history     # show weight history
```

### RESEARCH & EDGE HARNESS
```bash
# Run parameter sweep / walk-forward for a single edge
python -m research.edge_harness \
  --edge <EDGE_NAME> \
  --param-grid config/grids/<EDGE>.json \
  --walk-forward "YYYY-MM-DD:YYYY-MM-DD" \
  --backtest-config config/backtest_settings.json \
  --risk-config config/risk_settings.json

# Run edge evaluator (rank edges by time-decay composite score)
python -m scripts.run_evaluator

# Clear old research results
rm -rf data/research/*
```

### EVOLUTION & OPTIMIZATION (DARWIN)
```bash
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
```

### PHASE 2: RESEARCH & SHADOW TRADING
```bash
# Run the Shadow Loop (Hunter + Gatherer)
# - Discovers new 'Hunter' rules using Decision Trees.
# - Validates candidates in a Shadow Broker simulation.
# - Requires NO risk; uses 'Ghost Money'.
python scripts/run_shadow_paper.py
```

### DATA & MARKET INTELLIGENCE
```bash
# Update ALL Data (Intraday + Fundamentals)
# Reads tickers from config/universe.json
python scripts/update_data.py

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
```

### ANALYTICS & PERFORMANCE
```bash
# View research and backtest outputs
cat data/trade_logs/trades.csv
cat data/trade_logs/portfolio_snapshots.csv
cat data/governor/edge_weights.json

# View Parquet research results (binary format, requires Python)
python -c "import pandas as pd; print(pd.read_parquet('data/research/edge_results.parquet'))"
```

### DEBUGGING & DIAGNOSTICS
```bash
# The 'debug/' folder contains ad-hoc verification scripts
# Verify Assets API (Alpaca)
python debug/verify_assets_api.py

# Run full system diagnostics
python -m scripts.run_diagnostics
```

### PYTEST QUICK REFERENCE
```bash
# Run all system tests (full regression)
pytest -v

# Run specific subsystem tests
pytest -v tests/test_edge_outputs_extended.py        # Edge output format
pytest -v tests/test_collector_integration.py        # SignalCollector
pytest -v tests/test_alpha_pipeline.py               # AlphaEngine pipeline
pytest -v tests/test_portfolio.py                    # Portfolio accounting
pytest -v tests/test_backtest_controller.py          # Backtest orchestration
pytest -v tests/test_golden_path.py                  # Edge cases (data gaps, crashes)

# Typical Usage:
#   After editing an edge → test_edge_outputs_extended.py
#   After modifying pipeline logic → test_alpha_pipeline.py
#   Before committing code → pytest -v
```

### UTILITY & CLEANUP
```bash
# Backup and start fresh backtest
python -m scripts.run_backtest --fresh

# Clean generated files
rm -rf data/trade_logs/*
rm -rf data/research/*
rm -rf data/governor/*
```

---

### DEPRECATED COMMANDS
> These commands reference modules or paths that no longer exist or have been replaced. Kept for historical reference.

```bash
# V1 Dashboard (replaced by dashboard_v2)
python -m cockpit.dashboard --live

# continuous_validation (replaced by run_healthcheck)
python -m scripts.continuous_validation
python -m scripts.continuous_validation --once
python -m scripts.continuous_validation --interval 30
python -m scripts.continuous_validation --no-tests
python -m scripts.continuous_validation --debug

# DuckDB datastore (never implemented)
python -m datastore.inspect --path data/trading.duckdb
python -m datastore.migrate --mirror-csv true
duckdb data/trading.duckdb "SELECT run_id, mode, started_at FROM runs;"

# edge_db_viewer (use run_evaluator instead)
python -m research.edge_db_viewer

# performance_summary module (metrics computed inline by backtest)
python -m analytics.performance_summary

# Parquet files are binary (use Python to read, not cat)
cat data/research/edge_results.parquet

# File logging (system uses print(), no log files)
tail -f data/logs/latest.log
grep ALPHA data/logs/latest.log | tail
```
