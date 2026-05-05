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
| `engines/engine_f_governance/` | Governance — edge lifecycle management (`lifecycle_manager.py` — autonomous active ↔ paused → retired transitions, validated end-to-end 2026-04-25), weight updates, performance scoring, regime-conditional edge weighting (`regime_tracker.py` — runtime disabled 2026-04-23, walk-forward central tendency net-negative across 3 splits), allocation evaluation orchestration |
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
| `scripts/` | CLI tools — run_backtest, run_diagnostics, fetch_data, sync_docs, run_deterministic (pinned-state A/B harness), walk_forward_regime / walk_forward_affinity / walk_forward_risk_advisory / walk_forward_factor_edge (per-feature OOS validation harnesses), reset_base_edges (Phase ε demote tool, --confirm required) |
| `config/` | Configuration — universe definitions, edge configs, backtest settings |
| `core/` | Shared utilities and base classes — includes `metrics_engine.py` (MetricsEngine used by Discovery + Governance) and `benchmark.py` (LRU-cached SPY rolling Sharpe + benchmark-relative gate utility, used by Discovery validation and Governance lifecycle) |
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

The `docs/` tree is organized by **lifecycle**, not by topic. See `docs/README.md` for the canonical navigation index, and `docs/Core/SESSION_PROCEDURES.md` § "Documentation lifecycle" for the rules.

| Directory | Purpose |
|-----------|---------|
| `docs/README.md` | Canonical navigation index — "where do I find X" map across the whole `docs/` tree |
| `docs/Core/` | **Stable design** (rarely changes) — `SESSION_PROCEDURES.md`, `PROJECT_CONTEXT.md`, `engine_charters.md`, `simple_engine_roles.md`, `high_level_engine_function.md`, `execution_manual.md`, `roles.md`, `agent_instructions.md`, `files.md`, `MULTI_SESSION_ORCHESTRATION.md` |
| `docs/Core/Ideas_Pipeline/` | 3-stage idea promotion workflow (human → backlog → evaluations → ROADMAP) |
| `docs/Core/Human/` | Plain-English project explanations (3 audience levels) |
| `docs/State/` | **Current truth** (mutates in place, no date suffixes) — `health_check.md` (code-quality tracker), `forward_plan.md` (current strategy), `ROADMAP.md`, `GOAL.md`, `lessons_learned.md`, `deployment_boundary.md` |
| `docs/Measurements/<YYYY-MM>/` | **Point-in-time reports** (frozen, append-only) — backtests, ablations, audits, workstream close-outs. Bucketed by month. |
| `docs/Sessions/<YYYY-MM>/` | Per-session summaries (frozen). `_template.md` for new ones. `Other-dev-opinion/` (flat, not month-bucketed) for outside-reviewer pastes. |
| `docs/Archive/` | Explicitly retired — superseded forward plans, deprecated design docs, legacy meta-docs. Read for "what did we believe at time X", not for current truth. |
| `docs/Sources/` | External reference material (paper reviews, third-party analysis) |

## AI Configuration

| Directory | Purpose |
|-----------|---------|
| `.claude/agents/` | Subagent definitions (one `.md` per cognitive lens — `architect`, `code-health`, `edge-analyst`, `engine-auditor`, `ml-architect`, `quant-dev`, `regime-analyst`, `risk-ops-manager`, `ux-engineer`, `agent-architect`) |
| `.claude/skills/` | Reusable skills (e.g. `commit/SKILL.md` — commit-message format) |
| `.claude/settings.json` | Project hooks: SessionStart banner, Stop reminder, PostToolUse(Edit\|Write) → `sync_docs.py` for `engines/**/*.py`; permission boundaries |
| `CLAUDE.md` (repo root) | Operating constitution — non-negotiable rules, autonomy boundaries, git discipline |
| `docs/README.md` (canonical nav) | "Where do I find X" index — read this if you need to navigate any doc. The legacy `DOCUMENTATION_SYSTEM.md` describing the prior structure is at `docs/Archive/DOCUMENTATION_SYSTEM_legacy.md`. |
