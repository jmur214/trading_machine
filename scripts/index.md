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

### `ab_engine_c_hrp.py`
**Module Docstring:** A/B harness: weighted_sum vs HRP under run_isolated.
- **Function `main()`**: No docstring

### `ab_path_a_tax_efficient_core.py`
**Module Docstring:** A/B/C/D harness — Path A tax-efficient core (HRP slice 2 + turnover
- **Function `main()`**: No docstring

### `analyze_discovery_diagnostic.py`
**Module Docstring:** scripts/analyze_discovery_diagnostic.py
- **Function `load_records()`**: No docstring
- **Function `fmt_pct()`**: No docstring
- **Function `main()`**: No docstring

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

### `audit_feature_archive.py`
**Module Docstring:** 90-day archive enforcement for the Feature Foundry.
- **Class `AuditDecision`**: No docstring
- **Function `evaluate_card()`**: Decide whether `card` should be flagged review_pending.
- **Function `apply_decision()`**: Mutate the card in-place and write it back when the action is
- **Function `reset_pending()`**: Optional: clear all `review_pending` flags before re-running.
- **Function `run_audit()`**: Iterate over every card in `root`, evaluate, and (unless
- **Function `main()`**: No docstring

### `backfill_decision_diary.py`
**Module Docstring:** One-shot backfill of decision diary with this week's load-bearing decisions.
- **Function `main()`**: No docstring

### `backtest_transition_warning.py`
**Module Docstring:** scripts/backtest_transition_warning.py
- **Function `build_extended_panel()`**: Build an extended daily feature panel covering `start` → `end`.
- **Function `detect_real_transitions()`**: Identify durable argmax-state transitions in a posterior sequence.
- **Function `evaluate_anchor_events()`**: For each anchor event, find lead time of the first warning fire.
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

### `feature_foundry_gate.py`
**Module Docstring:** Feature Foundry CI gate.
- **Class `FeatureCheck`**: No docstring
- **Function `load_margin()`**: Resolve the adversarial margin: env var > YAML config > default.
- **Function `run_pytest()`**: Run the Feature Foundry test module. Returns the pytest exit code.
- **Function `import_feature_modules()`**: Import each changed feature file so its `@feature` decorator runs.
- **Function `validate_model_cards()`**: Run the existing card validator scoped to changed features.
- **Function `adversarial_check()`**: Real-vs-twin lift comparison.
- **Function `resolve_changed_paths()`**: Decide which feature files to gate.
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

### `fetch_vix_term_structure.py`
**Module Docstring:** fetch_vix_term_structure — cache CBOE VIX-family closes to data/macro/.
- **Function `fetch_one()`**: No docstring
- **Function `main()`**: No docstring

### `harvest_data.py`
- **Function `harvest()`**: Run a simulation to collect (Features, Label) pairs for ML training.

### `hrp_slice_3_redistribution_histogram.py`
**Module Docstring:** Sanity histogram for HRP slice 3's redistribution behaviour.
- **Function `build_data_map()`**: Two-cluster synthetic returns with mild within-cluster noise.
- **Function `collect_optimizer_weights()`**: No docstring
- **Function `histogram()`**: Bucket optimizer_weights into [0, 0.25), [0.25, 0.5), ... up to
- **Function `render_md_block()`**: No docstring
- **Function `main()`**: No docstring

### `migrate_edge_graveyard_tags.py`
**Module Docstring:** One-time migration: tag failed edges with structured graveyard metadata.
- **Function `migrate()`**: Apply graveyard tags. Returns map of edge_id -> action taken.
- **Function `main()`**: No docstring

### `optimize.py`
- **Function `main()`**: No docstring

### `path1_revalidation_grid.py`
**Module Docstring:** scripts/path1_revalidation_grid.py
- **Function `run_cell()`**: No docstring
- **Function `main()`**: No docstring

### `path_c_overlays.py`
**Module Docstring:** Path C overlays — standalone risk-overlay helpers for the compounder backtest.
- **Class `VolOverlayDiagnostics`**: Per-rebalance overlay diagnostics — used for clip-frequency analysis.
  - `def clip_state()`: Categorize the overlay action this rebalance.
- **Function `estimate_portfolio_vol()`**: Estimate annualized portfolio volatility from a wide price panel.
- **Function `apply_vol_target()`**: Scale weights to hit `target_vol`, clipped to [clip_low, clip_high].
- **Function `apply_exposure_cap()`**: Hard-cap gross exposure at `cap`.
- **Function `summarize_overlay_diagnostics()`**: Aggregate per-rebalance diagnostics into clip-frequency summary stats.

### `path_c_synthetic_compounder.py`
**Module Docstring:** Path C — compounder sleeve feasibility backtest.
- **Class `RebalanceEvent`**: No docstring
- **Class `BacktestResult`**: No docstring
- **Function `build_universe()`**: S&P 500 current-constituents ∩ ex-financials ∩ SimFin coverage.
- **Function `fetch_prices()`**: Fetch adjusted close prices via yfinance, with parquet caching.
- **Function `compute_composite_score_synthetic()`**: SYNTHETIC (price-derived) composite — preserved as Cell C baseline.
- **Function `apply_defensive_prescreen()`**: Keep the ``top_n`` lowest-trailing-vol names from ``universe`` as-of ``as_of``.
- **Function `compute_composite_score_real()`**: REAL-fundamentals composite — 6 V/Q/A factors via SimFin panel.
- **Function `get_first_trading_day_of_january()`**: Find the first available trading day in January of `year`.
- **Function `run_compounder_backtest()`**: Long-only annual-rebalance equal-weighted top-quintile compounder.
- **Function `run_spy_buy_and_hold()`**: Pure buy-and-hold of SPY. Tax applies only at terminal sale (LT).
- **Function `run_60_40_benchmark()`**: No docstring
- **Function `main()`**: Run the 5-cell harness comparing real-fundamentals vs synthetic vs vol-overlay.

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

### `run_discovery_diagnostic.py`
**Module Docstring:** scripts/run_discovery_diagnostic.py
- **Function `main()`**: No docstring

### `run_discovery_diagnostic_standalone.py`
**Module Docstring:** scripts/run_discovery_diagnostic_standalone.py
- **Function `load_data_map()`**: Load slim ticker set from data/processed/*_1d.csv.
- **Function `emit_timeout()`**: No docstring
- **Function `main()`**: No docstring

### `run_evaluator.py`
- **Function `main()`**: No docstring

### `run_evolution_cycle.py`
- **Class `AutonomousEvolution`**: The Master Learning Loop.
  - `def __init__()`
  - `def run_cycle()`

### `run_falsifiable_spec.py`
**Module Docstring:** Capture falsifiable-spec results for the gauntlet architectural fix.
- **Function `build_candidate_spec()`**: No docstring
- **Function `load_data_map()`**: No docstring
- **Function `main()`**: No docstring

### `run_healthcheck.py`
**Module Docstring:** Trading Machine - Unified Healthcheck Script
- **Function `run_cmd()`**: Run a shell command, stream output, and return success boolean.
- **Function `run_pytests()`**: Run only the high‑signal tests that verify portfolio math + controller logic.
- **Function `run_dev_backtest()`**: Run the small/fast dev backtest. User may later customize flags.
- **Function `run_invariants()`**: Perform core snapshot/trade invariants.
- **Function `main()`**: No docstring

### `run_isolated.py`
**Module Docstring:** scripts/run_isolated.py
- **Function `reset_module_globals()`**: Reset all registered cross-run-contaminating module globals.
- **Function `save_anchor()`**: Snapshot `data/governor/<file>` for every name in ISOLATED_FILES.
- **Function `restore_anchor()`**: Restore the full set of governor files from the anchor.
- **Function `isolated()`**: Context manager: restore anchor on entry, restore again on exit.
- **Function `main()`**: No docstring

### `run_live.py`
*No public classes or functions found.*

### `run_multi_year.py`
**Module Docstring:** scripts/run_multi_year.py
- **Function `main()`**: No docstring

### `run_oos_validation.py`
**Module Docstring:** scripts/run_oos_validation.py
- **Function `sample_universe_b()`**: Mirror engines/engine_d_discovery/discovery.py::_load_universe_b
- **Function `find_run_id()`**: No docstring
- **Function `run_q1()`**: 2025 OOS on prod universe. Same costs, shifted window, reset governor.
- **Function `run_q2()`**: Universe-B (50 held-out tickers, seed=42) on same in-sample window.
- **Function `run_q3()`**: 2021-2024 IS on prod universe with production-equivalent ensemble.
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

### `train_hmm_regime.py`
**Module Docstring:** scripts/train_hmm_regime.py
- **Function `main()`**: No docstring

### `train_hmm_vix_term.py`
**Module Docstring:** train_hmm_vix_term — train a 3-state HMM on the rebuilt feature panel
- **Function `main()`**: No docstring

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

### `train_multires_hmm.py`
**Module Docstring:** scripts/train_multires_hmm.py
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

### `validate_regime_signals.py`
**Module Docstring:** validate_regime_signals — read-only validation of HMM + WS-C signals.
- **Function `load_spy()`**: No docstring
- **Function `load_fred()`**: No docstring
- **Function `compute_hyg_lqd_z()`**: 60-business-day z-score of (BAMLH0A0HYM2 - BAMLC0A0CM).
- **Function `compute_dxy_change_20d()`**: No docstring
- **Function `compute_vvix_proxy()`**: No docstring
- **Function `forward_drawdown()`**: For each t, the worst forward drawdown over (t, t+horizon].
- **Function `forward_return()`**: Forward arithmetic return over `horizon` bars.
- **Function `auc_score()`**: ROC AUC from scratch (avoids sklearn dependency).
- **Function `hit_rate_and_fpr()`**: Hit rate (TPR) and false-positive rate.
- **Function `cond_mean_dd()`**: Mean forward drawdown conditional on a boolean mask.
- **Function `lead_time_stats()`**: For each forward window with drawdown ≤ threshold, find the lead
- **Function `main()`**: No docstring

### `validate_regime_signals_cheap.py`
**Module Docstring:** validate_regime_signals_cheap — feature-level cheap-input validation.
- **Function `load_spy()`**: No docstring
- **Function `load_macro_series()`**: No docstring
- **Function `forward_drawdown()`**: No docstring
- **Function `forward_return()`**: No docstring
- **Function `auc_score()`**: No docstring
- **Function `build_vix_term_features()`**: Compute VIX term-structure slopes on the daily index.
- **Function `build_pc_ratio_features()`**: Attempt to load CBOE total P/C ratio from data/macro/cboe_pc_ratio.parquet.
- **Function `conditional_top_decile()`**: No docstring
- **Function `coincident_leading_test()`**: No docstring
- **Function `main()`**: No docstring

### `validate_regime_signals_vix_term.py`
**Module Docstring:** validate_regime_signals_vix_term — slice-1 panel-rebuild validation.
- **Function `load_spy()`**: No docstring
- **Function `load_fred()`**: No docstring
- **Function `forward_drawdown()`**: No docstring
- **Function `forward_return()`**: No docstring
- **Function `auc_score()`**: No docstring
- **Function `hit_rate_and_fpr()`**: No docstring
- **Function `cond_mean_dd()`**: No docstring
- **Function `lead_time_stats()`**: No docstring
- **Function `main()`**: No docstring

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

### `wash_sale_multi_year.py`
**Module Docstring:** scripts/wash_sale_multi_year.py
- **Function `main()`**: No docstring
