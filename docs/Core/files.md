# Core File Index
This is a high-level, quick-reference guide to the primary directories of the Trading Machine. For deep, module-level details, see the `index.md` file inside each directory listed below.

## Engines (Core Trading Logic)

| Directory | Purpose |
|-----------|---------|
| `engines/engine_a_alpha/` | Alpha Generation — signal collection, edge evaluation, ensemble aggregation |
| `engines/engine_b_risk/` | Risk Management — ATR sizing, exposure caps, trailing stops, liquidity checks |
| `engines/engine_c_portfolio/` | Portfolio Management — accounting ledger, allocation policies, equity tracking, vol targeting, regime-adaptive allocation, autonomous allocation discovery (`allocation_evaluator.py`) |
| `engines/engine_d_discovery/` | Discovery & Evolution — two-stage ML scanning (LightGBM + DTree), GA evolution (selection/crossover/mutation), 4-gate validation (backtest/PBO/WFO/significance), 40+ feature engineering |
| `engines/engine_e_regime/` | Regime Intelligence — market state detection (trend, volatility), advisory policy hints |
| `engines/engine_f_governance/` | Governance — edge lifecycle management, weight updates, performance scoring, edge promotion, regime-conditional edge weighting (`regime_tracker.py` — runtime disabled 2026-04-23, walk-forward central tendency net-negative across 3 splits), allocation evaluation orchestration |
| `engines/data_manager/` | Data Pipeline — OHLCV ingestion (Alpaca), caching (Parquet/CSV), normalization |

## Orchestration & Execution

| Directory | Purpose |
|-----------|---------|
| `orchestration/` | Mode Controller — binds engines together for Backtest, Paper, or Live execution |
| `backtester/` | Simulation Loop — walk-forward backtesting, fill simulation, equity tracking |
| `live_trader/` | Live/Paper Execution — broker interface gateway for real-time order placement |
| `brokers/` | Broker Adapters — Alpaca broker connection (with future multi-broker extensibility) |

## Analytics & Intelligence

| Directory | Purpose |
|-----------|---------|
| `analytics/` | Post-trade feedback loops — edge performance analysis, Governor weight updates |
| `intelligence/` | Market Intel — news sentiment collection, macro environment analysis |
| `research/` | Edge Research — parameter sweeps, walk-forward optimization, edge discovery |

## UI & Visualization

| Directory | Purpose |
|-----------|---------|
| `cockpit/` | Shared cockpit infrastructure — `logger.py` (CockpitLogger for trade/snapshot CSV logging), `metrics.py` (PerformanceMetrics for post-run analysis) |
| `cockpit/dashboard_v2/` | **Active Dashboard** — Dash/Plotly web UI with tabs for analytics, governor, intel |
| `cockpit/dashboard/` | ⚠️ **Deprecated** — legacy V1 dashboard, do not use |

## Infrastructure & Utilities

| Directory | Purpose |
|-----------|---------|
| `debug_config.py` | **Root-level** — Global debug flag system (`DEBUG_LEVELS` dict) used by all engines for conditional logging |
| `scripts/` | CLI tools — run_backtest, run_diagnostics, fetch_data, sync_docs, run_deterministic (pinned-state A/B harness), walk_forward_regime (train-window / eval-window validation for regime-conditional governor) |
| `config/` | Configuration — universe definitions, edge configs, backtest settings |
| `core/` | Shared utilities and base classes — includes `metrics_engine.py` (MetricsEngine used by Discovery + Governance) |
| `utils/` | General-purpose helper functions |
| `storage/` | State persistence — system state management between runs |
| `tests/` | Test suite — edge output tests, pipeline tests, portfolio accounting tests |
| `debug/` | Ad-hoc diagnostic scripts — API verification, data manager checks |

## Data (Runtime, Not Tracked in Git)

| Directory | Purpose |
|-----------|---------|
| `data/trade_logs/` | Backtest/paper trade CSVs (trades, portfolio snapshots) |
| `data/governor/` | Edge weight JSON, `edges.yml` registry, `ga_population.yml` (GA state), `regime_edge_performance.json` (per-edge per-regime stats) |
| `data/research/` | Edge research results (Parquet), `discovery_log.jsonl` (discovery audit trail), `allocation_recommendations.json` (per-regime optimal allocation configs) |
| `data/intel/` | News snapshots and sentiment history |
| `data/processed/` | Cached OHLCV data files |

## Documentation

| Directory | Purpose |
|-----------|---------|
| `docs/Core/` | AI command center — GOAL, PROJECT_CONTEXT, ROADMAP, execution_manual, roles |
| `docs/Core/Ideas_Pipeline/` | 3-stage idea promotion workflow (human → backlog → evaluations → ROADMAP) |
| `docs/Audit/` | Technical audits, engine charters, codebase findings |
| `docs/Progress_Summaries/` | Lessons learned, timestamped phase completion summaries |
| `docs/Archive/` | Deprecated content — preserved for historical reference |
