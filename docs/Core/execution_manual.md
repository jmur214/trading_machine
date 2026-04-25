# Trading Machine Execution Manual

> **AI Agent Notice:** Use the commands below as your absolute reference for interacting with the Trading Machine. Never guess arbitrary python scripts or pathways. If you are tasked with a specific operation, search this manual for the exact execution syntax. When using the command line, you must track what works, what fails, and what it does in your reasoning. If you utilize or create a NEW command that is not in this document, you MUST immediately add it here.

---

### RUNTIME FLAGS (`run_backtest.py` and related scripts)

Two orthogonal axes control which configs and which state files a run uses. They are independent — choose each based on what you're doing.

**`--env {dev, prod}`** — selects which *config file* pair to load. Parsed in `ModeController.__init__` ([mode_controller.py:522, 551](orchestration/mode_controller.py#L522)).

| env | Alpha config | Risk config | Purpose |
|-----|--------------|-------------|---------|
| `dev` | `alpha_settings.dev.json` | `risk_settings.dev.json` | Debug on, loose thresholds (enter=0.10, exit=0.03), only `rsi_mean_reversion` + `xsec_meanrev` weighted. Use for quick iteration. |
| `prod` | `alpha_settings.prod.json` | `risk_settings.prod.json` | Debug off, tight thresholds (enter=0.01, exit=0.005), full edge roster with curated weights. This is the canonical settings. |

Default: `prod`. Use `--env dev` for rapid parameter experiments without editing the prod config.

**`--mode {sandbox, prod}`** — selects where *Governor state* is read from and written to. Parsed in `ModeController.run_backtest()` ([mode_controller.py:772-774](orchestration/mode_controller.py#L772-L774)).

| mode | Governor state path | Purpose |
|------|---------------------|---------|
| `prod` | `data/governor/edge_weights.json` + `regime_edge_performance.json` | Main learned state. Every run reads from and writes to these files. |
| `sandbox` | `data/governor/sandbox/edge_weights.json` + `regime_edge_performance.json` | Isolated scratch state. Use to test changes without contaminating main governor memory. |

Default: `prod`. Use `--mode sandbox` when you want to run backtests that should not update the main governor's learned weights.

**`--no-governor`** — skips the post-run `governor.update_from_trades()` + `save_weights()` call entirely ([mode_controller.py:838-840](orchestration/mode_controller.py#L838-L840)). The backtest still *reads* current governor state at startup, but does not write. Use for deterministic A/B tests where you want identical state between runs.

**Note on combining flags:** `--env` and `--mode` are independent. Typical combinations:
- `--env prod --mode prod` (default): real backtest that updates learned state.
- `--env prod --mode sandbox`: test a code change against prod configs without polluting main governor.
- `--env dev --mode sandbox`: quick iteration on debug configs in isolated state.

### DETERMINISTIC A/B TESTING

Backtests are *not* naturally deterministic across runs because every run that doesn't pass `--no-governor` writes `data/governor/edge_weights.json` and `regime_edge_performance.json`. Run 2 then reads post-run-1 state and produces different results — not because the code is non-deterministic, but because its inputs are.

To get reproducible results for A/B comparisons:

```bash
# 1. Create an anchor snapshot of governor state (one-time)
cp data/governor/regime_edge_performance.json data/governor/regime_edge_performance.json.anchor
cp data/governor/edge_weights.json data/governor/edge_weights.json.anchor

# 2. Before each test run, restore the anchor
cp data/governor/regime_edge_performance.json.anchor data/governor/regime_edge_performance.json
cp data/governor/edge_weights.json.anchor data/governor/edge_weights.json

# 3. Run with --no-governor so the run does not mutate the anchor for the next test
python -m scripts.run_backtest --no-governor

# 4. Verify determinism across two runs
md5 data/trade_logs/trades.csv      # run 1 md5
# (restore anchor, run again)
md5 data/trade_logs/trades.csv      # should match run 1
```

`scripts/run_deterministic.py` (wrapper that handles anchor save/restore + md5 comparison) is the preferred entry point for this workflow.

**Determinism also requires `PYTHONHASHSEED=0`** — Python 3 randomizes string hashing per-process by default, which makes `set()` iteration order differ across invocations. `run_deterministic.py` sets this automatically via a self-reexec guard at the top of the module; no manual action needed. When running `scripts/run_backtest` directly for A/B comparisons, prefix with `PYTHONHASHSEED=0 python -m scripts.run_backtest --no-governor`.

### WALK-FORWARD VALIDATION (regime-conditional governor)

Any regime-conditional mechanism (governor-per-regime weights, per-edge kill-switches conditioned on regime stats) must pass walk-forward before re-enabling. In-sample A/B (anchor trained and evaluated on the same window) hides overfitting — we saw this on 2026-04-23 where an in-sample Sharpe penalty of -0.15 revealed itself as -0.50 under walk-forward, decisively falsifying the per-edge-per-regime kill mechanism.

```bash
# Run the walk-forward harness: train regime_tracker on 2021-2022, evaluate
# 2023-2024 under three policy variants (baseline / hard-kill / soft-kill).
# Backs up config + governor state, auto-restores on exit.
PYTHONHASHSEED=0 python -m scripts.walk_forward_regime
```

Output: a 3-row report with OOS Sharpe, CAGR, MDD, WR per variant. Acceptance for re-enabling any regime-conditional feature: **OOS Sharpe of the activated variant ≥ OOS baseline Sharpe.** Anything below is a no-go regardless of in-sample result.

Date windows are hardcoded in the script (TRAIN_START/END, EVAL_START/END); edit those constants to test other splits.

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
# FULL DISCOVERY CYCLE (Recommended — post-backtest)
# Runs: regime detection → feature hunt (LightGBM+DTree) → GA evolution →
#       4-gate validation (backtest → PBO → WFO → significance) → auto-promote
python -m scripts.run_backtest --discover
python -m scripts.run_backtest --fresh --discover    # with fresh logs

# GENERATE CANDIDATES ONLY (no validation)
# Creates template mutations + GA-evolved composite genomes
python -m engines.engine_d_discovery.discovery

# VALIDATE CANDIDATES (Evolutionary Selector)
# Runs walk-forward optimization on 'candidate' edges.
# Promotes winners to 'active' status.
python -m scripts.optimize

# ML DATA HARVEST (Experimental)
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
# PERFORMANCE BENCHMARK (full scorecard)
# Runs a standardized backtest and outputs:
#   Portfolio metrics (Sharpe, Sortino, Calmar, CAGR, MDD, profit factor)
#   Per-edge breakdown (PnL, win rate, trade count)
#   SPY buy-and-hold comparison (alpha measurement)
python -m scripts.run_benchmark
python -m scripts.run_benchmark --start 2023-01-01 --end 2024-12-31
python -m scripts.run_benchmark --capital 50000
python -m scripts.run_benchmark --json     # JSON output only
# Report saved to: data/research/benchmark_report.json

# View research and backtest outputs
cat data/trade_logs/trades.csv
cat data/trade_logs/portfolio_snapshots.csv
cat data/governor/edge_weights.json

# View Parquet research results (binary format, requires Python)
python -c "import pandas as pd; print(pd.read_parquet('data/research/edge_results.parquet'))"
```

### MACRO DATA (FRED)
```bash
# The FRED macro pipeline lives at engines/data_manager/macro_data.py.
# It is a library — no CLI script. Cache in data/macro/<SERIES_ID>.parquet.
# Requires FRED_API_KEY in .env (free key: https://fredaccount.stlouisfed.org/apikeys).
# Without a key the manager runs in cache-only mode.

# Bootstrap / refresh the curated panel from a Python shell:
python -c "from engines.data_manager.macro_data import MacroDataManager; \
mgr = MacroDataManager(); panel = mgr.fetch_panel(); \
print(panel.tail()); print(mgr.cache_status())"

# Refresh a single series:
python -c "from engines.data_manager.macro_data import MacroDataManager; \
print(MacroDataManager().fetch_series('DGS10', force=True).tail())"

# Inspect the on-disk cache state without hitting the network:
python -c "from engines.data_manager.macro_data import MacroDataManager; \
print(MacroDataManager(api_key=None).cache_status().to_string())"
```

### EARNINGS DATA (FINNHUB)
```bash
# The Finnhub earnings pipeline lives at engines/data_manager/earnings_data.py.
# It is a library — no CLI script. Cache in data/earnings/<SYMBOL>_calendar.parquet.
# Requires FINNHUB_API_KEY in .env (free key: https://finnhub.io/register).
# Without a key the manager runs in cache-only mode.
# Free tier ceiling is 60 req/min — manager rate-limits to 1.1s/call by default.

# Bootstrap the cache for a universe (loops with rate limiting):
python -c "from engines.data_manager.earnings_data import EarningsDataManager; \
mgr = EarningsDataManager(); df = mgr.fetch_universe(['AAPL','MSFT','NVDA']); \
print(df.tail()); print(mgr.cache_status())"

# Refresh a single symbol (force-bypass the 24h freshness window):
python -c "from engines.data_manager.earnings_data import EarningsDataManager; \
print(EarningsDataManager().fetch_calendar('AAPL', force=True).tail())"

# Inspect the on-disk cache state without hitting the network:
python -c "from engines.data_manager.earnings_data import EarningsDataManager; \
print(EarningsDataManager(api_key=None).cache_status().to_string())"
```

### UNIVERSE MEMBERSHIP (S&P 500 historical)
```bash
# The membership loader lives at engines/data_manager/universe.py.
# Source: Wikipedia "List of S&P 500 companies". No API key required.
# Cache at data/universe/sp500_membership.parquet (refresh window: 7 days).

# Refresh the cached membership history (one network call):
python -c "from engines.data_manager.universe import SP500MembershipLoader; \
loader = SP500MembershipLoader(); df = loader.fetch_membership(force=True); \
print(loader.cache_status()); print('current:', len(loader.current_constituents()))"

# Survivorship-bias-aware snapshot for an arbitrary historical date:
python -c "from engines.data_manager.universe import SP500MembershipLoader; \
print(SP500MembershipLoader().historical_constituents('2018-01-01')[:10])"

# Inspect the cache state without hitting the network:
python -c "from engines.data_manager.universe import SP500MembershipLoader; \
print(SP500MembershipLoader().cache_status())"
```

The companion CLI `scripts/fetch_universe.py` uses the membership list
to populate `data/processed/` (OHLCV bars) via the existing
`DataManager` pipeline. It is **explicit user action only** — running
it for the full historical universe is a 30-60 minute job that hits
Alpaca's rate limit, so it is never invoked by tests, hooks, or
backtests.

```bash
# Preview which tickers would be fetched without touching the API:
python -m scripts.fetch_universe --source sp500_historical --dry-run

# Fetch only today's S&P 500 constituents:
python -m scripts.fetch_universe --source sp500_current --start 2018-01-01

# Fetch the full historical union (every ticker that's ever been in the index)
# — recommended for survivorship-bias-aware backtests:
python -m scripts.fetch_universe --source sp500_historical --start 2018-01-01

# Fetch from a custom newline-separated ticker file:
python -m scripts.fetch_universe --source file --file my_tickers.txt

# Cap the number of fetches per run (useful for incremental backfills):
python -m scripts.fetch_universe --source sp500_historical --max-tickers 50

# Re-fetch tickers that already have a cached parquet (forces refresh):
python -m scripts.fetch_universe --source sp500_current --refresh
```

Idempotent by default: tickers whose
`data/processed/parquet/<TICKER>_<TF>.parquet` already exists are
skipped. The script exits with code 0 on full success, 1 if any
ticker failed to fetch, 2 if Alpaca credentials are missing for a
non-empty fetch list.

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
