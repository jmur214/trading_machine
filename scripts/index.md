# CLI Scripts Directory
**Purpose:** Command-line wrappers to invoke specific workflows or execute tests without burying the user in Python imports.
**Architectural Role:** The user-facing execution layer.

**Key Categories:**
- *One-Button Orchestrators:* `run_autonomous_cycle.py` (Full ML Loop).
- *Execution:* `run_backtest.py`, `run_paper_loop.py`.
- *Diagnostics:* `run_healthcheck.py` (true math test), `system_validity_check.py`.
- *Documentation:* `sync_docs.py` (AST markdown generator).

*Note: Over 10 legacy proof-of-concept scripts were purged to `Archive/scripts/` during the Phase 6 Code Audit. See `docs/Audit/codebase_findings.md` for historical mapping.*

<!-- AUTO-GENERATED: DO NOT EDIT BELOW -->

## Auto-Generated Code Reference

*This section is automatically built by `scripts/sync_docs.py`. Do not edit manually.*

### `analyze_edges.py`
*No public classes or functions found.*

### `analyze_oos_2025.py`
**Module Docstring:** scripts/analyze_oos_2025.py
- **Function `load_trades()`**: No docstring
- **Function `pivot_pnl()`**: No docstring
- **Function `pivot_fills()`**: No docstring
- **Function `regime_pnl_crosstab()`**: No docstring
- **Function `regime_fill_crosstab()`**: No docstring
- **Function `regime_by_month()`**: No docstring
- **Function `cumulative_top_bottom()`**: No docstring
- **Function `spy_monthly_return()`**: No docstring
- **Function `rivalry_probe()`**: No docstring
- **Function `main()`**: No docstring

### `audit_data_gaps.py`
- **Function `audit_file()`**: No docstring
- **Function `main()`**: No docstring

### `det_d1_repro.py`
**Module Docstring:** scripts/det_d1_repro.py
- **Function `md5()`**: No docstring
- **Function `hash_governor_state()`**: No docstring
- **Function `file_size()`**: No docstring
- **Function `gov_sizes()`**: No docstring
- **Function `find_run_id()`**: No docstring
- **Function `trades_canon_md5()`**: MD5 of trades.csv with run_id+meta columns dropped (mirrors
- **Function `run_one()`**: Single 2025 OOS Q1-style run with --reset-governor.
- **Function `main()`**: No docstring

### `det_d2_bisect.py`
**Module Docstring:** scripts/det_d2_bisect.py
- **Function `md5()`**: No docstring
- **Function `snapshot_drifted()`**: Capture the current live governor state as the 'drifted' anchor.
- **Function `restore_from_drifted()`**: Restore the four candidate files from the drifted snapshot.
- **Function `override_one_from_clean()`**: After restore_from_drifted(), copy `file_to_override` from CLEAN
- **Function `find_run_id()`**: No docstring
- **Function `trades_canon_md5()`**: No docstring
- **Function `run_one()`**: Single 2025 OOS Q1 run. Caller is responsible for governor-state
- **Function `main()`**: No docstring

### `diagnose_realistic_slippage.py`
**Module Docstring:** scripts/diagnose_realistic_slippage.py
- **Function `find_latest_trade_log()`**: Locate the most recently-written trades.csv under data/trade_logs/.
- **Function `load_bar_data()`**: Load the daily parquet for a ticker; None if missing.
- **Function `trailing_window()`**: Return up to n_days of bar data ending at-or-before `as_of` (no look-ahead).
- **Function `main()`**: No docstring

### `factor_decomposition_baseline.py`
**Module Docstring:** scripts/factor_decomposition_baseline.py
- **Function `find_latest_trade_log()`**: No docstring
- **Function `edge_daily_returns()`**: Group trades by edge_id and compute a daily return stream per edge.
- **Function `regress_edge_on_factors()`**: OLS: edge_excess_return ~ alpha + sum(beta_i * factor_i).
- **Function `write_report()`**: No docstring
- **Function `main()`**: No docstring

### `fetch_all.py`
- **Function `main()`**: No docstring

### `fetch_data.py`
- **Function `main()`**: No docstring

### `fetch_universe.py`
**Module Docstring:** scripts/fetch_universe.py
- **Class `FetchSummary`**: No docstring
  - `def report()`
- **Function `parse_args()`**: No docstring
- **Function `load_ticker_list()`**: Resolve --source into a deduped, sorted ticker list.
- **Function `split_cached_vs_missing()`**: Partition the universe into already-cached vs. missing tickers.
- **Function `credentials_available()`**: True if DataManager will be able to talk to Alpaca.
- **Function `fetch_one()`**: Fetch a single ticker and return (success, message).
- **Function `run()`**: No docstring
- **Function `main()`**: No docstring

### `gate1_reform_falsifiable_spec.py`
**Module Docstring:** Falsifiable-spec driver for the Phase 2.10e Gate 1 reform.
- **Function `main()`**: No docstring

### `harvest_data.py`
- **Function `harvest()`**: Run a simulation to collect (Features, Label) pairs for ML training.

### `optimize.py`
- **Function `main()`**: No docstring

### `path1_revalidation_grid.py`
**Module Docstring:** scripts/path1_revalidation_grid.py
- **Function `run_cell()`**: No docstring
- **Function `main()`**: No docstring

### `per_edge_per_year_attribution.py`
**Module Docstring:** Phase 2.10c diagnostic: per-edge per-year PnL attribution across the
- **Function `main()`**: No docstring

### `prune_strategies.py`
- **Class `StrategyPruner`**: The 'Reaper' of the Trading Machine.
  - `def __init__()`
  - `def prune()`
  - `def clean_logs()`: Removes old backtest log folders from data/trade_logs.

### `replay_fill_share_cap_2025.py`
**Module Docstring:** scripts/replay_fill_share_cap_2025.py
- **Function `main()`**: No docstring

### `reset_base_edges.py`
**Module Docstring:** scripts/reset_base_edges.py
- **Function `load_edges()`**: No docstring
- **Function `save_edges()`**: No docstring
- **Function `preview()`**: Return edge_ids that would be demoted.
- **Function `demote()`**: Mutate in place: active → candidate. Returns count.
- **Function `main()`**: No docstring

### `retrain_edges.py`
*No public classes or functions found.*

### `revalidate_alphas.py`
**Module Docstring:** Re-validate the two factor-decomp-identified real alphas
- **Function `main()`**: No docstring

### `run.py`
*No public classes or functions found.*

### `run_autonomous_cycle.py`
- **Function `is_market_open()`**: Simple check: Mon-Fri, 9:30 AM - 4:00 PM EST.
- **Function `run_cycle()`**: No docstring

### `run_backtest.py`
**Module Docstring:** scripts/run_backtest.py
- **Function `run_backtest_logic()`**: Backward-compatible programmatic entry point for running a backtest.
- **Function `main()`**: No docstring

### `run_benchmark.py`
**Module Docstring:** Performance Benchmark
- **Function `profit_factor()`**: Gross profit / gross loss.
- **Function `max_consecutive()`**: Longest streak of consecutive winning (or losing) trades.
- **Function `avg_trade_duration()`**: Average holding period in bars (approximate from trade timestamps).
- **Function `per_edge_metrics()`**: Compute per-edge performance from trade log.
- **Function `spy_benchmark()`**: Compute SPY buy-and-hold metrics over the same period.
- **Function `print_scorecard()`**: Print a formatted performance scorecard.
- **Function `run_benchmark()`**: Run benchmark and return full report dict.
- **Function `main()`**: No docstring

### `run_c2_walkforward.py`
**Module Docstring:** scripts/run_c2_walkforward.py
- **Function `find_run_id()`**: No docstring
- **Function `build_filtered_run()`**: Copy the source run's trades + snapshots, filter out test_year rows,
- **Function `retrain_metalearner()`**: Invoke train_metalearner.py on the filtered run. Returns the
- **Function `backtest_year()`**: Backtest single-year window with the currently-loaded metalearner.
- **Function `attach_benchmarks()`**: No docstring
- **Function `main()`**: No docstring

### `run_deterministic.py`
**Module Docstring:** scripts/run_deterministic.py
- **Function `md5()`**: No docstring
- **Function `canonical_md5()`**: MD5 of the CSV with per-run identifier columns (run_id, meta) excluded.
- **Function `save_anchor()`**: No docstring
- **Function `restore_anchor()`**: No docstring
- **Function `run_once()`**: No docstring
- **Function `main()`**: No docstring

### `run_diagnostics.py`
- **Function `run()`**: No docstring
- **Function `check_file()`**: No docstring

### `run_evaluator.py`
- **Function `main()`**: No docstring

### `run_evolution_cycle.py`
- **Class `AutonomousEvolution`**: The Master Learning Loop.
  - `def __init__()`
  - `def run_cycle()`

### `run_healthcheck.py`
**Module Docstring:** Trading Machine - Unified Healthcheck Script
- **Function `run_cmd()`**: Run a shell command, stream output, and return success boolean.
- **Function `run_pytests()`**: Run only the high‑signal tests that verify portfolio math + controller logic.
- **Function `run_dev_backtest()`**: Run the small/fast dev backtest. User may later customize flags.
- **Function `run_invariants()`**: Perform core snapshot/trade invariants.
- **Function `main()`**: No docstring

### `run_isolated.py`
**Module Docstring:** scripts/run_isolated.py
- **Function `save_anchor()`**: Snapshot `data/governor/<file>` for every name in ISOLATED_FILES.
- **Function `restore_anchor()`**: Restore the full set of governor files from the anchor.
- **Function `isolated()`**: Context manager: restore anchor on entry, restore again on exit.
- **Function `main()`**: No docstring

### `run_live.py`
*No public classes or functions found.*

### `run_oos_validation.py`
**Module Docstring:** scripts/run_oos_validation.py
- **Function `sample_universe_b()`**: Mirror engines/engine_d_discovery/discovery.py::_load_universe_b
- **Function `find_run_id()`**: No docstring
- **Function `run_q1()`**: 2025 OOS on prod universe. Same costs, shifted window, reset governor.
- **Function `run_q2()`**: Universe-B (50 held-out tickers, seed=42) on same in-sample window.
- **Function `attach_benchmarks()`**: Add SPY / QQQ / 60-40 metrics over the same window.
- **Function `main()`**: No docstring

### `run_paper_loop.py`
- **Function `main()`**: No docstring

### `run_path2_revalidation.py`
**Module Docstring:** scripts/run_path2_revalidation.py
- **Function `write_config()`**: Edit alpha_settings.prod.json in place: set metalearner.enabled
- **Function `find_run_id()`**: No docstring
- **Function `trades_canon_md5()`**: No docstring
- **Function `attach_benchmarks()`**: No docstring
- **Function `run_q2_under_harness()`**: Single Universe-B (q2) backtest under isolated() context.
- **Function `run_single_year_under_harness()`**: Single-year prod-109 backtest under isolated() context.
- **Function `cell_runs()`**: No docstring
- **Function `task_c1()`**: No docstring
- **Function `build_filtered_run()`**: No docstring
- **Function `retrain_metalearner_on_fold()`**: No docstring
- **Function `task_c2()`**: No docstring
- **Function `main()`**: No docstring

### `run_path2_ub.py`
**Module Docstring:** Path-2 Universe-B driver — runs Q2 with optional metalearner override.
- **Function `sample_universe_b()`**: No docstring
- **Function `find_run_id()`**: No docstring
- **Function `run_q2_with_metalearner()`**: No docstring
- **Function `attach_benchmarks()`**: No docstring
- **Function `main()`**: No docstring

### `run_per_ticker_oos.py`
**Module Docstring:** scripts/run_per_ticker_oos.py
- **Function `main()`**: No docstring

### `run_shadow_paper.py`
- **Function `load_candidates()`**: Load 'Candidate' edges from the registry.
- **Function `run_shadow_session()`**: No docstring

### `smoke_per_ticker_logger.py`
**Module Docstring:** scripts/smoke_per_ticker_logger.py
- **Function `main()`**: No docstring

### `start_stack.py`
- **Function `run_background()`**: No docstring
- **Function `main()`**: No docstring

### `sweep_cap_recalibration.py`
**Module Docstring:** scripts/sweep_cap_recalibration.py
- **Function `snapshot_lifecycle_state()`**: Copy lifecycle/governor files into _cap_recal_anchor/. Idempotent.
- **Function `restore_lifecycle_state()`**: Restore lifecycle/governor files from _cap_recal_anchor/.
- **Function `patched_configs()`**: Patch alpha_settings.prod.json + regime_settings.json with the
- **Function `find_run_id()`**: No docstring
- **Function `run_one()`**: Run a single 2025 Q1 OOS under the given preset.
- **Function `main()`**: No docstring

### `sync_docs.py`
- **Function `parse_file()`**: No docstring
- **Function `sync_directory()`**: No docstring

### `system_validity_check.py`
- **Function `run_system_check()`**: No docstring

### `train_gate.py`
- **Function `train_gate_model()`**: Train the SignalGate model using harvested data.

### `train_metalearner.py`
**Module Docstring:** scripts/train_metalearner.py
- **Function `find_latest_run()`**: Locate the run directory whose trades.csv + portfolio_snapshots.csv
- **Function `load_per_edge_daily_raw_scores()`**: Build a (date × edge) matrix of MEAN RAW SCORES from the trade
- **Function `load_per_edge_daily_pnl()`**: Aggregate trade-level fills into a (date × edge) daily PnL matrix.
- **Function `load_portfolio_returns()`**: Daily portfolio return series from portfolio_snapshots.csv.
- **Function `build_features_from_raw_scores()`**: Build per-bar features from a (date × edge) raw-score matrix.
- **Function `build_features()`**: Build a (date × feature) DataFrame from per-edge daily PnL.
- **Function `build_profile_aware_target()`**: Build the training target: profile-aware fitness over the next
- **Function `walk_forward_train()`**: Train the meta-learner via walk-forward folds and report per-fold
- **Function `write_validation_report()`**: No docstring
- **Function `main()`**: No docstring

### `train_per_ticker_metalearner.py`
**Module Docstring:** scripts/train_per_ticker_metalearner.py
- **Function `find_latest_per_ticker_parquet()`**: No docstring
- **Function `load_per_ticker_scores()`**: No docstring
- **Function `assert_no_leakage()`**: Refuse to train if the corpus contains any rows >= cutoff. Returns
- **Function `per_ticker_features()`**: Pivot per-ticker rows to (date × edge_id) of raw_score.
- **Function `per_ticker_forward_return()`**: Forward H-day return on the ticker's CLOSE series.
- **Function `walk_forward_train_ticker()`**: Walk-forward training for ONE ticker.
- **Function `main()`**: No docstring

### `train_signal_gate.py`
- **Function `train_gate()`**: No docstring

### `update_data.py`
- **Function `update_all_data()`**: Programmatic entry point for data updating.
- **Function `main()`**: No docstring

### `validate_active_edges.py`
- **Function `main()`**: No docstring

### `validate_complementary_discovery.py`
- **Function `validate_discovery_vocabulary()`**: No docstring

### `validate_lifecycle_triggers.py`
**Module Docstring:** Phase 2.10d Task A validation driver.
- **Function `main()`**: No docstring

### `validate_phase2_math.py`
- **Function `test_phase2_math()`**: No docstring

### `walk_forward_affinity.py`
**Module Docstring:** scripts/walk_forward_affinity.py
- **Function `backup()`**: No docstring
- **Function `restore()`**: No docstring
- **Function `write_gov_config()`**: No docstring
- **Function `latest_run_summary()`**: No docstring
- **Function `phase_train()`**: No docstring
- **Function `phase_eval()`**: No docstring
- **Function `main()`**: No docstring

### `walk_forward_factor_edge.py`
**Module Docstring:** scripts/walk_forward_factor_edge.py
- **Function `backup()`**: No docstring
- **Function `restore()`**: No docstring
- **Function `set_edge_weight()`**: No docstring
- **Function `latest_run_summary()`**: No docstring
- **Function `run_eval()`**: No docstring
- **Function `main()`**: No docstring

### `walk_forward_phase210.py`
**Module Docstring:** scripts/walk_forward_phase210.py
- **Function `main()`**: No docstring

### `walk_forward_regime.py`
**Module Docstring:** scripts/walk_forward_regime.py
- **Function `backup()`**: No docstring
- **Function `restore()`**: No docstring
- **Function `write_gov_config()`**: Write governor_settings.json with overrides.
- **Function `latest_run_summary()`**: Read performance_summary.json from the most-recently-modified run dir.
- **Function `phase_train()`**: Phase 1: clean slate, run 2021-2022 with governor on → save OOS-anchor.
- **Function `phase_eval()`**: Phase 2/3: restore OOS anchor, run 2023-2024 --no-governor with given policy.
- **Function `main()`**: No docstring

### `walk_forward_risk_advisory.py`
**Module Docstring:** scripts/walk_forward_risk_advisory.py
- **Function `backup()`**: No docstring
- **Function `restore()`**: No docstring
- **Function `write_cfg()`**: No docstring
- **Function `latest_run_summary()`**: No docstring
- **Function `phase_train()`**: No docstring
- **Function `phase_eval()`**: No docstring
- **Function `main()`**: No docstring
