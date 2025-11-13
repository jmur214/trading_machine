```bash

# ===============================
# Trading Machine — Command Guide
# ===============================

# --- Environment Setup ---
python3 -m venv .venv
source .venv/bin/activate      # macOS / Linux
# .venv\Scripts\activate       # Windows

pip install -r requirements.txt

# --- Core Operations ---

# Run full backtest (Alpha → Risk → Portfolio → Cockpit)
python -m scripts.run_backtest

# Launch dashboard (standard mode)
python -m scripts.run

# Launch dashboard in live mode (placeholder / future integration)
python -m cockpit.dashboard --live


# --- Edge Research Harness ---

python -m research.edge_harness \
  --edge <edge_name> \
  --param-grid <json_or_path> \
  --walk-forward "YYYY-MM-DD:YYYY-MM-DD[,YYYY-MM-DD:YYYY-MM-DD,...]" \
  [--backtest-config config/backtest_settings.json] \
  [--risk-config config/risk_settings.json] \
  [--edge-config-template config/edge_config.json] \
  [--out data/research] \
  [--slippage-bps 10.0] \
  [--commission 0.0]


# --- Market Intelligence / Research ---

# Collect latest financial + macro news headlines
python -m intelligence.news_collector

# Summarize latest snapshot into a structured market brief
python -m intelligence.news_summarizer


# --- Research Database Management ---

# Inspect global research database
python -m research.edge_db_viewer

# Remove / reset corrupted global edge results DB
rm data/research/edge_results.parquet


# --- Optional Utilities ---

# Inspect trade logs or snapshots
cat data/trade_logs/trades.csv
cat data/trade_logs/portfolio_snapshots.csv

# Inspect research results
cat data/research/<edge_name>_<timestamp>/results.csv

# Read Parquet results in Python REPL
python
>>> import pandas as pd
>>> df = pd.read_parquet("data/research/edge_results.parquet")
>>> print(df.head())


# --- Environment Management ---
deactivate                      # Exit virtual environment