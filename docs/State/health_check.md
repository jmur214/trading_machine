# Code Health Tracker

Living document tracking the current quality state of the codebase. 
Maintained by the `engine-auditor` and `code-health` subagents — they 
append findings as they discover them. Resolved items move to the 
"Resolved" section with a date.

This is the source of truth for SESSION_PROCEDURES.md Path 2 
("Critical findings"). When the user asks what's next, this file is 
checked before the roadmap.

If this file appears empty or stale, run the engine-auditor against 
recently-touched engines or the code-health subagent across the 
codebase to populate it.

---

## Active Issues

Findings are listed in priority order: HIGH first, then MEDIUM, 
then LOW. Within each severity, list newest at the top.

### HIGH

### [HIGH → RESOLVED 2026-05-02] Gauntlet geometry-mismatch — gates 1–6 consumed a standalone single-edge equity curve incompatible with ensemble-deployed strategies
- Engine: D (Discovery — `engines/engine_d_discovery/discovery.py::validate_candidate`, gates 1–6) + orchestration (the production-equivalent backtest invocation that didn't exist)
- First flagged: cumulatively across 2026-04-29 → 2026-05-01 — Q3 gauntlet revalidation (`docs/Audit/gauntlet_revalidation_2026_04.md`), Phase 2.10c per-edge attribution (`oos_2025_decomposition_2026_04.md`), discovery diagnostic (`docs/Audit/discovery_diagnostic_2026_05.md`), gates-2-through-6 audit (`docs/Audit/gates_2_to_6_audit_2026_05.md`). Memory: `project_gauntlet_consolidated_fix_2026_05_01.md`.
- **Status: RESOLVED 2026-05-02.** Consolidated architectural fix shipped on `gauntlet-architectural-fix` branch, merged to main as commits `2451076` (gauntlet fix) and `36d9072` (merge). Agent 1's audit `docs/Audit/gauntlet_architectural_fix_2026_05.md` documents the design rationale, threshold calibration, and falsifiable-spec verification. Path A's foundation work landed alongside the Feature Foundry merge `9ea6c17`.
- Description: `validate_candidate` ran a single-edge **standalone** backtest (one edge at full risk-per-trade, no ensemble context) and used its equity curve as the input to all six downstream gates. Two structural problems followed: (a) Gate 1's standalone Sharpe is incommensurable with ensemble-deployed Sharpe — full risk-per-trade per fill crossed the Almgren-Chriss impact knee on `volume_anomaly_v1` and `herding_v1` (Q3 produced 0.32 / -0.26 standalone vs +ensemble contribution; the very edges that contribute positively in production were architecturally falsified by the gate); (b) gates 2–6 inherited the standalone artifact and tested the wrong object (a strawman strategy, not the candidate's actual ensemble effect). All 6 gates were not 6 independent bugs — they were one architectural mismatch between measurement geometry and deployment geometry, which violates the foundation rule "Geometry of measurement matches deployment. No standalone tests for ensemble-deployed strategies." (`docs/Sessions/Other-dev-opinion/05-1-26_1-percent.md`).
- Fix: `validate_candidate` rewritten to run two production-equivalent backtests per candidate via the new `orchestration/run_backtest_pure.py::run_backtest_pure` (pure callable, no governor/CSV/perf-summary side effects, with `PureBacktestCache` so a Discovery cycle of N candidates costs N+1 backtests instead of 2N). Baseline = (active ∪ paused) **minus** the candidate at production weights (active at config weight, paused at `min(config_weight × 0.25, 0.5)` matching `ModeController`'s soft-pause logic). With-candidate = baseline ∪ {candidate at default weight}. Treatment-effect attribution stream = `with_candidate_returns − baseline_returns`. Gate 1 = contribution Sharpe > θ (default 0.10). Gates 2–6 consume the attribution stream rather than the standalone equity curve. Gate 5 (Universe-B) and Gate 6 (FF5) operate on the same attribution-stream geometry. WFO stitching at `wfo.py:112` switched to RETURNS-based concatenation (eliminates phantom −4.76% returns at every window boundary). Robustness module gains `generate_cross_section_bootstrap` (synchronized block-pick preserves cross-sectional correlation) and `bootstrap_returns_stream` for 1-D attribution streams.
- Verification — falsifiable spec (`docs/Audit/falsifiable_spec_results.json`, captured by `scripts/run_falsifiable_spec.py`, 30-ticker × 2024H1):
  - `volume_anomaly_v1`: contribution +0.113 Sharpe → Gate 1 PASS, Gate 2 PASS (76.5% PBO survival), Gate 5 PASS. **The architectural fix correctly admits a real ensemble contributor that the standalone-geometry gate had architecturally falsified.**
  - `herding_v1`: contribution -0.422 Sharpe in 2024H1 → Gate 1 FAIL (window-specific result for a contrarian edge in a strong bull window; consistent with prior per-edge attribution audits, NOT an infrastructure bug — see memory `project_ensemble_alpha_paradox_2026_04_30.md`).
- Tests: 32 new unit tests pass (`tests/test_run_backtest_pure.py`, `tests/test_attribution.py`, `tests/test_validate_candidate_v2.py`, `tests/test_pbo_cross_section.py`, `tests/test_wfo_oos_stitching.py`). 24 existing discovery tests still pass.
- Honest scope: this resolution closes the **measurement-geometry** bug class. It does not retroactively re-validate prior Q3-era findings (which are already closed under their own resolved entries); it does mean future Discovery cycles measure ensemble contribution honestly. The narrow gate-3 (WFO interface) and gate-5 (datetime index) findings further down in this file were partial precursors that the consolidated fix supersedes architecturally even though they were already closed under their own entries.

### [HIGH → RESOLVED 2026-05-01] Backtest non-determinism regression — same config produced ±1.4 Sharpe variance across runs
- Engine: F (lifecycle / governor state mutation) + orchestration (run_oos_validation harness)
- First flagged: 2026-05-01 (Phase 2.10d/Path 1 ship-validation block)
- **Status: RESOLVED 2026-05-01.** Agent A's investigation (branch `determinism-floor-restore`, audit `docs/Audit/determinism_floor_restore_2026_05.md`) bisected the drift source to a single file: **`data/governor/edges.yml`**. End-of-run lifecycle (`evaluate_lifecycle`) and tier reclassification (`evaluate_tiers`) writes mutate active-edge status; subsequent `--reset-governor` runs read the mutated file and produce different Sharpes. The other three mutable governor files (edge_weights.json, regime_edge_performance.json, lifecycle_history.csv) mutate too but their content is write-only audit; restoring just edges.yml from clean closes the entire 0.227 Sharpe gap exactly. New harness `scripts/run_isolated.py` snapshots+restores edges.yml + 3 audit files around each run. **3-run verify under harness: Sharpe 0.984 / 0.984 / 0.984, 1 unique canon md5 across 3 runs (bitwise-identical, matching the 04-23 floor).** Use `python -m scripts.run_isolated --runs N --task q1` for any measurement campaign. See memory `project_determinism_floor_2026_05_01.md`.
- Description: Backtest reproducibility has regressed materially since the 2026-04-23 determinism floor (memory `project_determinism_floor_2026_04_23.md` documented bitwise-identical canon md5s under `scripts/run_deterministic.py`). Recent same-config runs produce wildly different Sharpe:
  - cap=0.25 + ML-off: Phase 2.10d task C = 0.315; round-1 Agent A A0 hours later = 0.562 (Δ +0.247)
  - cap=0.20 + ML-off: round-1 A3 = 0.920; round-2 B3 v2 = 1.102 (Δ +0.182)
  - **cap=0.20 + ML-on: Agent C round-1 (cap=0.25 default + ML) = 1.064; Agent A round-3 A3 = -0.378 (Δ -1.442 — opposite-sign Sharpe under nominally compatible config)**
- The ±1.4 variance band makes every Sharpe number from the project from 2026-04-29 onward unreliable as a deployment input. Including Agent D's Path 2 result (Universe-B 0.916 with floors+ML) — could be real or could be favorable governor-state coincidence.
- Leading hypothesis: the autonomous lifecycle (`engines/engine_f_governance/lifecycle_manager.py`) and governor (`engines/engine_f_governance/governor.py`) mutate `data/governor/edges.yml`, `lifecycle_history.csv`, `regime_edge_performance.json`, and `edge_weights.json` at end-of-run. `--reset-governor` resets weights at start but does not isolate end-of-run mutations or roll back lifecycle state. Cross-worktree governor-COPY isolation (per `MULTI_SESSION_ORCHESTRATION.md`) prevents inter-agent races but does NOT fix intra-agent run-to-run drift.
- Why this is HIGH (not MEDIUM): the project cannot proceed past Path 1 ship without reproducible measurement. Every A/B claim is provisional. The 2026-04-23 fix already exists at `scripts/run_deterministic.py`; presumably either (a) the OOS validation harness `scripts/run_oos_validation.py` doesn't use it, (b) it broke since 04-23, or (c) it doesn't cover the lifecycle state mutations introduced in Phase 2.10d.
- Recommended next step: dispatch a focused agent for non-determinism investigation. Reproduce the variance with a controlled experiment (run same config 3-5× under tight isolation), find the source of drift (likely candidates: lifecycle_history.csv accumulation, regime_edge_performance.json mutation, edge_weights.json saves), implement a determinism harness that fully isolates a run from prior governor state. Re-establish the bitwise-identical canon md5 floor from the 04-23 baseline. Until this resolves, every Sharpe number is ±1.4 noise.
- See: `docs/Audit/path1_ship_validation_2026_05.md` (Agent A's blocked ship + ±1.4 evidence), `docs/Audit/path2_adv_floors_2026_05.md` (Agent D's caveat), memory `project_determinism_floor_2026_04_23.md` (the prior fix).

### [HIGH → RESOLVED 2026-05-01] System alpha is real but architecturally wasted — capital rivalry + noise edges drag the ensemble (updated 2026-04-30, resolved 2026-05-01)
- Engine: A (signal_processor capital allocation) + C (portfolio engine slot management) + F (lifecycle — partial; pause decisions vindicated, soft-pause weight policy in question)
- First flagged: 2026-04-29 (as "no validated alpha"); **revised 2026-04-30** after Phase 2.10c per-edge attribution diagnostics resolved the apparent paradox.
- **Status: RESOLVED 2026-05-01** — Phase 2.10d task B shipped the three structural primitives; round-2 cap recalibration found cap=0.20 as the optimum (Sharpe 1.102 OOS / 1.113 IS, full-pass gate cleared). `fill_share_cap: 0.20` is the production cap value. Path 1 deployment-ship state captures cap=0.20 as the validated baseline.
- **Residual:** the ML-stacking variant of Path 1 (cap=0.20 + ML-on) did NOT reproduce in agentA's path1-deployment-ship validation (Sharpe -0.378 vs the expected 1.1+ from stacking on Agent C's 1.064 ML-on baseline). Same nominal config; different governor state at run start. Tracked as a separate ship blocker — see `docs/Audit/path1_ship_validation_2026_05.md`. Resolution path is non-deterministic-state diagnosis, NOT re-investigating the rivalry pathology (which is structurally fixed).
- See `docs/Audit/capital_allocation_fixes_2026_04.md`, `docs/Audit/cap_recalibration_sweep_2026_04.md`, `docs/Audit/cap_bracket_sweep_2026_04.md`, `docs/State/deployment_boundary.md`.

### [HIGH NEW → RESOLVED 2026-05-01 evening] Same-config Sharpe non-determinism across worktrees — lifecycle_history.csv likely culprit (2026-05-01)
- Engine: F (lifecycle history not snapshotted by sweep harness) + orchestration (anchor restore semantics)
- First flagged: 2026-04-30 in `cap_bracket_sweep_2026_04.md`; **escalated to ship-blocker 2026-05-01** by `path1_ship_validation_2026_05.md`.
- **Status: RESOLVED 2026-05-01 evening.** Agent A's `determinism-floor-restore` branch isolated the actual drift source to a different file: **`data/governor/edges.yml`** (not lifecycle_history.csv as initially hypothesized — that file does mutate but its content is write-only audit). End-of-run lifecycle + tier-reclassification writes to edges.yml; subsequent runs read mutated state. The new `scripts/run_isolated.py` harness snapshots+restores 4 governor files (edges.yml + 3 audit files) around each backtest. **3-run verify produces bitwise-identical canon md5 across runs.** Subsequent re-validation under harness confirmed: cap=0.20 + ML-off = 0.984 Sharpe deterministic on 2025 OOS prod-109; ML-on degrades by ~0.58 (the +0.749 lift was governor-drift coincidence). See memory `project_determinism_floor_2026_05_01.md` and `project_metalearner_drift_falsified_2026_05_01.md`. The `path1-revalidation-under-harness` audit table is the canonical post-harness measurement set.

### [HISTORICAL — superseded by entries above 2026-05-01]
- Status: closed.
- Description: per Phase 2.10c attribution work (audit docs `oos_2025_decomposition_2026_04.md` and `per_edge_per_year_attribution_2026_04.md`), the system *does* have real alpha — but it lives in the ensemble's risk-sizing dampening + edge-timing diversification, not in standalone signals. Specifically:
  - **Stable contributors (positive every year 2021-2025):** `volume_anomaly_v1` (+1.93% to +4.94%/yr), `herding_v1` (+0.55% to +2.43%/yr).
  - **Weak-positive diversifiers:** `gap_fill_v1`, `macro_credit_spread_v1`, and 4 others (~+0.5%/yr each).
  - **Noise / sparse / zero-fill dead weight:** ~9-11 edges contributing nothing or near-zero across 5 years.
  - **Lifecycle-paused edges (vindicated):** `atr_breakout_v1` (-5.78% in 2022 alone), `momentum_edge_v1` (-9.17% in 2022), `low_vol_factor_v1`. All 3 pause decisions were correct in retrospect.
- The Q3 standalone-gauntlet failure of `volume_anomaly_v1` and `herding_v1` was a **measurement-vs-test mismatch**, not a falsification: standalone Gate 1 gives full `risk_per_trade_pct` per fill, which crosses the Almgren-Chriss impact knee. In production, risk-per-trade is split across 17 firing signals → sub-knee fills → cost tax stays small → signal survives. See memory `project_ensemble_alpha_paradox_2026_04_30.md`.
- Three concrete defects identified in Phase 2.10c (Agent A audit doc):
  1. **Capital rivalry — no per-edge participation floor.** Bottom-3 edges in 2025 (`low_vol_factor_v1`, `atr_breakout_v1`, `momentum_edge_v1`) consumed 83% of fill share for -$5,645 of realized losses; top-2 best-PnL edges got 4.3% of fill share. Un-pausing momentum edges flipped `volume_anomaly_v1` per-fill from +$10.12 to -$1.17.
  2. **Soft-pause weight leak — `low_vol_factor_v1` fired 1,613 times in 2025** despite being effectively paused (weight 0.5 × regime_gate `{benign:0.15, stressed:1.0, crisis:1.0}`). It contributed -2.53% in 2025 alone, mostly via the regime_gate amplifying it in `market_turmoil`/`crisis` regimes — exactly when it should NOT trade.
  3. **No regime-aware slot reduction.** April-2025 `market_turmoil` triggered -$3,551 of simultaneous correlated loss across 5 edges in one month (122% of full-year loss). The portfolio engine has no primitive to reduce concurrent slot count in stressed regimes.
- Why this is HIGH (not MEDIUM): the system's headline performance (1.063 in-sample, -0.049 OOS, 0.225 universe-B) is gated entirely on these three structural issues. Pruning + fixing them is the path to unblocking Phase 2.11/2.12/2.5; not fixing them means the gauntlet never runs out of failure modes to surface.
- Recommended next step: **Phase 2.10d** (see ROADMAP). Two parallel diagnostics — (A) attribution-based pruning proposal cutting 9-11 noise edges to ~6-7 actives, (B) capital allocation defect investigation with code-change proposals. Then sequential C: re-run 2025 OOS with pruned + structurally-fixed system.
- Original entry kept below for context, dated 2026-04-29:

### [HIGH] (HISTORICAL — superseded by entry above 2026-04-30) In-sample Sharpe 1.063 was a double artifact — system has no validated alpha under honest costs on a representative universe
- Engine: A (signal_processor / edge stack) + D (discovery / lifecycle decisions made on artifact data)
- First flagged: 2026-04-29 (Phase 2.10b OOS Validation Gate result)
- Status: **active — blocking all forward feature work.** Phase 2.10c diagnostic triage required next.
- Description: Phase 2.10b ran the three OOS gates for the realistic-cost in-sample Sharpe 1.063 result. **All three failed by wide margins:**
  - **Q1 (2025 OOS, prod 109 universe):** Sharpe **-0.049** vs criterion > 0.5. SPY 2025 was 0.955 — system trailed every benchmark by **>1.0 Sharpe** in a strong bull year. Run UUID `72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34`. Audit: `docs/Audit/oos_validation_2026_04.md`.
  - **Q2 (universe-B held-out 50, in-sample window):** Sharpe **0.225** vs in-sample 1.063 — a **79% Sharpe collapse** on the same window with held-out tickers. Vol nearly doubled (5.7% → 9.95%), MDD nearly doubled (-10.07% → -18.17%). Run UUID `ee21c681-f8de-4cdb-9adb-a102b4063ca1`.
  - **Q3 (`volume_anomaly_v1` + `herding_v1` standalone gauntlet under realistic costs):** Both failed Gate 1. Sharpe 0.32 and **-0.26** respectively (`herding_v1` standalone is capital-destroying under honest costs) vs benchmark threshold ~0.68. The prior factor-decomp t-stats of +4.36 and +4.49 were a cost-model confound — `validate_candidate` hardcoded slippage at 5bps while the integration backtest used realistic Almgren-Chriss. Audit: `docs/Audit/gauntlet_revalidation_2026_04.md`.
- Diagnosis: the 1.063 in-sample headline is a **double artifact** — favorable universe (curated 109 mega/mid caps) AND favorable window (2021-2024). Universe-B at 0.225 is in the same ZIP code as the prior 0.4 baseline noted in `project_lifecycle_vindicated_universe_expansion_2026_04_25.md`. The "two real alphas" claim is falsified.
- What this kills: Phase 2.11 (per-ticker meta-learner), Phase 2.12 (growth-profile config), Phase 2.5 (Moonshot Sleeve) all blocked until Phase 2.10c diagnostic triage determines whether ANY real alpha exists in the active edge stack.
- Adjacent bug fix shipped on `gauntlet-revalidation` branch: `engines/engine_d_discovery/discovery.py::validate_candidate` previously hardcoded `slippage_bps=5.0`; agent added `exec_params` override so candidates can be validated under the same cost model the integration backtest uses. **This is a real bug fix independent of the edge result and should land on main.**
- Recommended next step: Phase 2.10c — full standalone gauntlet on all 13 active edges + TierClassifier rerun with realistic costs + universe-fit decomposition. Single audit doc per diagnostic. **No new features until results are in.**
- See: `docs/State/ROADMAP.md` Phase 2.10b/2.10c sections, `docs/Archive/forward_plans/forward_plan_2026_04_29.md` "Result" section.

### [HIGH] Sharpe-only fitness limits portfolio profile flexibility — multi-metric measurement + config-driven fitness profile needed
- Engine: A (signal_processor / meta-learner) + D (discovery gates) + F (lifecycle)
- First flagged: 2026-04-28
- Status: not started — design ready in `docs/Core/phase1_metalearner_design.md`
- Description: The realistic-cost backtest produced Sharpe 1.063 (vs SPY 0.875) with under HALF the volatility and HALF the drawdown — but only **6.06% CAGR vs SPY 13.94%**. The system's apparent excellence on Sharpe is partly because Sharpe is volatility-normalized: a 5.7%-vol system beats a 16.5%-vol system on Sharpe even when its absolute return is half. **What's optimal for a low-vol/retiree profile (low drawdown, high Sharpe) is NOT optimal for a growth profile (high CAGR even at higher vol).** Currently every gate, fitness function, and lifecycle decision in the codebase uses Sharpe as the dominant metric. This hardcodes one profile preference into infrastructure that should support multiple.
- Architectural fix (three-layer separation, per design doc):
  - **Layer 1 (Existence — alive vs retired):** OBJECTIVE / profile-independent. Lifecycle gates use factor-decomp t-stat, BH-FDR, PBO survival, raw Sharpe vs benchmark. An edge gets retired only for objective reasons (consistently destroying value, no real signal, charter-broken). Profile changes do NOT retire edges.
  - **Layer 2 (Tier — alpha/feature/context):** OBJECTIVE / profile-independent. Machine-classified from factor-decomp t-stats by the planned `TierClassifier` module. Self-updating, not hand-set.
  - **Layer 3 (Allocation — how much capital):** SUBJECTIVE / config-driven. The active `FitnessConfig` profile weights Sharpe + Calmar + Sortino + CAGR + MDD into a single fitness score. Profiles in `config/fitness_profiles.yml`: retiree (`0.6 calmar + 0.3 sortino + 0.1 sharpe`), balanced (`0.5 sharpe + 0.3 calmar + 0.2 cagr`), growth (`0.5 cagr + 0.3 sharpe + 0.2 calmar`).
  - The meta-learner trains against the active profile's fitness target, not raw forward returns.
- Why this is HIGH (not MEDIUM): every downstream optimization in the system is currently anchored to Sharpe. Without this fix, the v2 plan's "build edges, autonomously combine" architecture is implicitly committing to one risk profile forever. Switching to a different profile later would require code edits across discovery, lifecycle, and signal_processor.
- Recommended next step: implement during Session N of the meta-learner build (foundation phase). `MetricsEngine.calculate_all` already returns Calmar (commit fb1ba13 era); just add Sortino and Sortino-coverage tests, then add the `FitnessConfig` config layer. The `TierClassifier` rule and Lifecycle objective gates are already designed in the meta-learner design doc.
- See: `docs/Core/phase1_metalearner_design.md` ("Three-layer architecture" section), `docs/Audit/realistic_cost_backtest_result.md` (the empirical observation that triggered this finding).

### [MEDIUM] validate_candidate uses full data_map extent instead of configured backtest window — Gate 1 takes ~35 min/candidate
- Engine: D
- First flagged: 2026-04-28
- Status: not started
- Description: `discovery.py::validate_candidate` lines 631-632 derive `start_date` and `end_date` from `data_map[first_ticker].index[0]` and `[-1]`. The data_map fed by `mode_controller._run_discovery_cycle` is the full price-history parquet (2020-04 → 2026-04, ~6 years for current cache) including the 1-year warmup window. So Gate 1's "quick backtest" runs 6 years of data on 109 tickers per candidate — observed empirically at ~30-35 min per Gate 1. Combined with Gates 2-5, each candidate takes ~2 hours. With the cycle cap of 10 candidates this is ~20 hours per discovery run, making the autonomous loop impractical.
- Recommended next step: Have validate_candidate accept (or look up) a "validation window" — e.g. last 12-24 months — for Gate 1's quick filter. Gate 3 (WFO) already does proper multi-window OOS via train_months/test_months params, so a short Gate 1 window is fine for the cheap pass/fail filter. Either honor `cfg_bt["start_date"]`/`end_date` from backtest_settings, or expose `validation_start_date`/`validation_end_date` parameters to the mode_controller call site.

### [HIGH] RuleBasedEdge requires FeatureEngineer-computed columns that are absent from validation data_map
- Engine: D (with A as the affected receiver — `RuleBasedEdge.check_signal`)
- First flagged: 2026-04-28
- Status: not started
- Description: After commit dda474c added `RuleBasedEdge.compute_signals()`, hunter candidates run through Gate 1 — but they still produce Sharpe=0.00 with zero trades. Root cause: `check_signal()` reads `row[feat]` for features like `RSI_14`, `Vol_ZScore`, `Regime_CorrSpike` etc. These columns are only populated by `FeatureEngineer.compute_*` methods during the hunt phase (assembled into `big_data` at `discovery.py::hunt:106`), and are NOT preserved into the validation `data_map` that `validate_candidate` passes to AlphaEngine. The data_map there has only OHLCV columns. `if feat not in row: return None` triggers on every bar, every ticker. Result: hunter Gate 1 Sharpe = 0.00 → fails benchmark threshold → marked failed. The autonomous discovery loop cannot promote any rule discovered by TreeScanner regardless of how good the rule is.
- Files: `engines/engine_a_alpha/edges/rule_based_edge.py::check_signal`, `engines/engine_d_discovery/discovery.py::validate_candidate` (data_map passed to AlphaEngine without feature engineering), `engines/engine_d_discovery/feature_engineering.py` (where features are computed but only for hunt).
- Recommended next step: Either (a) `RuleBasedEdge.compute_signals` calls `FeatureEngineer` on the per-ticker DataFrame at signal-time to add the columns its conditions reference, OR (b) `validate_candidate` runs `FeatureEngineer.compute_basic_features()` over `data_map` before instantiating the AlphaEngine. Option (a) is cleaner — keeps the edge self-sufficient and matches how rsi_bounce/atr_breakout compute their features inline. Add a unit test asserting hunter validation produces non-zero Sharpe given a contrived dataset where the rule trivially matches.

### [HIGH] Engine A alpha_engine references deleted `rsi_mean_reversion` module — bare-except masks 6-month-old broken import
- Engine: A
- First flagged: 2026-04-28
- Status: **resolved 2026-04-28** — dead imports removed, default edge swapped to `rsi_bounce`
- Description: `alpha_engine.py:251` listed `"rsi_mean_reversion"` in `default_edges`, and `alpha_engine.py:422` did `importlib.import_module("engines.engine_a_alpha.edges.rsi_mean_reversion")`. Module was deleted 2025-11-12. Both call sites were wrapped in `except Exception` blocks that only printed under `is_info_enabled()` — failure was invisible under standard logging. AlphaEngine ran with one fewer default edge for ~6 months.
- Fix: Replaced both import sites with `rsi_bounce` (the only existing RSI edge); removed orphan `"rsi_mean_reversion": "mean_reversion"` from `signal_processor.EDGE_AFFINITY_MAP`; updated `config/alpha_settings.dev.json` orphan entry; replaced silent `except Exception` with `except ImportError` that raises with diagnostic context. Future default-edge rename will now fail loudly at startup.

### [HIGH → CLOSED 2026-04-28] (misdiagnosed) Engine D WFO `_quick_backtest` keys edges dict by edge_id, but AlphaEngine looks up weights by edge_name — WFO runs all edges at default weight 1.0
- Engine: D (with A as the receiver of the contract drift)
- First flagged: 2026-04-28
- Status: **misdiagnosed — closed 2026-04-28**
- Description: code-health agent claimed `AlphaEngine.edges` is keyed by edge_name (`"momentum_edge"`) in production, but WFO keys by edge_id (`"momentum_edge_v1"`). Verification on 2026-04-28: `mode_controller._load_edges_via_registry` lines 674-679 actually populate `loaded_edges[edge_id] = ...`, and `config/alpha_settings.prod.json::edge_weights` is keyed by edge_id (`"atr_breakout_v1": 2.5`). Both sides of the lookup use edge_id consistently. WFO's `AlphaEngine(edges={spec["edge_id"]: edge})` matches production convention.
- Real (smaller) issue: WFO does not pass `edge_weights` or `regime_gates` to AlphaEngine, so a single-edge WFO test runs at weight=1.0 with regime_gates bypassed. For a solo WFO test this is the **desired** behavior — there is no other edge to compete with for capital, and you typically want to measure the unconditioned edge. If we ever need to WFO-test a regime-gated edge with its gate active, surface it as a separate finding.

### [HIGH → RESOLVED 2026-04-28] Engine D Gate 3 (WFO) is silently disabled — interface mismatch with WalkForwardOptimizer
- Engine: D
- First flagged: 2026-04-28
- Status: **resolved 2026-04-28** — rewired with correct interface
- Description: `discovery.py::validate_candidate` line 736 called `WalkForwardOptimizer()` with no args, but ctor requires `data_map`. Line 750 called `run_optimization(_WFOWrapper(edge), data_map, n_configs=1)` — wrong signature. Bare `except` swallowed everything; Gate 3 trivially passed for every candidate. No candidate was actually WFO-validated since this code was written.
- Fix: Rewrote Gate 3 block to use the correct interface — `WalkForwardOptimizer(data_map=data_map)`, then `run_optimization(candidate_spec, start_date=..., train_months=12, test_months=3)`. Removed the `_WFOWrapper` shim (candidate_spec already has `module`/`class`/`edge_id` keys, doubles as `strategy_spec`). The bare-except now re-raises `TypeError` and `AttributeError` so future interface drift surfaces immediately. Also fixed `wfo.py::run_optimization` deprecated `get_loc(method='nearest')` → `get_indexer(..., method='nearest')` (separate but related bug masked by another bare-except).

### [HIGH → RESOLVED 2026-04-28] Engine D Gate 5 (Universe-B) crashes silently — same datetime-index bug just fixed at Gate 1
- Engine: D
- First flagged: 2026-04-28
- Status: **resolved 2026-04-28** — datetime index added at line 806
- Description: `discovery.py:806` built the universe-B equity curve as `pd.Series([h["equity"] for h in b_history])` with no datetime index. `MetricsEngine.cagr()` then crashed on `.days` of the integer RangeIndex. Bare-except set `universe_b_sharpe = float("nan")` and reported `Gate 5 skipped`. The Gate-5 logic `universe_b_passed = math.isnan(...) or > 0` gave every candidate a free pass.
- Fix: Same pattern as Gate 1 — `pd.Series([h["equity"] for h in b_history], index=pd.to_datetime([h["timestamp"] for h in b_history]))`. Exception logging now includes `type(e).__name__` so future schema drift is identifiable instead of being swallowed as "Gate 5 skipped".

### [HIGH → RESOLVED 2026-04-28] Engine D feature_engineering reads regime keys that don't exist on RegimeDetector output
- Engine: D
- First flagged: 2026-04-28
- Status: **resolved 2026-04-28** — read from structured `*_regime["state"]` keys
- Description: `feature_engineering.py:347-358` did `regime_meta.get("correlation")`, but RegimeDetector's output only has `"correlation"` nested under `correlation_regime["state"]`. `Regime_CorrSpike` was hardcoded 0 for every bar of every TreeScanner hunt.
- Fix: Read all three regime states from the structured form (`trend_regime["state"]`, `volatility_regime["state"]`, `correlation_regime["state"]`) with fallback to the top-level backward-compat keys (`trend`, `volatility`). 6 new tests in `tests/test_discovery_regime_features.py` cover the fix path AND the legacy fallback path.

### [MEDIUM] Engine D has duplicate, drifting WFO orchestrators (evolution_controller and validate_candidate)
- Engine: D + F (charter boundary issue — `evolution_controller.py` lives in `engine_f_governance/` but does Engine D work)
- First flagged: 2026-04-28
- Status: **awaiting user decision** — `validate_candidate` WFO is now correctly wired; `evolution_controller.py` is confirmed dead code (zero importers in `engines/`, `orchestration/`, `scripts/`).
- Description: `engines/engine_f_governance/evolution_controller.py` implements a complete validate-from-registry-with-WFO pipeline (`run_cycle`, `run_wfo_for_candidate`). Until commit 8ee8289 it was the only WFO orchestrator with a correct interface — `discovery.py::validate_candidate` was broken. After 8ee8289, validate_candidate is canonical and works; evolution_controller.py is unused. Its module location violates the charter (Engine D work in F's package).
- Charter reference: engine_charters.md Engine F Forbidden Inputs: "Edge discovery, parameter optimization, or walk-forward testing (that's D's job)."
- Recommended next step: User decision required — moving the file is a charter-boundary change which CLAUDE.md classifies as propose-first. Recommend archiving to `Archive/engine_f_governance/evolution_controller.py` since validate_candidate is now the canonical path. Alternative: keep evolution_controller as a future migration target if you want a more structured WFO orchestrator separate from validate_candidate.

### [MEDIUM] Engine D bare `except Exception` blocks routinely mask interface-drift bugs
- Engine: D
- First flagged: 2026-04-28
- Status: not started
- Description: `discovery.py::validate_candidate` contains 6 bare `except Exception as e: print(...)` blocks at lines 680, 727, 758, 769, 812, 871 — one for each gate plus the outer wrapper. Each catches programmer errors (TypeError, AttributeError, missing-method) on equal footing with legitimate runtime issues (data unavailability, file IO). This pattern is what hid all three bugs the user just fixed in commit dda474c, AND it is hiding the two HIGH findings above (Gate 3 and Gate 5). The print messages do not include exception type or traceback, so the user cannot distinguish "Gate 3 had no data this run" from "Gate 3 has been broken for weeks." `tree_scanner.py:178, 233, 257` and `wfo.py:48-53` (also `try: get_loc(method='nearest') except: start_idx = 0`) follow the same pattern — bare except, default value, silent continuation.
- Charter reference: Charter Invariant 5 (Engine D): "D's research is fully reproducible given the same data and random seeds." Silent gate-skip violates reproducibility — outcome depends on whether the masked exception fires.
- Recommended next step: Replace each bare `except Exception` with `except (RuntimeError, KeyError, FileNotFoundError) as e:` (or a similar narrow set), and add a final `except Exception:` at the top level that logs the traceback. Programmer errors should propagate; data errors should fail the gate explicitly with `result["gate_X_passed"] = False` not silently default to a passing value. Also, `wfo.py:49` uses the deprecated `get_loc(method='nearest')` API which has been removed in pandas ≥1.4 — the bare except masks an `InvalidIndexError` and falls back to `start_idx = 0`, meaning every WFO run starts from bar 0 regardless of `start_date`.

### [MEDIUM → RESOLVED 2026-04-28] Engine D wfo.py uses deprecated `get_loc(method='nearest')` API
- Engine: D
- First flagged: 2026-04-28
- Status: **resolved 2026-04-28** — switched to `get_indexer` (commit 8ee8289 item 4)
- Description: `wfo.py:49` calls `full_timeline.get_loc(start_dt, method='nearest')`. The `method` parameter was deprecated in pandas 1.4 and removed in pandas 2.0+. On any recent pandas, this raises `TypeError: get_loc() got an unexpected keyword argument 'method'`. The bare `except: start_idx = 0` at line 52 catches it, so every WFO call starts at bar 0 of the timeline — `start_date` is silently ignored. Combined with the Gate 3 interface mismatch above, the production discovery path never reaches this line, so the bug has been latent. But `evolution_controller.run_wfo_for_candidate` (the working orchestrator) DOES reach it — meaning when that path is exercised, all WFO runs use full-history training despite the caller specifying a recent start date.
- Charter reference: "Walk-forward optimization, OOS/IS degradation ratio" (engine_charters.md, Engine D Modules table). Walk-forward by definition requires honoring the rolling window start.
- Recommended next step: Replace with `full_timeline.get_indexer([start_dt], method='nearest')[0]` (or `np.argmin(np.abs(full_timeline - start_dt))` for clarity). Remove the bare except — if the date is unparseable, the run should fail loudly.

### [LOW] Engine D save_candidates uses print() instead of structured logger; conflicts with DiscoveryLogger
- Engine: D
- First flagged: 2026-04-28
- Status: not started
- Description: `discovery.py:475, 492, 513` and the gate-result lines at 678, 685, 728, 759, 770, 813, 852, 854 use `print()` for diagnostic output, while the module already has `DiscoveryLogger` (jsonl audit trail) and a module-level `logger = logging.getLogger("DISCOVERY")`. Inconsistent emission means the gate failures we just diagnosed are visible only as stdout in the discovery cycle log file, not in the structured `discovery_log.jsonl` that downstream tools (and the cockpit) consume. The user's diagnosis of the three bugs in commit dda474c required reading the raw stdout — DiscoveryLogger only sees the final pass/fail, not the gate-skip reason.
- Charter reference: Engine D index.md: "JSONL audit logging of all discovery activity" (`discovery_logger.py` purpose).
- Recommended next step: Route gate-result diagnostics through `DiscoveryLogger.log_validation` (extend the schema with `gate_skipped_reason: Optional[str]`), or at minimum through `logger.warning(...)` so it lands in `evolution.log`. Stop printing.

### [HIGH] System Sharpe 0.4 on 109-ticker universe vs SPY 0.88 in-sample
- Engine: System-level (Alpha + Risk + Portfolio composition)
- First flagged: 2026-04-25
- Status: **partially resolved — 0.855 figure is pre-lifecycle, not a stable baseline**
- Description: Universe expansion from 39 to 109 tickers exposed that the system underperforms SPY by ~0.5 Sharpe on a broader equity universe. The previously-reported Sharpe 0.979 was a curated-mega-cap-tech artifact. Existing edges don't generalize beyond the original 39 names; lifecycle correctly paused 2 of 14 (`atr_breakout_v1`, `momentum_edge_v1`) but no replacement alpha was queued.
- 2026-04-27 Phase 2.10 full backtest result: **Sharpe 0.855** (run d134e488) — but this was the run that GENERATED the lifecycle pause decisions. `atr_breakout_v1` (weight 2.5) and `momentum_edge_v1` (weight 1.5) were still at full weight during this run and contributed +$2,694 and +$1,569 respectively. Post-pause, subsequent in-sample runs show Sharpe 0.161–0.677 depending on governor learned-affinity state.
- 2026-04-28 in-sample re-run with paused edges at 0.25x soft-pause: **Sharpe 0.161** (run daf4ad4d). Per-edge breakdown shows `momentum_edge_v1` went from +$1,569 to -$888 at reduced weight; `gap_fill_v1` went from +$151 to -$1,080; "Unknown" exit losses went from -$3,681 to -$11,241. Governor learned-affinity state is a significant contributor to variance between runs.
- **2026-04-28 operational baseline established**: `--no-governor` (0.264) and neutral-governor + weight-cap (0.256) both confirm post-lifecycle Sharpe of **~0.26**. SPY 2021-2024 Sharpe is 0.875 — gap is **-0.619**. This is larger than the pre-Phase-2.10 gap (0.875 - 0.403 = 0.472), because the Phase 2.10 macro edges barely fire in-sample (macro_credit_spread: 0 trades, most others 0-3 trades) and some lose (macro_yield_curve: -$784 from 157 trades). The alpha is concentrated in atr_breakout (soft-paused) and volume_anomaly/herding (unchanged from before Phase 2.10).
- Per-edge breakdown of neutral-governor run (e5055f4e): atr_breakout +$7,988 (2188 trades at 0.5 cap), volume_anomaly +$5,176 (77 trades), herding +$2,119 (49 trades). "Unknown" exit losses: -$14,832 (885 exits, likely atr_breakout stops). All Phase 2.10 macro edges either silent or losing.
- **2026-04-28 (session 3) walk-forward year-by-year results** (`walk_forward_phase210.py`): 0/4 years beat SPY. 2021: sys 0.455 vs SPY 2.133 (delta -1.678); 2022: sys -0.844 vs SPY -0.735 (delta -0.109, worse in bear); 2023: sys 1.167 vs SPY 1.896 (delta -0.729); 2024: sys 1.048 vs SPY 1.882 (delta -0.834). Mean delta: **-0.837**. No year-specific anomaly — uniform structural underperformance. 2022 result is particularly damning: system loses MORE than SPY in the bear year (no defensive value). Paused edges (atr_breakout, momentum_edge) dominate portfolio even at soft-pause weight, with active macro/PEAD edges contributing near-zero.
- **2026-04-28 (session 3) attribution bug fixed**: "Unknown" exit losses (-$14,832) were attribution failures from soft-paused edges where `norm*weight < min_edge_contribution=0.05`. Fixed `_prepare_orders` in `backtest_controller.py` to fall back to signal's top-level `edge` field when `edges_triggered` is empty. Also fixed double version suffix bug in `alpha_engine.py::_edge_meta_from_detail`. Loss is real (momentum_edge_v1 at soft-pause weight); fix only corrects governance metrics reporting, not Sharpe.
- **2026-04-28 (session 3) autonomous discovery cycle launched**: `PYTHONHASHSEED=0 PYTHONPATH=. python -m scripts.run_backtest --discover` running. Discovery phase begins after in-sample backtest completes. Expected: hunt + generate candidates + 5-gate validation with BH-FDR. Prior cycle had 132/133 failures — GA fitness was optimizing for in-sample Sharpe which the gauntlet kills. This run uses same GA fitness (ROADMAP plan item 6B — OOS fitness — not yet implemented). Not expecting promotions.
- Remaining gap: **-0.837 mean Sharpe delta vs SPY (year-by-year)**. The edge pool has no alpha that fires reliably at deployment weights across multiple years. Gap is uniform, not year-specific. Closing it requires new alpha sources, not weight tuning. Autonomous discovery cycle is the next mechanism.
- Recommended next step: (1) Wait for discovery cycle results; (2) implement ROADMAP item 6B (GA fitness = 0.5*OOS_Sharpe + 0.3*(1-PBO) + 0.2*(OOS/IS)) so the next cycle optimizes for what the gauntlet rewards; (3) discovery is generating candidates but the fitness function needs to align with the validation gauntlet.
- See: `docs/Sessions/2026-04-27_session.md`, commits dfb0627, f06afb2-b1928c9, aa1cb65, da196b1, 1600e45, 53d5c07, 7db6625, 45abf0e, efbdf8d. Also `scripts/walk_forward_phase210.py`.

### MEDIUM

### [MEDIUM] Engine F has a duplicate orchestrator `system_governor.py` (653 lines) that no production path calls
- Engine: F
- First flagged: 2026-04-28
- Status: not started
- Description: `engines/engine_f_governance/system_governor.py` defines a 653-line `SystemGovernor` class that orchestrates the same loop as `StrategyGovernor.update_from_trade_log` — read trades, compute edge metrics, update weights, persist to `data/governor/edge_weights.json`, append history. It has its own CLI entry (`python -m engines.engine_f_governance.system_governor --once / --watch`) and its own dataclass-based config. Grep across the entire repo shows: every production caller (`mode_controller`, `alpha_engine`, `analytics.edge_feedback`, `scripts.system_validity_check`) imports `StrategyGovernor` from `governor.py`. **Nothing imports `SystemGovernor`** — only the file's own `__main__` runs it. This is the textbook `governor.py` + `system_governor.py` duplicate-with-similar-name pattern called out in the code-health checklist. It also accumulates its own bare-except blocks (29 of them) which represent a separate, drifting maintenance burden.
- Files: `engines/engine_f_governance/system_governor.py` (the dead one), `engines/engine_f_governance/governor.py` (the canonical one)
- Recommended next step: Move `system_governor.py` to `Archive/engine_f_governance_legacy/system_governor_2026_04_28.py`. If the `--watch`/polling daemon mode is still wanted, port that one feature onto `StrategyGovernor` as a small CLI wrapper (`scripts/governor_daemon.py`) instead of carrying a 653-line shadow implementation. Verify nothing in `cron`, `launchd`, or live_trader/ shells out to `python -m engines.engine_f_governance.system_governor` before archiving.

### [MEDIUM] Engine A signal_collector silently returns `{}` when an edge defines a typo'd method — same failure class as the just-fixed `check_signal` vs `compute_signals` bug
- Engine: A
- First flagged: 2026-04-28
- Status: not started
- Description: `SignalCollector._call_edge` (signal_collector.py:23-103) tries four method-name dispatches in order: module-level `compute_signals`, module-level `generate_signals`, class instance with `compute_signals`, class instance with `generate_signals`. Each layer is wrapped in `except Exception as inst_err: …` that only emits a print under `is_debug_enabled("COLLECTOR")` (off in production). If an edge author defines `_compute_signals` (private), or `compute_signal` (singular), or any other typo, the collector falls all the way through and returns `{}` — the edge produces zero signals every bar with no warning. This is exactly the symptom of the `check_signal` vs `compute_signals` bug from the user's recent diagnosis: `RuleBasedEdge` only survives because it explicitly wraps `check_signal()` inside a `compute_signals()` method (rule_based_edge.py:72-89). Any edge that ships with the wrong method name today is invisible. Worse, the dispatch order means a class with both `compute_signals` and `generate_signals` will always use `compute_signals` regardless of what the author intended (edges like `xsec_momentum.py` define both, with subtly different return shapes — class.compute_signals returns a `dict[str, float]`; the module-level `compute_signals` at line 181 returns a `list[dict]`, so the dispatcher's choice silently determines the contract).
- Files: `engines/engine_a_alpha/signal_collector.py:23-103`, `engines/engine_a_alpha/edges/xsec_momentum.py:31, 139, 181` (triple-defined `compute_signals` — module-level convenience function shadows the class method).
- Recommended next step: At AlphaEngine startup, validate every registered edge has exactly one of `compute_signals` or `generate_signals` callable, and log a `WARNING` for any edge that has neither. Make the bare-excepts in `_call_edge` re-raise `AttributeError` and `TypeError` so a typo manifests as a startup failure, not a silent zero-signal day. Separately, resolve the `xsec_momentum.py` triple-define: either delete the module-level `compute_signals` (lines 173-187) or document why it exists.

### [MEDIUM] Charter inversion: Engine A signal_processor imports EDGE_CATEGORY_MAP from Engine F's regime_tracker
- Engine: A (with import dependency on F)
- First flagged: 2026-04-28
- Status: not started
- Description: `engines/engine_a_alpha/signal_processor.py:27` does `from engines.engine_f_governance.regime_tracker import EDGE_CATEGORY_MAP`. EDGE_CATEGORY_MAP is a taxonomy mapping edge name patterns to category labels (`"momentum"`, `"mean_reversion"`, etc.) used by SignalProcessor for the learned-affinity multiplier. Per `engine_charters.md`, Engine A produces signals; Engine F governs lifecycle. A should not depend on F's internal data structures at module-import time — that creates a cycle of intent: SignalProcessor's behaviour now depends on whether F has loaded its tracker module, which means refactoring F's tracker can break A's signal aggregation. The proper layering is for the taxonomy to live in `engines/engine_a_alpha/` (where the edges live) or in `core/` as a shared resource, with F consuming it. Today it lives in F because F was the first to need it for affinity tracking, and A grew an after-the-fact dependency. This is a smaller version of the same charter-inversion that flagged `evolution_controller.py` in F (existing finding above): a piece of the system is in the wrong package, and the dependency direction is reversed from what the charter intends.
- Charter reference: engine_charters.md Engine A: "Generates buy/sell signals." Engine F: "Lifecycle, governance, weight learning." Authority Boundaries imply A precedes F in the data flow — A should not import F.
- Files: `engines/engine_a_alpha/signal_processor.py:27`, `engines/engine_f_governance/regime_tracker.py` (where EDGE_CATEGORY_MAP is defined)
- Recommended next step: Move `EDGE_CATEGORY_MAP` to `engines/engine_a_alpha/edge_taxonomy.py` (new small module), import it from there in both `signal_processor.py` and `regime_tracker.py`. Same content, correct dependency direction. While there, check whether `EDGE_CATEGORY_MAP` is the right shape — it currently has the orphan `"rsi_mean_reversion"` entry referenced in the HIGH finding above.

### [MEDIUM] Soft-paused edges with high alpha_settings weights still dominate signal ensemble
- Engine: A (AlphaEngine / SignalProcessor) + F (lifecycle soft-pause design)
- First flagged: 2026-04-28
- Status: **resolved 2026-04-28** — `PAUSED_MAX_WEIGHT = 0.5` cap added (commit 93411be)
- Description: The soft-pause 0.25x multiplier is applied to the edge's pre-pause alpha_settings weight. `atr_breakout_v1` at weight 2.5 → 0.625 after soft-pause, still above most active edges at 0.5-1.0. Caused atr_breakout to generate 2371 trades in the 2026-04-28 in-sample run (vs 51 for volume_anomaly at weight 1.0) and drive "Unknown" exit losses to -$11K. Fix: added `PAUSED_MAX_WEIGHT = 0.5` cap in `mode_controller.py` after the multiplier — paused edges can now be at most `min(weight × 0.25, 0.5)`. For atr_breakout: min(0.625, 0.5) = 0.5, below active edges at 1.0. Does not affect edges whose pre-pause weight was ≤ 2.0 (they stay below 0.5 after multiplier).

### [MEDIUM] Governor learned-affinity from OOS runs contaminates subsequent in-sample backtests
- Engine: F (Governor — `data/governor/edge_weights.json` persistence)
- First flagged: 2026-04-28
- Status: **resolved 2026-04-28** — `--reset-governor` flag shipped
- Description: `edge_weights.json` (the governor's learned SR-based affinity per edge) persists across runs. When OOS backtests run first (especially on adversarial windows like 2025 data), the governor downgrades edge weights that underperform in OOS. Loading those downgraded weights into a subsequent in-sample run injects forward-looking signal: the governor "knows" which edges struggled in 2025 and suppresses them in the 2021-2024 window where they were profitable. Observed 2026-04-28: governor-enabled in-sample run got Sharpe 0.161 vs 0.264 with `--no-governor` — the difference is -0.103 Sharpe from stale/wrong affinity. Resetting to neutral (all weights = 1.0) before in-sample runs restores correct behavior.
- Fix: `StrategyGovernor.reset_weights()` clears `_weights` and `_regime_weights` to empty (→ all edges default to 1.0 in `get_edge_weights()`). Does NOT write to disk — persisted production state is unchanged. Exposed as `--reset-governor` flag in `scripts/run_backtest.py` and `reset_governor=True` parameter in `run_backtest_logic()`. 4 tests in `tests/test_governor_reset.py` cover: clears in-memory weights, does not touch disk, clears regime weights, idempotent. Use: `PYTHONHASHSEED=0 python -m scripts.run_backtest --reset-governor` for clean in-sample measurement.

### [MEDIUM] Soft-paused edges at 0.25x are primary driver of 2025 OOS underperformance
- Engine: F (Governance — lifecycle soft-pause weight policy)
- First flagged: 2026-04-28
- Status: **partially resolved 2026-04-28** — paused→retired path added (commit 1dca4a5)
- Description: 2025 OOS backtest (2025-01-01 → 2026-04-17) shows Sharpe 0.173 vs SPY 0.975. Root cause: `atr_breakout_v1` and `momentum_edge_v1` are soft-paused at 0.25x weight, but still generate 3082 + 1642 = 4724 fills and lose -$3,357 + -$1,208 = -$4,565 combined. The positive Phase 2.10 edges generate only +$3,556 total. The paused edges had no lifecycle exit path — they could only revive or stay paused forever.
- 2026-04-28 partial fix: `LifecycleManager` now has a `paused → retired` transition gate. After `paused_retirement_min_days` (default 90 days), if an edge remains benchmark-negative and is not currently reviving, it gets retired rather than accumulating 0.25x losses indefinitely. 4 new tests, 19/19 lifecycle tests pass.
- Remaining gap: The 2025 OOS backtest result won't change until the in-sample run fires the retirement (next run with lifecycle=True against 2021-2024 data). After that run, both edges will retire at the 2024-12-31 evaluation point and won't be loaded in the 2025 OOS at all.

### [MEDIUM] Earnings backend swapped Finnhub → yfinance — PEAD now has training data
- Engine: A (data_manager — `engines/data_manager/earnings_data.py`)
- First flagged: 2026-04-25
- Status: resolved-but-noted — swap done, cache re-bootstrapped
- Description: Finnhub's free tier was confirmed (2026-04-25) to return 0 historical earnings — per-symbol queries return empty regardless of window, and the unfiltered calendar exposes only the last ~30 days. With Finnhub as the backend, `pead_edge.py` had no historical training data and was functionally inert. Swapped backend to yfinance which exposes ~25 quarters per ticker with `EPS Estimate`, `Reported EPS`, and computed surprise %. Re-bootstrapped on 115-ticker universe → 109 with events, 6 empty (ETFs / BRK.B), 0 failed, 2698 total events. PEAD edge confirmed live (NVDA 2024-02-21 +13% surprise → signal 0.127 day +1, decays linearly to 0 at day 90). `FINNHUB_API_KEY` retained in `.env` for possible real-time use during paper trading; no longer consumed by `EarningsDataManager`. Old Finnhub cache archived at `data/Archive_earnings_finnhub_2026_04_25/`.
- Recommended next step: monitor — yfinance scraping has known reliability issues; if it degrades, the manager already falls back to cache so backtests stay reproducible. No further action unless cache rebuilds start failing.
- See: `memory/project_finnhub_free_tier_no_historical_2026_04_25.md`, `tests/test_earnings_data.py`.

### [MEDIUM] signal_processor lacks conditional-weight composition for regime-conditional edges
- Engine: A (signal_processor)
- First flagged: 2026-04-25
- Status: **resolved 2026-04-27** — regime_gate primitive shipped (commit aa1cb65)
- Description: Resolved. `SignalProcessor` now accepts `regime_gates: Dict[str, Dict[str, float]]` in its constructor. Per-edge gate maps Engine E `regime_summary` labels ("benign", "stressed", "crisis") to weight multipliers [0,1]. Gate multiplies `w` in the weighted-mean aggregation; missing labels default to 1.0; `regime_meta=None` defaults to "benign". `low_vol_factor_v1` re-enabled at weight 0.5 with gate `{benign:0.15, stressed:1.0, crisis:1.0}`. 8 new tests in `tests/test_signal_processor_regime_gate.py` covering all edge cases.
- See: commit aa1cb65, `tests/test_signal_processor_regime_gate.py`, `data/governor/edges.yml` (low_vol_factor_v1 entry).

### LOW

### [LOW] Lifecycle must not modify edge statuses during OOS backtesting
- Engine: F (Governance) + backtesting methodology
- First flagged: 2026-04-28
- Status: **resolved 2026-04-28** — `lifecycle_readonly` mode shipped
- Description: Running lifecycle on the same OOS window multiple times caused a cascade: each run retired more edges that underperformed in that window, making the result non-reproducible. Fixed by adding `LifecycleConfig.readonly: bool = False`. When `True`, all gate evaluations run and events are returned, but `_save_registry()` and `_append_history()` are skipped — the same OOS window always produces the same result regardless of how many times it's run.
- Wire-up: `GovernorConfig.lifecycle_readonly: bool = False` added; `governor_settings.json` carries the key. Set `lifecycle_readonly: true` in governor_settings to enter OOS measurement mode. 2 new tests in `tests/test_lifecycle_manager.py` (21/21 pass): `test_readonly_mode_does_not_write_registry`, `test_readonly_mode_does_not_append_history`.

---

## Resolved (last 90 days)

### [MEDIUM] Lifecycle audit-trail / registry-state divergence detection missing (2026-04-25)
- Engine: F (Governance)
- Resolved: 2026-04-27
- Description: `LifecycleManager._audit_registry_divergence_check()` was shipped as part of "Phase α v3" (committed before 2026-04-27 session). At the top of `evaluate()`, it reads `lifecycle_history.csv`, extracts the most recent `new_status` per edge via `groupby("edge_id").last()`, then compares against the current registry status in `edges.yml`. Any disagreement logs a `WARNING` with edge_id, audit_trail value, registry value, and a bug-class label (`status_reverted` or `missing_from_registry`). The check is wrapped in `try/except` so it cannot break the lifecycle loop — observability only, not gating. 6 unit tests in `tests/test_lifecycle_manager.py` cover: no-op on empty history, no-op when audit and registry agree, flags status_reverted, flags missing_from_registry, uses most-recent-event correctly, runs silently when evaluate() is called with divergence present.
- See: `engines/engine_f_governance/lifecycle_manager.py::_audit_registry_divergence_check` (lines 357-449), `tests/test_lifecycle_manager.py` lines 292-420.

### [MEDIUM] Engine D's GA gene vocabulary searches a strip-mined space (2026-04-24)
- Engine: D (Discovery)
- Resolved: 2026-04-27
- Description: `CompositeEdge` now evaluates `"macro"` (10% probability — T10Y2Y yield curve, VIX level, UNRATE unemployment delta) and `"earnings"` (5% — EPS surprise % look-back) gene types. Both use lazy instance-level caching. Gene vocabulary weights: technical 40%→35%, regime 10%→5%, fundamental 15%→10%. GA now discovers macro-conditional and earnings-event combinations.
- See: commit 45abf0e, `tests/test_composite_edge_macro_earnings.py`.

### [HIGH → RESOLVED 2026-04-25] EdgeRegistry.ensure() silently overrode lifecycle status (2026-04-25)
- Engine: A (EdgeRegistry, used by F's lifecycle)
- Status: **resolved 2026-04-25** — `ensure()` write-protects `status` per edges.yml Write Contract; `tests/test_edge_registry.py` is the regression check
- Resolved: 2026-04-25
- Description: Auto-register-on-import code (`momentum_edge.py:64`, `momentum_factor_edge.py:113`) called `EdgeRegistry().ensure(EdgeSpec(..., status="active"))`. Pre-fix `ensure()` had `if spec.status: s.status = spec.status` — the comment claimed "keep status as-is unless provided" but `EdgeSpec.status` defaults to `"active"` so callers always provided it. Effect: every backtest startup imported `momentum_edge.py` → reverted any lifecycle-applied pause/retire on `momentum_edge_v1` back to `active`. Visible only as repeated identical pause events in `lifecycle_history.csv` across runs. `atr_breakout_v1` escaped because `atr_breakout.py` has no auto-register block, which is why the "first autonomous pause" finding from 2026-04-24 felt real (it was — for atr_breakout). Discovered today via the methodology rule "bitwise-identical canon md5 when expecting change is diagnostic evidence."
- Fix: `EdgeRegistry.ensure()` now write-protects `status` for existing specs, per the `edges.yml` Write Contract documented in `PROJECT_CONTEXT.md` ("F writes: status field changes — neither engine deletes the other's fields"). Added `tests/test_edge_registry.py` with 12 tests including `test_repro_momentum_edge_import_does_not_revive_paused` as a permanent regression check.
- See: `memory/project_registry_status_stomp_bug_2026_04_25.md`, `docs/State/lessons_learned.md` 2026-04-25 entry, `tests/test_edge_registry.py`.

---

## Archived (older than 90 days)

When resolved items pass 90 days, move them here. Keep this section 
trimmed — if it grows beyond ~50 items, archive the oldest to 
`docs/Archive/audits/health_check_resolved_<year>.md`.

*No archived findings yet.*

---

## Severity guide

- **HIGH**: Actively breaks things or causes silent harm. Examples: 
  broken imports still being called, deprecated paths in active use, 
  bugs that produce wrong outputs, code that bypasses charter 
  boundaries in ways that affect runtime behavior.
- **MEDIUM**: Structural debt that doesn't break the system today 
  but compounds. Examples: god classes (>500 lines), duplicate 
  implementations, oversized functions (>200 lines), missing test 
  coverage on critical paths, charter drift that hasn't yet caused 
  visible problems.
- **LOW**: Hygiene issues. Examples: stale TODOs (>90 days), unused 
  imports, empty test stubs, formatting inconsistencies, outdated 
  comments.

## Format

Findings appended by subagents follow one of two formats:

**From engine-auditor:**
```
### [SEVERITY] <one-line summary>
- Engine: <A/B/C/D/E/F>
- First flagged: <YYYY-MM-DD>
- Status: not started
- Description: <what's wrong>
- Charter reference: <quote or section from engine_charters.md>
- Recommended next step: <specific action>
```

**From code-health:**
```
### [SEVERITY] <one-line summary>
- Category: <duplicate/god-class/dead-code/stale-todo/other>
- Files: <path(s)>
- First flagged: <YYYY-MM-DD>
- Status: not started
- Recommended next step: <specific action>
```

When a finding is resolved, move the entry to the Resolved section 
and add a `- Resolved: <YYYY-MM-DD>` line.
---

## Code-health scan 2026-05-06 — post-V/Q/A merge (code-health subagent)

Scope: Engine A (6 new SimFin V/Q/A edges + signal_processor + fill_share_capper),
Engine E (HMM panel + cross_asset_confirm + transition_warning), Engine C
(HRP + sleeves), Engine D (gauntlet architectural fix), core/feature_foundry,
core/observability (net-new), engines/data_manager/fundamentals/simfin_adapter,
scripts/path_c_synthetic_compounder, scripts/run_multi_year, scripts/run_isolated.
Prior was tilted toward bare-except / silent-cache / dict-iteration patterns
because the past week surfaced 2 Path C bugs in those families.

Severity counts: HIGH 3 | MEDIUM 6 | LOW 4. Top-3 highest-impact below.

### [HIGH → RESOLVED 2026-05-06] Negative-equity ROIC silently zeros the denominator — distressed firms inflate to top-quintile rank
- Category: silent-correctness / signal-quality bug
- Files:
  - `engines/engine_a_alpha/edges/quality_roic_edge.py:87-88` (NEW edge, just shipped)
  - `scripts/path_c_synthetic_compounder.py:663-664` (Path C real-fundamentals composite)
- First flagged: 2026-05-06
- **Status: RESOLVED 2026-05-06.** Branch `vqa-edges-bugfixes` commit `6c9b4af`. Fix mirrors `value_book_to_market_edge`'s explicit `equity <= 0 → return None` in both `quality_roic_edge.compute_signals` and `path_c_synthetic_compounder.compute_composite_score_real`. Regression test `test_quality_roic_drops_negative_equity_ticker` synthesizes a negative-equity firm and asserts it is dropped from the cross-section before quintile selection. See audit `docs/Measurements/2026-05/vqa_edges_bugfix_2026_05_06.md`.
- Description: ROIC denominator is computed as
  `invested_capital = (equity if equity > 0 else 0.0) + (lt_debt if lt_debt > 0 else 0.0)`.
  A firm with negative equity (deeply distressed) thus has its equity component
  silently treated as 0, and ROIC = `NOPAT / lt_debt`. That denominator is small,
  so distressed firms can score a *very high* ROIC and end up in the top
  quintile of the long-only Quality factor — the opposite of what the academic
  factor (Asness-Frazzini-Pedersen "Quality Minus Junk") prescribes. Compare
  to `value_book_to_market_edge.py:76-78` four files away in the same package,
  which correctly drops negative-equity firms with an explicit `return None`
  and the comment "Negative-equity firms produce misleading signs for B/P".
  The same silent-zero pattern is duplicated in the Path C compounder's
  `compute_composite_score_real` at line 663, so any historical Path C
  result that scored a near-bankrupt firm into the top quintile is suspect.
  This was unflagged on the 2024 smoke test (canon `4ae83833f6d5a35a...`)
  because the prod 109-ticker universe is mostly mature mega-caps with
  positive equity — but the next universe expansion (Workstream H, growing
  past 109) increases the probability of a negative-equity name in the panel.
- Recommended next step: In both sites, return `None` (drop the ticker) when
  `equity is None or equity <= 0`. The contract should match
  `value_book_to_market_edge.py`'s explicit comment. Add a regression test in
  `tests/test_fundamentals_edges.py` with a synthetic negative-equity ticker
  asserting it is dropped from `quality_roic_v1`'s top-quintile.

### [HIGH → RESOLVED 2026-05-06] `top_quintile_long_signals` swallows ALL exceptions inside the score function — every new V/Q/A edge inherits the silent-bug pattern
- Category: bare-except / silent failure
- Files: `engines/engine_a_alpha/edges/_fundamentals_helpers.py:205-208`
- First flagged: 2026-05-06
- **Status: RESOLVED 2026-05-06.** Branch `vqa-edges-bugfixes` commit `6c9b4af`. The bare `except Exception` is replaced with two narrowed tuples — `_PROGRAMMER_ERRORS = (AttributeError, NameError, ImportError, SyntaxError, AssertionError)` re-raises so bugs surface, `_DATA_MISSING_ERRORS = (KeyError, IndexError, ValueError, ZeroDivisionError, TypeError)` is suppressed and DEBUG-logged with ticker + edge_id + exception type. Tests `test_helper_reraises_attribute_error_from_score_fn` and `test_helper_suppresses_value_error_from_score_fn` lock the contract. See audit `docs/Measurements/2026-05/vqa_edges_bugfix_2026_05_06.md`.
- Description: The shared helper that all 6 new SimFin V/Q/A edges use has a
  bare `except Exception: raw = None` around the per-ticker score callable.
  Programmer errors in any score function — `TypeError` from a bad pandas
  operation, `AttributeError` from a method-name typo, `KeyError` from a
  panel-column rename, `ImportError` from a moved helper — are caught
  identically to legitimate data-missing cases and quietly turn into "this
  ticker has no signal." All 6 edges (`value_earnings_yield_v1`,
  `value_book_to_market_v1`, `quality_roic_v1`, `quality_gross_profitability_v1`,
  `accruals_inv_sloan_v1`, `accruals_inv_asset_growth_v1`) share this code
  path. The 2024 smoke result showed all 6 firing — that result tells you
  the happy path works; it tells you nothing about whether the gauntlet of
  exception types are being silenced. This is the same failure mode the
  prior memory `project_gauntlet_consolidated_fix_2026_05_01` documents in
  Engine D (gates 1-6 hid 5 distinct bugs behind bare-excepts for weeks).
- Recommended next step: Narrow the catch to `except (KeyError,
  IndexError, ValueError, ZeroDivisionError) as exc:` (the legitimate
  data-shape exceptions a score_fn might raise on a sparse SimFin slice),
  log the exception class+message at DEBUG level when raw is None, and let
  `TypeError` / `AttributeError` / `ImportError` propagate. This is the
  single change that has the largest downside-prevention surface across
  the 6 new edges.

### [HIGH → RESOLVED 2026-05-06] All 6 new V/Q/A edge auto-register blocks swallow EdgeRegistry errors silently
- Category: bare-except / silent-state / status-stomp risk
- Files:
  - `engines/engine_a_alpha/edges/value_earnings_yield_edge.py:101-112`
  - `engines/engine_a_alpha/edges/value_book_to_market_edge.py:94-105`
  - `engines/engine_a_alpha/edges/quality_roic_edge.py:105-116`
  - `engines/engine_a_alpha/edges/quality_gross_profitability_edge.py:84-95`
  - `engines/engine_a_alpha/edges/accruals_inv_sloan_edge.py:100-111`
  - `engines/engine_a_alpha/edges/accruals_inv_asset_growth_edge.py:93-104`
- First flagged: 2026-05-06
- **Status: RESOLVED 2026-05-06.** Branch `vqa-edges-bugfixes` commit `6c9b4af`. All 6 auto-register blocks narrowed to `except (FileNotFoundError, PermissionError, OSError) as exc` with WARNING-level log. A future `EdgeSpec` schema-drift `TypeError` or registry-write `RuntimeError` now propagates so the AlphaEngine never loads an edge whose spec failed to install. Tests `test_auto_register_propagates_programmer_errors` (TypeError raised by mocked `ensure()` propagates on importlib.reload) and `test_auto_register_swallows_io_error` (FileNotFoundError degrades gracefully + WARNING log captured) lock the contract. See audit `docs/Measurements/2026-05/vqa_edges_bugfix_2026_05_06.md`.
- Description: Every new edge ends with the same pattern:
  ```python
  try:
      _reg = EdgeRegistry()
      _reg.ensure(EdgeSpec(... status="active"))
  except Exception:
      pass
  ```
  Memory entry `project_registry_status_stomp_bug_2026_04_25.md` documents that
  the EdgeRegistry's `ensure()` was previously stomping pause/retire decisions
  silently — exactly because callers (every edge module) auto-register at
  import. The 04-25 fix made `ensure()` write-protect status; OK. But the
  bare `except Exception: pass` in the call site means: if the registry file
  is locked (concurrent backtest in another worktree), corrupted, or a future
  schema change to `EdgeSpec` breaks the constructor, the 6 new edges will
  silently fail to register but the import will succeed. AlphaEngine will
  load them as classes, the lifecycle layer won't see the spec, and
  `EdgeRegistry.get_all_specs()` will return a registry that's missing 6
  edges. The lifecycle audit divergence check is the only thing that would
  catch this — and only if it runs on a corrupt-registry scenario.
- Recommended next step: Either narrow the catch to `except (FileNotFoundError,
  PermissionError, yaml.YAMLError) as exc: log.warning(f"... auto-register
  skipped: {type(exc).__name__}: {exc}")` so a missing data dir during test
  runs degrades gracefully but a programmer error fails loudly, OR move the
  auto-register to `EdgeRegistry`'s own scan-on-startup so the duplication
  goes away entirely. Latter is the structurally cleaner fix and aligns
  with the `EdgeRegistry` charter.

### [MEDIUM] cross_asset_confirm.py is a soft-archive candidate — disabled-by-default, validation showed it as coincident-noise
- Category: dead-code / archive candidate
- Files: `engines/engine_e_regime/cross_asset_confirm.py` (183 lines),
  `engines/engine_e_regime/regime_config.py:185-205` (the `CrossAssetConfirmConfig`
  dataclass), `tests/test_ws_c_cross_asset.py` (582+ lines of tests)
- First flagged: 2026-05-06
- Status: not started
- Description: `cross_asset_confirm.py` is gated behind
  `cross_asset_confirm_enabled: bool = False` (regime_config.py:204) and the
  only non-test importer is `regime_detector.py:565` (lazy-import inside a
  try-except, never reached when the flag is off). The recent regime
  validation `docs/Measurements/2026-05/regime_signal_validation_2026_05_06.md`
  concluded the underlying signals are coincident, not predictive
  ("Verdict: Branch 3 — NOISE. Do NOT scope Engine B integration"). The
  module ships ~183 lines of code, ~25 lines of config, and 582+ lines of
  tests for behavior that is intentionally never enabled. Production
  consumers are zero. This isn't strictly dead — `scripts/run_ws_c_smoke.py`
  flips the flag to test the gate runs end-to-end — but it's a "misleading
  standing reference" per CLAUDE.md, and the lessons_learned note from
  2026-05-05 explicitly documents "WS-C cross-asset is observability-only;
  do not measure by flipping flags."
- Recommended next step: User decision required because archiving touches
  the documented "observability-only" gate. Two options: (a) move
  `cross_asset_confirm.py` and the dataclass to `Archive/engine_e_regime/`
  with a redirect note in `engines/engine_e_regime/index.md` so future
  regime work doesn't rediscover the dead path, OR (b) keep it but add
  `# ARCHIVED-ON-DISABLE: per docs/Measurements/2026-05/regime_signal_validation_2026_05_06.md`
  at the top of the module as a header. (a) is cleaner and aligns with the
  charter that disabled features should not pollute the active-engine surface.

### [MEDIUM] `scripts/run_multi_year.py` per-year report assumes uniform rep counts — silent KeyError on heterogeneous failures
- Category: load-bearing harness fragility
- Files: `scripts/run_multi_year.py:77`, lines 84-106
- First flagged: 2026-05-06
- Status: not started
- Description: At line 77 the formatter computes
  `len(next(iter(by_year.values())))` to print "N years × M reps". This
  assumes all years have identical rep counts. If a single (year, rep) pair
  errored out (handled at line 206-213 and skipped via `[r for r in results
  if r.get("ok")]` at line 222), the surviving by_year buckets can have
  different lengths and the printed total is misleading. Worse, if ALL reps
  for a year fail, that year is silently dropped from `by_year` entirely,
  meaning the markdown table would not show any FAIL row for that year —
  the report's per-year coverage decays without alerting the reader.
  Separately, line 96's determinism check `det_pass = (sharpe_range <= 0.02
  and canon_unique == 1)` computes `sharpe_range` over only non-None Sharpes
  but `canon_unique` over all reps — so if rep 2 errored out and produced
  `trades_canon_md5 = "(no run_id)"` while reps 1 and 3 produced identical
  canons, `canon_unique = 2` and the run is wrongly flagged FAIL. This is
  the file the user explicitly called out as "load-bearing" (multi-year
  measurement is currently running). The bug doesn't corrupt measurement,
  but it can silently misreport the determinism floor.
- Recommended next step: (a) include FAILED runs in `_format_markdown_report`
  with explicit "FAIL — error: ..." rows so cross-year coverage is visible;
  (b) compute total by `sum(len(reps) for reps in by_year.values())` instead
  of assuming uniformity; (c) compute canon_unique only over reps where
  `ok=True` and `run_id != "?"`. Add a small unit test with a synthetic
  results list mixing failed and successful runs to lock the expected
  report shape.

### [MEDIUM] Engine D Gates 2/4/5/6 still use bare `except Exception` — 5 of 6 gates can silently default to "skipped" or "passing"
- Category: bare-except / silent-failure persistence after a known-fix
- Files: `engines/engine_d_discovery/discovery.py:975-976` (Gate 2),
  `:1006-1009` (Gate 3 — has the partial fix that re-raises TypeError /
  AttributeError, this is the model), `:1026-1027` (Gate 4),
  `:1078-1079` (Gate 5), `:1114` (Gate 6 — same pattern), `:1183` (outer
  catch)
- First flagged: 2026-05-06
- Status: not started
- Description: The gauntlet architectural fix landed 2026-05-02 fixed the
  measurement-geometry but kept the same bare-except shape around each
  gate's body. Gate 3 was retrofitted with `if isinstance(e, (TypeError,
  AttributeError)): raise` (lines 1007-1008) — which is exactly the right
  pattern. Gates 2, 4, 5, 6 did NOT receive the same patch. They still
  catch the broad `Exception`, print the type/name, and fall through to
  default values: Gate 2 leaves `survival_rate=0.0`; Gate 4 leaves
  `sig_p=1.0`; Gate 5 leaves `universe_b_sharpe=NaN`; Gate 6 leaves
  factor-alpha defaults. The downstream gate-pass logic varies — Gate 4
  treats `sig_p=1.0` as failing if a `significance_threshold` is set, but
  Gate 5's `universe_b_passed` logic treats NaN as passing. This means a
  silent crash in Gate 5 currently gives a free-pass to the universe-B
  transfer test — the same bug class that was already documented and
  resolved on 2026-04-28. The previous fix-pattern of "narrow the catch
  to `(KeyError, ValueError, RuntimeError)` and re-raise programmer
  errors" should be replicated to the other 4 gates.
- Recommended next step: Apply the same `if isinstance(e, (TypeError,
  AttributeError, ImportError)): raise` defensive promotion to gates 2,
  4, 5, 6 in discovery.py (plus the outer wrapper at line 1183). Or
  better: refactor each gate body into its own `_run_gate_N()` method
  with consistent error-handling — the 5 gate try-except blocks have
  drifted slightly which is its own reason to factor out the boilerplate.

### [MEDIUM] Engine A imports Engine C optimizers — charter inversion (A→C)
- Category: charter inversion
- Files: `engines/engine_a_alpha/signal_processor.py:229-231`
- First flagged: 2026-05-06
- Status: not started
- Description: `signal_processor.py` does
  `from engines.engine_c_portfolio.optimizers import HRPOptimizer,
  TurnoverPenalty` (and HRPConfig / TurnoverConfig) inside its `__init__`
  when `po_settings.method in ("hrp", "hrp_composed")`. Per
  `engine_charters.md` the data flow is A → B → C; A consuming C optimizers
  inverts the dependency. In effect, Engine A is now doing portfolio
  composition as part of signal aggregation. This is not new debt
  (HRP slice work landed in May), but it is a structural drift the
  charter-inversion-imports memory `pattern_charter_inversion_imports.md`
  flagged as a recurring failure mode. Combined with the existing inversion
  `signal_processor.py:27` (A imports F's `EDGE_CATEGORY_MAP`),
  signal_processor is now A's largest charter-violation surface.
- Recommended next step: Long-term: HRP composition belongs in Engine C
  (or in a `core/portfolio_optimizers/` shared package), with A consuming
  a portfolio-allocation interface rather than instantiating an optimizer
  itself. Short-term: rename `engines/engine_c_portfolio/optimizers/` to
  `core/portfolio_optimizers/` so the directional inversion goes away
  even if A keeps the lazy-import. Document in
  `engine_charters.md` that "optimizer interfaces are charter-neutral
  utilities, not C-owned" if that's the desired contract.

### [MEDIUM] Engine A signal_processor approaching god-class threshold (715 LOC); fundamentals_helpers global cache adds another mutable singleton
- Category: god-class / mutable singleton
- Files: `engines/engine_a_alpha/signal_processor.py` (715 LOC),
  `engines/engine_a_alpha/edges/_fundamentals_helpers.py:43-44, 47-66`
- First flagged: 2026-05-06
- Status: not started
- Description: signal_processor.py grew from ~600 LOC pre-Phase-2.10d to
  715 LOC after fill_share_capper, HRP/turnover wiring, per-ticker
  metalearner, and tier-classifier integration. Still under the 1000-LOC
  hard threshold but worth flagging — the same accretion pattern documented
  in `pattern_debt_hotspots.md`. Adjacent finding: `_fundamentals_helpers.py`
  uses a module-global `_PANEL_CACHE` + `_PANEL_LOAD_FAILED` singleton with
  reset functions for tests. Per-process caching is reasonable for a
  10MB SimFin parquet, but the pattern is the same one that bit Path C's
  `fetch_prices` SPY-cache (a cache key that didn't include all required
  tickers). The current implementation caches the *whole panel* unconditionally,
  so the SPY-cache shape of bug isn't reproducible here — but the test-helper
  contract (`reset_panel_cache`, `set_panel`) means production code can
  observe a fixture-injected panel if a test forgets to reset, with no
  cache-key isolation. Same semantics as the Path C bug, different surface.
- Recommended next step: (a) For signal_processor.py: extract the HRP / turnover
  branch (lines 220-242) into a separate `_PortfolioCompositionLayer` class.
  Same pattern as the LifecycleManager extraction that "Held" per the
  hotspots memory. (b) For `_fundamentals_helpers.py`: replace the module-
  global with `functools.lru_cache(maxsize=1)` on a no-arg `_load_panel_cached()`
  function and a corresponding `_load_panel_cached.cache_clear()` for tests.
  Same effective behavior, no mutable globals, harder for tests to leak
  state into production.

### [MEDIUM] `_LAST_OVERLAY_DIAGS` module-global leaks between calls if `run_compounder_backtest` is invoked outside the wrapper
- Category: mutable global / leakage between runs
- Files: `scripts/path_c_synthetic_compounder.py:799, 967, 1295`
- First flagged: 2026-05-06
- Status: not started
- Description: `_LAST_OVERLAY_DIAGS` is a module-global list mutated inside
  `run_compounder_backtest` (line 967) whenever vol_overlay_enabled=True.
  The wrapper `_run_with_overlay_diagnostics` is the only function that
  CLEARS the global (lines 1277, 1291). Any caller that invokes
  `run_compounder_backtest(vol_overlay_enabled=True, ...)` directly — twice
  in the same process — will see the diagnostics from run-1 leaked into
  run-2's view of the global, since `.append()` is the only mutation. This
  is the same shape as the SPY-cache bug: a process-wide mutable state
  that an unsuspecting caller can be silently affected by. Currently only
  `main()` calls the wrapper, so it's latent; but path_c is in active
  iteration and a future ablation harness might hit this.
- Recommended next step: Pass diagnostics back through the return tuple
  (already a 3-tuple; making it a 4-tuple is straightforward) and remove
  `_LAST_OVERLAY_DIAGS` entirely. The wrapper exists only to hide the
  signature change — a deliberate workaround per its docstring. With the
  signature change, the wrapper goes away and the global goes away.

### [LOW] Stale TODO at robustness.py:303 — open since 2026-01-27 (~99 days)
- Category: stale-todo
- Files: `engines/engine_d_discovery/robustness.py:303`
- First flagged: 2026-05-06
- Status: not started
- Description: `# TODO: Compare real result to these distribution` set to
  `"original_sharpe_percentile": 0.0` for every PBO result. Git blame:
  cb61f4f8, 2026-01-27. Older than the 90-day stale threshold. The PBO
  output dict has the placeholder field but no consumer ever reads
  `original_sharpe_percentile` (grep across repo: 0 hits outside this
  line). The TODO is noting that the bootstrapped distribution is
  computed but the actual percentile of the live result against that
  distribution isn't returned. Either implement (1 line:
  `np.mean(self._sharpe_distribution < actual_sharpe)`) or delete the
  field from the dict.
- Recommended next step: One-line fix — either compute the percentile
  inline, or delete the field. Don't leave the TODO open another quarter.

### [LOW] `engines/engine_c_portfolio/sleeves/` is a documented design artifact with zero consumers
- Category: design artifact / disable-on-arrival
- Files: `engines/engine_c_portfolio/sleeves/sleeve_base.py` (151 LOC),
  `engines/engine_c_portfolio/sleeves/__init__.py` (26 LOC)
- First flagged: 2026-05-06
- Status: not started
- Description: Both files document themselves as DESIGN ARTIFACTS — the
  module docstrings explicitly say "DESIGN ARTIFACT, not production code"
  and reference Phases M0-M3 of the path_c_compounder_design_2026_05.md
  migration plan. There are zero non-test imports of the `Sleeve` ABC
  anywhere in the repo (grep across `engines/`, `orchestration/`,
  `scripts/`, `cockpit/`: 0 production consumers). The recent Path C
  decision (defer pending HMM in-production-decision-path + Engine B
  regime-driven de-grossing — see `project_compounder_synthetic_failed_2026_05_02`)
  pushes M1+ further out. This is borderline between "intentional
  forward-looking placeholder" and "dead code that will go stale before
  it ships." The honest framing per
  `pattern_duplicate_orchestrators.md`: a placeholder that ships before
  the migration does often grows two implementations.
- Recommended next step: Either (a) ship a minimal concrete sleeve (e.g.
  CoreSleeve wrapping the existing PortfolioPolicy.allocate() at zero
  semantic change) so the abstraction has at least one real consumer
  beyond tests, OR (b) move sleeves/ to `Archive/engine_c_portfolio/sleeves/`
  with a pointer in the migration plan saying "interface-first design,
  resurrect when M1 unblocks." Per CLAUDE.md, archive-not-delete.
  Path (a) is more useful if Path C unblock happens in next quarter; (b)
  if longer.

### [LOW] `accruals_inv_sloan_edge.py` and `accruals_inv_asset_growth_edge.py` directly negate adapter-precomputed factors — adapter-edge contract is implicit
- Category: implicit contract / future-fragility
- Files: `engines/engine_a_alpha/edges/accruals_inv_sloan_edge.py:88`,
  `engines/engine_a_alpha/edges/accruals_inv_asset_growth_edge.py:81`,
  `engines/data_manager/fundamentals/simfin_adapter.py:131-177`
  (`compute_factors` adds these as derived columns)
- First flagged: 2026-05-06
- Status: not started
- Description: The two accruals edges read `sloan_accruals` and `asset_growth`
  directly from the SimFin panel (precomputed by the adapter at panel-build
  time) and just negate them. The contract — "adapter populates these
  columns, edge consumes them" — is implicit; nothing pins the column
  names or sign convention. If a future adapter rewrite renames
  `sloan_accruals` to `accruals_sloan` (or flips the sign convention), the
  edges fail silently via the bare-except in `top_quintile_long_signals`
  (the previous HIGH finding) — score_fn returns None for every ticker,
  edge abstains, signals drop to zero. No alert fires. Compare to the
  `_INC_KEEP` / `_BAL_KEEP` / `_CF_KEEP` mapping dicts in simfin_adapter.py
  (lines 60-92) which are the canonical column-name registry — these two
  derived columns aren't listed there, just computed inline at line 156-174.
- Recommended next step: Add a `_DERIVED_COLUMNS = {"sloan_accruals", ...}`
  set in simfin_adapter.py and assert the columns exist after `compute_factors`.
  Have edges import that constant rather than the literal string, so a
  rename is enforced by the import. Or: add a `DerivedColumnsContract`
  test that builds a tiny synthetic panel, calls `compute_factors`, and
  asserts the expected columns + sign conventions.

### [LOW] `_LAST_OVERLAY_DIAGS` declared at line 1295 but used at line 799 — forward-reference works only because it's never read in the same module-scope
- Category: code-organization / readability
- Files: `scripts/path_c_synthetic_compounder.py:799, 1295`
- First flagged: 2026-05-06
- Status: not started
- Description: `global _LAST_OVERLAY_DIAGS` at line 799 references a name
  defined at module load time at line 1295 (~500 lines later). This works
  in Python because module loading is top-down and the global is read at
  call-time, not at function-definition-time — but it makes the file
  surprising to read, especially given the global is only mutated inside
  `run_compounder_backtest` and read inside `_run_with_overlay_diagnostics`.
  Same finding as the MEDIUM one above on the global itself, but the
  ordering is independently a readability issue.
- Recommended next step: When the MEDIUM finding above is fixed by
  threading diagnostics through the return tuple, this issue resolves
  automatically. Otherwise, move the `_LAST_OVERLAY_DIAGS: List = []`
  declaration to the top of the module (near other module-level state)
  and add a `# Module-global: see _run_with_overlay_diagnostics docstring`
  comment.
