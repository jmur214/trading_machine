# Master Blueprint & Roadmap

> **Master Protocol:** Every Phase in this roadmap represents an overarching goal. As new ideas exit the pipeline and enter this roadmap, that goal MUST be broken down into smaller, strictly actionable sub-steps.

## Phase 1: Robust Core Foundations (Completed)
- [x] Engines A-D scaffolding (Alpha, Risk, Portfolio, Governor).
- [x] Modular edge integration (Technical signals).
- [x] Initial Backtester & CSV execution simulation.
- [x] Cockpit Dashboard V1 (Performance metrics, PnL by edge, equity curve).
- [x] Governor feedback loops based on CSV trades.

## Phase 2: Codebase Review & Real Fund Architecture (Completed)
- [x] Conduct a comprehensive, line-by-line codebase architecture review to ensure strict alignment with the "Real Fund Manager" mentality.
  - *Completed via `docs/Audit/` — see `codebase_findings.md`, `high_level-engine_function.md`, and `engine_charters.md`.*
- [x] **6-Engine Architecture Restructure.**
  - [x] Split Engine D (Research) into: D (Discovery & Evolution), E (Regime Intelligence), F (Governance).
  - [x] Move MetricsEngine to shared `core/` infrastructure.
  - [x] Move SignalGate to Engine A (`engine_a_alpha/learning/`).
  - [x] Move `promote.py` and `evolution_controller.py` to Governance (F).
  - [x] Wire ModeController to orchestrate Engine E (regime detection as a service).
  - [x] Update all imports across codebase. Remove old `engine_d_research/` and `engine_e_evolution/` directories.
  - *New architecture: A (Alpha), B (Risk), C (Portfolio), D (Discovery), E (Regime), F (Governance).*


## Phase 2.5: Documentation & System Blueprinting
- [x] **Define High-Level Engine Boundaries.**
  - [x] Explicitly outline what Engine A (Alpha), Engine B (Risk), Engine C (Portfolio), and Engine D (Governor) *should* and *shouldn't* do at a high level.
  - [x] Establish these limits to actively prevent logic bleed and technical debt across the execution pipeline.
  - *Completed in `docs/Audit/engine_charters.md` — formal authority boundaries, input/output contracts, and invariants defined for all 5 engines (A-E).*
- [x] **Create an overarching `docs/Core/` meta-index file.**
  - [x] Map, organize, and explain the specific contents of the `docs/Core/` folder itself to guide AI context.
  - *Completed as `docs/Core/README.md` — tiered reading order, document flow diagram, and important rules.*
- [ ] **Visualize system architecture with a Mermaid Flowchart.**
  - [ ] Add the flowchart to `PROJECT_CONTEXT.md`.
  - [ ] Map the exact structural relationships between the code directories and the theoretical system architecture.
- [ ] **Audit and refine Engine `index.md` files.**
  - [ ] Review the qualitative descriptions of all `index.md` files within the `engines/` subdirectories.
  - [ ] Ensure they strictly match the finalized architectural boundaries for 100% functional accuracy.
- [x] **Reconcile Edge Taxonomy (6 Core Edges vs actual implementation).**
  - Kept the 6 Core Edges as the taxonomy. Added "Evolutionary / Synthetic" as a 7th meta-category for GA-generated composite edges.
  - Current alignment:
    - ✅ **Price / Technical** — Implemented (RSI Bounce, ATR Breakout, Bollinger Reversion, Momentum, SMA Cross)
    - ✅ **Fundamental** — Implemented (FundamentalRatio, ValueTrap)
    - 🟡 **News-Based / Event-Driven** — Partial (VADER sentiment exists; EarningsVolEdge handles pre/post-earnings patterns)
    - ✅ **Stat/Quant** — Implemented (SeasonalityEdge, GapEdge, VolumeAnomalyEdge, XSec Momentum/Reversion)
    - ✅ **Behavioral/Psychological** — Implemented (PanicEdge, HerdingEdge, EarningsVolEdge)
    - ❌ **"Grey"** — Not implemented (abstract data source stubs planned)
  - **Evolutionary / Synthetic** — CompositeEdge genomes evolved via GA (tournament selection, crossover, mutation), RuleBasedEdge from tree scanning. These are meta-edges that combine genes from any category above.
  - **ML Gating** — MLPredictor and SignalGate are infrastructure (meta-filters), not edges. Not part of the taxonomy.


## Phase 2.9: Autonomous Edge Lifecycle (ACTIVE — 2026-04-24)

> **Blocker** for all further alpha work. Audit revealed Engines D and F don't execute their charter duties — Discovery validation subprocesses a non-existent script (132/133 candidates auto-fail); Engine F has no retire/pause code at all. The 13 "active" edges are hand-entered and immortal. System underperforms SPY because it can't retire losers or promote winners.

Full plan: [docs/Core/Ideas_Pipeline/autonomous_lifecycle_plan.md](docs/Core/Ideas_Pipeline/autonomous_lifecycle_plan.md). Root memory: `project_autonomous_lifecycle_broken_2026_04_24.md`.

- [x] **Phase β: Benchmark-relative validation gates** (2026-04-24). New `core/benchmark.py` with LRU-cached SPY rolling Sharpe/CAGR/MDD + `gate_sharpe_vs_benchmark()` utility. Wired into `discovery.py::validate_candidate` Gate 1 and `scripts/run_evolution_cycle.py` Gate 1. Falls back to legacy absolute threshold if benchmark data unavailable.
- [x] **Phase γ: Fix Discovery plumbing** (2026-04-24). `evolution_controller.py` rewired — no longer subprocess-calls the missing `walk_forward_validation.py`. Calls `WalkForwardOptimizer` directly with benchmark-relative OOS pass criterion. Smoke-tested: real WFO executes on real candidates.
- [x] **Phase α: `lifecycle_manager.py`** (2026-04-24). Auto-retirement + pause + revival gates with minimum-evidence thresholds, benchmark-relative comparison, audit trail to `data/governor/lifecycle_history.csv`. Wired into governor via `evaluate_lifecycle()` method, called from both `update_from_trade_log` (paper/live) and `mode_controller.run_backtest` (backtest path). Synthetic-verified AND first real-data firing captured.
- [x] **Phase ε (step 1): Flip `lifecycle_enabled: true` and observe first autonomous action** (2026-04-24). Result: `atr_breakout_v1` auto-paused on evidence (sharpe -0.33 vs benchmark 0.87, lost 41% of recent deployed volume). Post-pause canon `5e2ae40a6b5049b4bba71681903d94aa`, Sharpe 0.862, MDD -10.47% (+2.3pp better). Aggregate Sharpe dropped 0.12 because atr_breakout provided leverage-stack volume — lesson: pruning alone hurts, need replacement alpha. See `project_first_autonomous_pause_2026_04_24.md`.
- [x] **Phase α v2: Soft-pause fix for revival deadlock** (2026-04-24). `EdgeRegistry.list_tradeable()` returns active+paused; `ModeController.run_backtest` applies `PAUSED_WEIGHT_MULTIPLIER = 0.25`. Paused edges continue trading at reduced weight so the revival gate has post-pause data. A/B under deterministic harness: baseline Sharpe 0.98 / hard-pause 0.862 / soft-pause **0.979**. Soft-pause is Pareto improvement — same Sharpe, better MDD (+0.39pp) and WR (+5.36pp). Canon `d3799688ad14921a3e27e70231013d70` is the new post-autonomy baseline. See `project_soft_pause_win_2026_04_24.md`.
- [~] **Phase ε (step 2): Demote & re-validate base edges.** Implicitly in progress: lifecycle has now autonomously paused 2 of 14 (`atr_breakout_v1`, `momentum_edge_v1`) on the expanded 109-ticker universe based on evidence, without needing the explicit `reset_base_edges.py` demotion path. The remaining 11 active edges haven't yet had a clear lifecycle trigger fire. The original Phase ε framing (demote ALL bases at once) is no longer the right action — let the lifecycle continue to act incrementally on evidence. Mark `reset_base_edges.py` as available-but-not-needed-for-now.
- [x] **Critical autonomy bug found and fixed (2026-04-25): Registry status-stomp.** `EdgeRegistry.ensure()` was silently reverting lifecycle pause/retire decisions on every module import (auto-register-on-import code in `momentum_edge.py:64` etc. forced `status="active"`). Fixed by write-protecting `status` in `ensure()` per the `edges.yml` Write Contract. 21 new tests in `tests/test_edge_registry.py` + `tests/test_lifecycle_manager.py` enforce the contract permanently. See `memory/project_registry_status_stomp_bug_2026_04_25.md`.
- [x] **Universe expansion (2026-04-25): 39 → 109 tickers.** Single config change in `backtest_settings.json`; data was already cached. Expanded universe surfaced that the original 0.979 baseline was a curated-mega-cap-tech artifact: same edge stack on a wider similar-quality universe gets Sharpe 0.4 (vs SPY 0.88). The 109-ticker post-lifecycle canon `821f98eee63cd94190948e2c234579f6` is the new honest baseline.
- [x] **Phase ζ kickoff (2026-04-25): first FRED-consuming edge shipped.** `engines/engine_a_alpha/edges/macro_yield_curve_edge.py` — yield-curve regime tilt (10Y-2Y spread → uniform ±0.3 tilt across universe). Graceful when cache empty; activates the moment FRED bootstrap runs. Active at weight 0.5. Parallel agent's `engines/data_manager/macro_data.py` is the data source.
- [ ] **Phase α v3 (optional refinement):** Revival gate currently uses `pnls[-20:]` which approximates "post-pause trades." For precision, read `lifecycle_history.csv` to find pause timestamp and filter pnls to post-pause only. Approximation works for high-frequency edges; this refinement matters more for edges that trade sparsely. Plus: add a startup sanity check that flags `<edge>: <prev> → <new>` audit-trail events where `prev` doesn't match the registry's actual current value (would have caught the registry stomp bug).
- [x] **Phase δ: GA fitness function upgrade (2026-04-27).** `0.5*OOS_Sharpe + 0.3*survival_rate + 0.2*degradation_ratio`. Gate 3 key bug fixed (`"degradation_ratio"` → `"degradation"`). `validate_candidate` now stores `wfo_oos_sharpe`, `wfo_is_sharpe`, `fitness_score` in candidate params. `_load_fitness_from_registry` prefers `fitness_score` over `validation_sharpe`. BH-FDR batch correction wired into `mode_controller._run_discovery_cycle`. Macro + earnings gene types added (10%+5% vocabulary share). 26 new tests. See commits 53d5c07, 7db6625, 45abf0e.
- [ ] **Phase ζ continued: more new alpha templates.** PEAD edge (`pead_v1`) is wired and reading from `engines/data_manager/earnings_data.py` (yfinance backend after Finnhub free-tier was confirmed historical-paywalled on 2026-04-25; 109 tickers / 2698 events cached). Cross-sectional momentum to retest on the soon-to-arrive survivorship-aware S&P 500 universe (would let `momentum_factor_v1` use a real top-quintile of ~100 names), low-vol factor (currently failed — needs conditional-weight composition layer). 2-3 weeks.

**Acceptance** (revised after universe expansion exposed the true baseline): combined Sharpe on the 109-ticker (or wider) universe must exceed SPY's Sharpe on the same window for at least 2 of 3 walk-forward splits, with at least one currently-paused edge transitioning autonomously (revive or retire) based on accumulated evidence.

### What needs adding (currently blocking forward progress)

Maintained as a focused checklist in `docs/Progress_Summaries/2026-04-25_session.md` "What needs adding" section. Two-sentence summary here:

- **One user-side action remains for alpha-measurement unblocks**: `scripts/fetch_universe.py` for the survivorship-aware S&P 500 universe → retest `momentum_factor_v1` with proper top-quintile breadth. (`FRED_API_KEY` + bootstrap is done — `macro_yield_curve_v1` is live. Earnings is done — backend swapped Finnhub→yfinance on 2026-04-25 after Finnhub free tier was confirmed paywalled on history; `pead_v1` is reading from a 109-ticker / 2698-event cache.)
- **Three architectural items need design** (not autonomous-loop-sized): conditional-weight composition primitive in signal_processor (the architectural answer to today's `low_vol_factor_v1` regime-conditional failure), Engine D rework to search factor/macro/earnings space instead of technical-only genes, and macro-aware Engine E regime classifier (replaces price-only labels with FRED-driven; requires FRED cache populated first).

## Phase 2.10: Alpha-First Roadmap (ACTIVE — 2026-04-27)

> Driven by user-shared audit doc `docs/Progress_Summaries/2026-04-26_audit-and-improvements.md` (16 non-LLM autonomous discovery methods) plus user feedback: defer AI-heavy methods, prioritize code-level improvements, **prioritize items that actually generate new alpha** rather than items that only harden existing search.

### Sequence (alpha generation first, hardening after)

The HIGH severity finding `[HIGH] System Sharpe 0.4 on 109-ticker universe vs SPY 0.88` (`docs/Audit/health_check.md`) is the load-bearing problem. New alpha sources move that number; hardening doesn't. Steps 1-5 below ship new edges; Step 6+ harden the gauntlet around them.

- [x] **Step 1: `momentum_factor_v1` walk-forward retest on S&P 500 universe** (2026-04-27). CONFIRMED FALSIFIED on 666-ticker universe: FACTOR ON 0.193 vs FACTOR OFF 0.684, delta -0.491. Not a universe-size artifact — 133-name quintile, proper factor breadth. Vanilla 12m-1m momentum without sector neutralization underperforms 2024-2025. Weight stays 0.0. Code retained for future sector-neutral v2.
- [x] **Step 2: `insider_cluster_v1` edge** (2026-04-27). Shipped: cluster Form-4 buying (≥3 distinct insiders within 60 days, 90-day linear-decay hold). 15/15 tests. Registered at weight 0.5. Bootstrap complete on 109-ticker universe.
- [x] **Step 3: 4 macro regime-tilt edges** (2026-04-27). Shipped: `macro_credit_spread_v1`, `macro_unemployment_momentum_v1`, `macro_real_rate_v1`, `macro_dollar_regime_v1`. Each reads FRED series and emits ±0.3 regime tilt. All at weight 0.5.
- [x] **Step 4: Conditional-weight composition primitive in `signal_processor`** (2026-04-27). `regime_gate` field added to `EdgeSpec`; `signal_processor.aggregate_signals()` applies gate as weight multiplier. `low_vol_factor_v1` re-enabled at weight 0.5 with gate `{benign:0.15, stressed:1.0, crisis:1.0}`. 8 tests in `test_signal_processor_regime_gate.py`. Resolved MEDIUM health_check finding.
- [x] **Step 5: PEAD variants** (2026-04-27). Shipped: `pead_short_v1` (negative surprise, 63-day hold), `pead_predrift_v1` (fires only when pre-drift < 5%). 17 tests. Both at weight 0.5.
- [x] **Step 6A: BH-FDR correction** (2026-04-27). `monte_carlo_permutation_test` now applies Benjamini-Hochberg FDR adjustment when `n_tests > 1`. Wired into `mode_controller._run_discovery_cycle` as two-pass batch correction. Closes false-positive hole.
- [x] **Step 6B: GA fitness function upgrade** (2026-04-27). See Phase δ entry above.
- [x] **Step 6C: Transfer test as 5th gate** (commit fe1eabe). `DiscoveryEngine._load_universe_b()` samples tickers NOT in the production universe from `data/processed/`; `validate_candidate()` runs the candidate edge on this out-of-universe sample and requires `universe_b_sharpe > 0` (nan skips the gate gracefully if no universe-B data exists). Gate 5 result stored in `result["universe_b_sharpe"]` and included in `passed_all_gates`. 13 unit tests in `tests/test_discovery_gate5.py`.
- [x] **Step 7: Engine D gene vocabulary expansion** (2026-04-27). Macro + earnings gene types added. See Phase δ above.

### Roadmap (after Step 6, alpha + hardening lanes)

7. Engine D gene vocabulary expansion (factor / macro / event genes) — already MEDIUM in health_check, ~1-2 weeks
8. Sector rotation edge + calendar/seasonality edge — additional Class D edges, ~1 week
9. Mutual-info feature ranking — ~hours, diagnostic
10. Adversarial validation as Gate 6 — ~1-2 days, hardening
11. MAP-Elites GA selection — ~3 days, algorithmic
12. Optuna replacing grid search — ~1 day, algorithmic
13. Causal-discovery validation gate (`dowhy`) — ~1 week, algorithmic
14. Thompson sampling allocator — ~1 week, algorithmic
15. Conformal prediction intervals — ~3-5 days, algorithmic
16. Vectorization audit — variable, code hygiene

### Out of Scope (AI-heavy, deferred per user direction 2026-04-27)

PySR / gplearn symbolic regression, tsfresh / AutoGluon AutoML, GNN universe model, self-play RL, TDA, JAX backtester, coevolutionary alphas, reservoir computing, self-supervised TS, active inference, agent-based simulation. Re-evaluate after Steps 1-16 and the HIGH-severity Sharpe finding has empirical movement to attribute to.

Full plan: `~/.claude/plans/foamy-foraging-horizon.md` (mirror, not authoritative — this section is the source of truth).

## Phase 2.10b: OOS Validation Gate — ❌ FAILED (2026-04-29)

> Driven by `docs/Progress_Summaries/Other-dev-opinion/04-29-26_a-and-i.md`.
> The realistic-cost in-sample Sharpe **1.063** was a hypothesis until
> OOS confirmed it. **All three questions failed by wide margins.**
> Full results in `docs/Audit/oos_validation_2026_04.md` (Q1+Q2,
> branch `oos-validation`) and `docs/Audit/gauntlet_revalidation_2026_04.md`
> (Q3, branch `gauntlet-revalidation`).

- [x] **Q1: 2025 OOS Sharpe under realistic costs.** ❌ FAIL.
      Result: **-0.049** (criterion > 0.5). SPY 2025 was 0.955 →
      system trailed every benchmark by **>1.0 Sharpe** in a strong
      bull year. Run UUID `72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34`.
- [x] **Q2: Universe-B Sharpe under realistic costs.** ❌ FAIL.
      Result: **0.225** vs in-sample 1.063 — a **79% Sharpe collapse**
      (criterion: not below 0.74). Vol nearly doubled (5.7% → 9.95%),
      MDD nearly doubled (-10.07% → -18.17%). Universe-B is closer
      to the system's "true" Sharpe on a representative universe.
      Run UUID `ee21c681-f8de-4cdb-9adb-a102b4063ca1`.
- [x] **Q3: `volume_anomaly_v1` + `herding_v1` through 6 gates.** ❌ FAIL.
      Both edges failed at Gate 1 (the cheapest filter): Sharpe
      **0.32** and **-0.26** respectively, vs benchmark threshold
      ~0.68. **`herding_v1` standalone is capital-destroying** under
      realistic costs (negative Sharpe). The factor-decomp t-stats
      (+4.36, +4.49) were a **cost-model confound** — the per-edge
      backtest used hardcoded 5bps slippage; the integration backtest
      used realistic Almgren-Chriss. Same signal, different costs,
      opposite verdict.

### Headline diagnosis

The 1.063 in-sample headline was a **double artifact**: favorable
universe (curated 109 mega/mid caps) AND favorable window (2021-2024
edge-regime alignment). Real OOS in 2025: -0.049. Real cross-universe:
0.225. The two "real alphas" weren't standalone alphas at all. The
infrastructure caught the artifact exactly as designed — Gate 6
factor-decomp + universe-B sampling + realistic costs together
falsified the claim. The bones-before-paper philosophy is paying off.

### What this kills, immediately

- **Phase 2.11 (per-ticker meta-learner) — BLOCKED.** Per the failure
  clause in `forward_plan_2026_04_29.md`. There is no in-sample base
  to lift via per-ticker training when the in-sample base itself is
  artifact.
- **Phase 2.12 (growth-profile config) — BLOCKED.** Same reason. No
  compounding base to lever into a growth profile.
- **Phase 2.5 (Moonshot Sleeve) — BLOCKED for now.** The architectural
  argument still stands (goal C is a real gap), but spinning up a
  parallel sleeve while the core sleeve doesn't produce alpha is
  premature. Re-evaluate after Phase 2.10c diagnostics.
- **`docs/Audit/realistic_cost_backtest_result.md` 1.063 number** is
  to be re-flagged as in-sample-only with prominent OOS shrinkage
  callout. Not retracted (the in-sample measurement is real); but
  cannot continue to be cited as the system's performance.

## Phase 2.10c: Falsification triage — REFRAMED (2026-04-29) → mostly resolved (2026-04-30)

> Per the original framing: "no new features until we know which of
> the 13 active edges produce real standalone alpha." That framing
> was wrong-headed in retrospect. The Phase 2.10c diagnostic work
> resolved the Q3 paradox via per-edge per-year attribution and
> 2025-decomposition: **the system does have real alpha (volume_anomaly_v1,
> herding_v1, plus weak-positive diversifiers) — it's just being
> wasted by capital rivalry, noise edges, and missing regime-aware
> slot reduction.** Standalone Gate 1 was the wrong test for an
> ensemble system; full standalone gauntlet on all 13/18 edges is
> NOT useful. Universe-fit decomposition partially answered (Agent B's
> +impact-knee math: universe-B has lower-liquidity tickers → impact
> knee bites earlier per fill).

- [x] **Lifecycle-counterfactual** (2026-04-30, branch `lifecycle-counterfactual`,
      audit `docs/Audit/lifecycle_counterfactual_2025_2026_04.md`). Un-pausing
      `atr_breakout_v1` + `momentum_edge_v1` for 2025 OOS lifted Sharpe -0.049 → +0.273
      (+0.32) but **starved volume_anomaly_v1 (191→19 fills) and herding_v1 (44→2
      fills)**. Bucket #2: pause helped a little, edges contribute partial signal.
      Capital rivalry confirmed.
- [x] **2025 OOS decomposition** (2026-04-30, branch `oos-2025-decomposition`,
      audit `docs/Audit/oos_2025_decomposition_2026_04.md`). Per-edge per-month
      PnL + fill counts identified three concrete defect surfaces in
      `signal_processor`/portfolio engine: no per-edge participation floor,
      soft-pause weight leak (`low_vol_factor_v1` fired 1,613 times despite being
      paused), no regime-aware slot reduction (April-2025 `market_turmoil` cliff
      = -$3,551 simultaneous loss across 5 edges).
- [x] **Per-edge per-year attribution** (2026-04-30, branch `per-edge-per-year-attribution`,
      audit `docs/Audit/per_edge_per_year_attribution_2026_04.md`). 16 fired edges across
      2021-2025: 2 stable + 2 regime-conditional + 6 weak-positive + 6 noise/sparse,
      6 more registered active are zero-fill dead weight. **All 3 lifecycle pause
      decisions vindicated** (atr_breakout -5.78% in 2022 alone, momentum_edge -9.17%
      in 2022). Standalone gauntlet has nothing left to tell us — the integration
      math reconciles why the two stable contributors fail Gate 1 standalone (impact
      knee math; see memory `project_ensemble_alpha_paradox_2026_04_30.md`).
- [N/A] ~~Full standalone gauntlet on all 13 active edges~~ — abandoned.
      Standalone Gate 1 is the wrong test for an ensemble system. Per-year
      attribution covers what we actually need to know about edge contribution.
- [N/A] ~~Re-run TierClassifier with realistic-cost data~~ — abandoned for now.
      The TierClassifier reads from factor-decomp; the per-year attribution table
      is a stronger signal at this point. Revisit later if needed.

**Phase 2.10c result:** the system has real alpha (~+5% to +10% per year stable +
~+6% weak-positive diversifier vs ~-9% to -10% noise/dead-weight drag). Forward
path is structural fix, not new alpha hunting. See Phase 2.10d.

## Phase 2.10d: Autonomous lifecycle extension + capital allocation fix — ✅ SHIPPED (cap-only path) 2026-05-01

> **Status update 2026-05-01:** task C (cap=0.25 baseline) measured
> Sharpe 0.315 (AMBIGUOUS); round-2 cap recalibration found cap=0.20
> as the optimum (Sharpe 1.102 OOS / 1.113 IS, full-pass gate cleared).
> `fill_share_cap: 0.20` is now the production cap value.
> Phase 2.11 (portfolio meta-learner stacking on top of cap=0.20)
> attempted to ship this round but the validation run produced Sharpe
> -0.378 — see `docs/Audit/path1_ship_validation_2026_05.md` for the
> ship-blocker analysis and three resolution paths. Cap-only shipped;
> ML-on stacking pending reproduction.


> Phase 2.10c showed alpha exists but is wasted. The original 2.10d
> framing ("hand-pruning proposal" — Agent B classifies which edges
> to cut, user applies) was caught and corrected mid-dispatch:
> hand-pruning violates the project's autonomous-system principle
> (`feedback_no_manual_tuning.md`). The correct fix is to extend the
> autonomous lifecycle so it detects the failure modes Agent B
> identified, runs continuously, and applies the same KEEP/CUT
> decisions on its own — both for the existing 22 edges and for
> every future edge that decays.
>
> Agent B's pruning-proposal audit (branch `pruning-proposal`,
> `docs/Audit/pruning_proposal_2026_04.md`) is preserved as
> **ground-truth target** for trigger calibration. It is NOT applied
> as a config change.

### Tasks A + B in parallel — different engines, low conflict risk

- [ ] **A. Autonomous lifecycle trigger extension** (Agent B continuity).
      Extend `engines/engine_f_governance/lifecycle_manager.py` with
      the missing detection primitives:
      1. **Zero-fill timeout trigger.** Edge active with 0 fills over
         90+ days → auto-pause → 90 days later → auto-retire.
      2. **Sustained-noise trigger.** Edge with `|mean annual
         contribution| < threshold` AND no positive year over rolling
         3-year window → auto-pause. Threshold calibrated from Agent
         B's per-year attribution table so the 9-11 cut-eligible
         edges trip it but the 6-7 keep-eligible don't.
      3. **TierClassifier scheduling.** Wire as a post-backtest hook
         (already designed, never scheduled). Re-classifies tiers
         monthly so stale classifications self-correct.
      4. **Validate** by running extended lifecycle on existing 5-year
         integration data: the autonomous triggers must produce the
         same KEEP/CUT decision Agent B reached manually. If they
         don't, re-tune. **The hand-classified result is the
         falsifiable spec for the autonomous output.**
      Output: code in `lifecycle_manager.py` + new tests + audit doc
      `docs/Audit/lifecycle_triggers_validation_2026_04.md` showing
      trigger-fire vs hand-classified comparison.

- [ ] **B. Capital allocation structural fixes** (Agent A continuity).
      Three missing primitives — these are genuine code work, not
      autonomous decisions:
      1. **Per-edge participation floor / fill-share ceiling** in
         `engines/engine_a_alpha/signal_processor.py`. No single edge
         can consume >X% of fills regardless of its weight. Hard
         architectural ceiling. The 83% fill-share concentration
         observed in 2025 should be impossible by construction.
      2. **Soft-pause weight leak fix** in signal_processor /
         regime_gate logic. `low_vol_factor_v1` fired 1,613 times in
         2025 despite being paused because `regime_gate` amplifies
         weight back to full in stressed regimes — exactly opposite
         of design intent. Soft-pause must dominate regime_gate
         amplification.
      3. **Regime-aware slot reduction primitive** — likely Engine B
         (Risk) or Engine C (Portfolio). When regime classifier
         reports `market_turmoil` or `crisis`, cap concurrent active
         positions to N/2. The April-2025 -$3,551 single-month
         correlated loss across 5 edges should be impossible by
         construction. **TOUCHES ENGINE B / C — agent must propose
         design before implementing.**
      Output: code on a branch + tests + audit doc
      `docs/Audit/capital_allocation_fixes_2026_04.md` documenting
      design + before/after measurements.

### C. Re-run 2025 OOS (sequential, after A + B merge)

- [ ] **C. Re-run 2025 OOS with extended lifecycle + capital
      allocation fixes active.** Same window/universe/cost-model as
      Q1 anchor (UUID `72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34`).
      Director runs.

### Phase 2.10d gate — recalibrated 2026-04-30 with kill-thesis floor

Pre-committed thresholds (per the 04-30 outside reviewer's
no-goalpost-moving discipline). Pre-committed BEFORE Agent A and
Agent B report so the result can't be moved-the-goalposts away:

| Post-fix 2025 OOS Sharpe | Verdict |
|---|---|
| **< 0.2** | **Kill thesis.** The alpha foundation is wrong. Pivot harder than 2.10d. The structural fixes were *necessary* but the system has deeper problems than rivalry — possibly the universe, possibly the underlying signals themselves. Stop, regroup, do NOT continue patching. |
| 0.2 - 0.4 | **Ambiguous.** Fix worked partially. More rivalry/dilution diagnosis needed. Phase 2.11 still blocked. |
| 0.4 - 0.65 | **Partial pass.** Real lift but trails benchmark significantly. Phase 2.11 (per-ticker meta-learner) becomes the strategic next step (per 04-30 reviewer: meta-learner *is* the structural answer to capital rivalry that the linear allocator can't fully solve). |
| **> 0.65** | **Full pass.** Phase 2.11 + 2.12 unblock. Goal-B path becomes credible. |

## Phase 2.10e: Reform Gate 1 — ensemble-simulation gate (SHIPPED IN-PROGRESS, NOT PROMOTED — 2026-05-01)

> **Status as of 2026-05-01 evening:** Phase 2.10e shipped as in-progress.
> Two iterations of the gate (`gate1-reform-ensemble-simulation`,
> `gate1-reform-baseline-fix`) progressively closed the baseline-vs-harness
> gap from -1.4 Sharpe to ~0.33 Sharpe, but ~0.33 Sharpe of residual
> divergence remains, attributable to init-order/model-state/config
> subtleties the gate's reimplementation can't easily reproduce.
> Falsifiable-spec `volume_anomaly_v1` + `herding_v1` produce
> contributions ~zero under the corrected baseline — could be genuine
> "edges add zero ensemble value" OR measurement artifact of the
> residual gap; the two cannot be cleanly separated yet. Branches on
> origin, NOT merged. Per-pre-committed criterion: gate is
> mis-designed → re-tune. **Not promoted.** Memory:
> `project_gate1_reimplementation_problem_2026_05_01.md`.
>
> **Architectural pivot for next session:** the gate reimplements
> ensemble execution in its own code path, which is fragile to converge.
> The cleaner architecture is to invoke the actual production backtest
> pipeline (`orchestration/mode_controller.py::run_backtest`) with the
> candidate added vs excluded, rather than reimplementing the ensemble.
> That's a meaningful refactor (likely needs `run_backtest_pure(...)`
> extraction from the CLI orchestration layer) but it's the convergence
> path. See memory file for the design.

> **Original framing (preserved for context):** The 04-30 outside
> reviewer flagged Q3's standalone-gauntlet failure as a false negative
> produced by the gauntlet's test geometry not matching the deployment
> geometry: standalone fills get full `risk_per_trade_pct` and cross
> the Almgren-Chriss impact knee; ensemble fills stay sub-knee. **The
> gauntlet is currently rejecting real alphas because of test
> geometry.** Reform Gate 1 to test candidates *inside a simulated
> ensemble of the current active set with realistic capital splitting.*
> Standalone Sharpe becomes one diagnostic, not a gate.

- [ ] Design ensemble-simulation gate in
      `engines/engine_d_discovery/discovery.py::validate_candidate`.
      Replace standalone-Sharpe Gate 1 with: candidate edge added to
      simulated ensemble of active edges, full backtest with realistic
      capital splitting, benchmark-relative Sharpe of the *candidate's
      attributed contribution* must clear threshold.
- [ ] Backtest the same ground truth: re-run `volume_anomaly_v1` and
      `herding_v1` through the new Gate 1 and confirm both PASS
      (because they pass per-year attribution under the ensemble
      math). If they don't pass, the ensemble gate is mis-designed.
- [ ] Document in `docs/Audit/gate1_reform_2026_04.md`.

**Sequencing:** queued post-2.10d because Discovery isn't running new
candidates this cycle anyway; the gate-reform isn't blocking 2.10d.
Important to land before any future Discovery run — otherwise we
manufacture more false negatives.

## Phase 0.5: Cost-model completeness (queued — borrow + tax + Alpaca tiers)

> 04-30 reviewer addition. The current `RealisticSlippageModel`
> handles half-spread + Almgren-Chriss impact correctly but misses
> three after-tax / after-fee elements that materially affect any
> "we beat the market" claim:
> - **Borrow rates** for shorts (5–25 bps/day on borrows; can be
>   huge for short-bias periods)
> - **Short-term cap gains tax** (30%+ federal haircut for active
>   strategies — kills naive after-tax CAGR)
> - **Alpaca fee tiers** (currently flat assumption)

- [ ] Borrow-rate model for short positions in
      `RealisticSlippageModel` (or wrapper).
- [ ] Tax-aware backtest mode — short-term gains taxed at 30%+
      federal, long-term at 15-20%. Track holding-period per
      position; apply tax drag at year-end.
- [ ] Alpaca fee-tier model.

**Why this matters for goal A (compound):** for a 20-something
planning to compound over 40 years, short-term tax drag compounds
*against* you. A naive 12% pre-tax CAGR with 90% short-term turnover
delivers ~8.4% after-tax — that's a 30%+ erosion of the compounding
base over decades. Goal A's honest evidence requires after-tax
measurement.

**Sequencing:** queued. Should ship before the system is presented
with a credible "beat the market" claim, but doesn't block 2.10d/e.

## Cross-cutting workstream addition (continuous)

- [ ] **Capital allocation diagnostic dashboard** in `cockpit/dashboard_v2/`.
      Live view of per-edge fill share vs PnL contribution, updated
      per backtest. The 2025 capital-rivalry pathology would have
      been visible in real time if this view had existed during the
      in-sample run. Cheap UX-engineer task; high signal value
      forever after. (Future ux-engineer dispatch.)

## Phase 2.11: Portfolio meta-learner — ⚠ CONDITIONAL SHIP within prod-109 (2026-05-01)

> **2026-05-01 update:** Agent C's `metalearner-robustness` audit
> validated the portfolio meta-learner at Sharpe 1.064 (cap=0.25,
> ML-on, prod-109 2025 OOS) and walk-forward mean Sharpe +0.873
> across 2022/2023/2024 holdouts. Universe-B test FAILED (Sharpe 0.273)
> — the lift is concentrated on prod-109. **The deployment boundary
> at `docs/Core/deployment_boundary_2026_05.md` documents this.**
>
> Path 1 ship-state validation in agentA worktree under cap=0.20 +
> ML-on produced Sharpe **-0.378** — the stacking with cap=0.20 did
> not reproduce. The ML half of Path 1 is **not yet validated for
> production**. Director's call on resolution path
> (`docs/Audit/path1_ship_validation_2026_05.md`).
>
> Original framing (preserved for Phase 2.11 *per-ticker* training,
> still BLOCKED until portfolio ML reproduces):

## Phase 2.11 per-ticker (still blocked) — Session N+1 proper, ~2 weeks


> **BLOCKED** by Phase 2.10b failure. The in-sample base this would
> have lifted is itself artifact. Re-evaluate after Phase 2.10c
> diagnostics determine whether any real edge exists in the stack.
>
> Original framing (preserved for context): Phase 1 N+1 portfolio-level
> trainer showed +0.056 OOS correlation — barely above coin flip.
> Per-ticker training was hypothesized to be the real lift.

- [ ] Log per-bar per-ticker edge scores during backtest (route from
      `alpha_engine.AlphaEngine.run_alpha_logic()` to a parquet the
      trainer can consume).
- [ ] `scripts/train_metalearner.py` per-ticker mode with walk-forward
      rolling folds. One model per ticker (or per ticker-cluster if
      data is too sparse).
- [ ] A/B comparison across all three profiles (retiree / balanced /
      growth) with `metalearner.enabled: true`. Confirm:
      retiree-profile model produces lowest-vol output, growth-profile
      model produces highest-CAGR output, all from the same edge pool.
- [ ] **Phase 1 gate crossing**: meta-learner-active OOS strictly
      better fitness than disabled. Until then,
      `metalearner.enabled: false` stays in production config.

## Phase 2.12: Universe configured for growth (~1 week) — 🚫 BLOCKED 2026-04-29

> **BLOCKED** by Phase 2.10b failure. Switching to growth profile
> requires a compounding base that produces real alpha. The current
> stack does not (Sharpe -0.049 OOS in 2025, Sharpe 0.225 on
> universe-B). Re-evaluate after Phase 2.10c determines the real
> alpha content of the active edge stack.
>
> Original framing (preserved for context): the user's stated goals
> (20-something, 40-year horizon, growth priority) explicitly favor
> `growth` profile over `balanced` for the core sleeve. Architecture
> already supports this — most of the work is config, with one
> small-code addition.

### Config moves (no new code)
- [ ] Switch active fitness profile to `growth` in
      `config/fitness_profiles.yml`.
- [ ] Concentrated-universe mode: cap to top 30–50 names by momentum +
      liquidity rather than the full 109. **Concentration is itself
      growth-profile alpha.**
- [ ] *(Engine B — propose first)* Loosen position sizing:
      `risk_per_trade_pct` 0.025 → 0.05; sector cap 20% → 30%;
      single-name cap 5% → 8%.
- [ ] *(Engine B — propose first)* Allow modest gross leverage
      (1.1–1.3x) when meta-learner confidence is high.

### Small-code edge additions (growth-flavored)
- [ ] `momentum_factor_v2` — sector-neutral cross-sectional 12-1
      momentum (v1 was falsified OOS for concentration reasons).
- [ ] `earnings_revision_momentum_v1` — long stocks with rising EPS
      estimate consensus over 3 months.
- [ ] `breakout_52w_v1` — 52-week breakout with volume confirmation
      (CAN SLIM / O'Neil).
- [ ] `qmj_composite_v1` — Quality + Momentum composite (AQR's
      research-confirmed long top decile of momentum × quality).
- [ ] `sector_rotation_v1` — long top 3 sectors by 6-month return,
      monthly rebalance.

**Phase 2.12 honest tradeoff** (per reviewer): expect Sharpe
1.063 → 0.7–0.9, MDD -10% → -20% to -30%, CAGR 6% → 12–18%. Higher
growth is NOT higher Sharpe; they can move opposite. The honest
benchmark for high-growth is leveraged passive (70/30 QQQ/TQQQ),
not SPY.

## Phase 2.5: Moonshot Sleeve (PARALLEL — NEW 2026-04-29) — 🚫 BLOCKED 2026-04-29

> **BLOCKED** by Phase 2.10b failure. The architectural argument
> still stands — goal C (asymmetric upside) is a real gap that no
> amount of core-sleeve tuning will close — but spinning up a
> parallel sleeve while the core sleeve does not produce alpha is
> premature. Re-evaluate after Phase 2.10c. Design notes below
> remain valid; deployment is paused.
>
> Original framing (preserved for context): the architectural gap
> for **goal C** (asymmetric upside / catch moonshots like RKLB,
> NVDA, BTC). The current core sleeve cannot do this and shouldn't
> be forced to — Sharpe optimization punishes high-vol positions;
> 109-name diversification dilutes any 10x to noise; the
> lifecycle/gauntlet is built around statistical rigor, not
> narrative-driven theme conviction.
>
> The strategy: **venture-capital model applied to public equities.**
> Hold 30–50 candidates, each sized to lose at most 1–2% of the sleeve
> if it goes to zero, stop-loss at -50%, upside uncapped. Hit rate
> 10–30% is fine — the math works only at portfolio level.
>
> Suggested allocation for a 20-something:
> Core (70–75%) + Moonshot (15–20%) + Cash (5–10%).
>
> Full design in `docs/Core/forward_plan_2026_04_29.md`.

### Phase 2.5 deliverables (parallel to 2.11/2.12, not blocking)

- [ ] **Universe data layer expansion** — Russell 2000 + IPO last-5y +
      theme-tagged equities (AI, space, biotech, crypto-equity, EV,
      semis). 200–400 names, refreshed quarterly. **Explicitly NOT
      the S&P 100/500 names the core trades.**
- [ ] **`moonshot` profile** added to `config/fitness_profiles.yml` —
      Sortino + skewness + upside-capture weights (NOT Sharpe).
- [ ] **Different gauntlet criteria** for moonshot edges:
      skewness > 0.5, upside capture > 1.2× downside capture, hit
      rate ≤ 30% acceptable. Lifecycle (Layer 1) gates remain
      objective.
- [ ] **5–7 moonshot edges** through the gauntlet:
  - [ ] Long-term momentum (12m + 24m) on small/mid-caps
  - [ ] 52-week breakout with volume confirmation on small-caps
  - [ ] Earnings beat + raised guidance (persistent 6–12 month signal)
  - [ ] Insider cluster buying in small-caps (small-cap variant of
        `insider_cluster_v1`)
  - [ ] Sentiment velocity — *rate of change* of mentions on
        Reddit/StockTwits, not absolute level
  - [ ] High short interest + improving fundamentals (squeeze setups)
  - [ ] Theme detection (10-K language clustering, quarterly universe
        pivot — this is the Phase 6 LLM foothold)
- [ ] *(Engine B — propose first)* **Asymmetric sizing engine** as a
      parallel module to `risk_engine.py`, runs on the moonshot sleeve
      only. Trailing stops not fixed exits. Stop-loss at -50%.
- [ ] *(Engine C — propose first)* **Two-sleeve portfolio engine** —
      aggregates positions from both sleeves, applies portfolio-level
      risk caps, does NOT cross-net them.

**Phase 2.5 gate:** moonshot sleeve passes its own walk-forward over
2018–2024 with skewness > 0.5, hit rate 15–30%, and sleeve-level CAGR
> Russell 2000 over the same window.

**Phase 2.5 deployment is gated on Phase 3** (kill switches, real
OMS) — higher risk profile means *more* critical kill switches, not
fewer. Design and validate now; deploy after Phase 3.

## Phase 3: From Simulation to Reality
- [ ] Enforce structural risk diversification logic and cross-sector allocation before advancing trading operations.
- [ ] Connect the Order Management System (OMS).
- [ ] Incorporate slippage, fees, and short-borrow cost modeling. *(Partial: fixed + vol-based slippage and commission exist in ExecutionSimulator; short-borrow cost not yet modeled)*
- [ ] Solidify exposure limits and Max Drawdown logic. *(Partial: RiskEngine enforces gross exposure, sector limits, position limits, ATR stops, trailing stops; Governor MDD kill-switch at -25%)*
- [ ] Transition from CSV data to Parquet / DB solutions for local analytics. *(Partial: DataManager dual-writes Parquet + CSV; Parquet is primary read path)*
- [ ] Finalize the Alpaca Paper Trading integration with the Cockpit.

## Phase 4: Market Regime Detection & Intelligence
- [x] Build a dedicated Market Regime Detection engine (Engine E). *(Completed: `engine_e_regime/` with `RegimeDetector`; advisory hints planned)*
- [x] **Comprehensive Engine E rewrite — 5-axis regime detection with advisory system.**
  - [x] Phase 1: Foundation (RegimeConfig, regime_settings.json, HysteresisFilter)
  - [x] Phase 2: Sub-detectors (Trend, Volatility, Correlation, Breadth, Forward Stress)
  - [x] Phase 3: Coordinator + Advisory (AdvisoryEngine, RegimeHistoryStore, RegimeDetector rewrite, macro regime mapping)
  - [x] Phase 4: Wiring (BacktestController, ModeController, AlphaEngine, CompositeEdge, run_backtest.py)
  - [x] Phase 5: History + Analytics (regime history persistence, RegimePerfAnalytics compatibility)
  - *84 unit tests passing. 5 axes, hysteresis, soft macro regime probabilities, coherence checks, VIX term structure.*
- [x] **Double-counting cleanup:** Replaced binary `market_vol == "high"` (-25%) and `market_trend == "bear"` (-50%) cuts in SignalProcessor with Engine E's advisory `risk_scalar` applied selectively in stressed/crisis regimes. Backtest validated: Sharpe improved from -0.56 to -0.40. Edge affinity boost deferred until Governance (F) proves regime-conditional profitability. See `lessons_learned.md` for details.
- [x] **Self-Learning Feedback Loop Closure.**
  - [x] Governor MDD kill-switch: soft proportional penalty (current vs historical drawdown) instead of permanent hard zero.
  - [x] Governor normalization: removed sum-to-1.0 constraint; weights are now independent quality scores in [0, 1].
  - [x] RiskEngine dynamic sizing: fixed inert `gate_confidence` default; now uses signal `strength` + `governor_weight` for position sizing.
  - [x] Equal aggregation weights: `run_backtest.py` passes 1.0 for all loaded edges, Governor handles quality differentiation post-aggregation.
  - [x] Silent edges fixed: config no longer overrides edge weights to 0.0; `EdgeRegistry.get_all_specs()` added.
  - [x] Discovery wired: `--discover` flag on `run_backtest.py` triggers post-backtest hunt → validate → promote cycle.
  - *See `lessons_learned.md` 2026-04-16 entries for details.*
- [x] **Regime-Conditional Edge Management (B) + Portfolio Management (C).**
  - [x] Phase 1: `RegimePerformanceTracker` — per-edge, per-regime Welford online stats (`engines/engine_f_governance/regime_tracker.py`).
  - [~] Phase 2: Governor regime-conditional weights — blended `alpha * regime_weight + (1-alpha) * global_weight`. Architecture landed (init-time priming via `_rebuild_regime_weights_from_tracker`); **runtime activation DISABLED 2026-04-23** (`regime_conditional_enabled: false`). Three walk-forward splits via [scripts/walk_forward_regime.py](scripts/walk_forward_regime.py): Split A (eval 2023-2024) soft-kill -0.50 Sharpe, Split B (eval 2024-2025) +0.18, Split C (eval 2025) -0.21. Central tendency: net-negative in 2 of 3 splits, with one positive outlier that overlaps both negatives on 2024 — so it's not "activation helps in regime X" cleanly, more likely noise + one anomaly. Hard-kill variant is consistently worst. In-sample (Sharpe 0.98 / hard-kill -0.37 / soft-kill 0.83) is misleading in isolation. Mechanism is not reliably additive. Before any re-enable decision: redesign the signal source (coarser regime grouping, continuous features, or portfolio-level overlay) rather than iterating policy on the current mechanism. See `project_regime_conditional_activation_blocked_2026_04_23.md`.
  - [x] Phase 3: Trade fill regime tagging — every fill stamped with `regime_label` from macro regime at time of execution.
  - [x] Phase 4: AlphaEngine wiring — `get_edge_weights(regime_meta=regime_meta)` passes current regime to Governor.
  - [x] Phase 5: Learned edge affinity — `RegimePerformanceTracker.get_learned_affinity()` replaces static `MACRO_EDGE_AFFINITY` table; applied as 0.3-1.5x multiplier per edge category in `SignalProcessor`.
  - [x] Phase 6: Advisory wired to Risk Engine — `prepare_order()` now consumes `suggested_max_positions`, `suggested_exposure_cap`, `risk_scalar`, and `correlation_regime` for dynamic sector limits. All constraints can only tighten, never loosen beyond config.
  - [x] Phase 7: Portfolio vol targeting — `PortfolioPolicy` now estimates portfolio-level vol via `w @ cov @ w` and scales weights to match `target_volatility`. Advisory exposure cap enforcement applied post-allocation.
  - [x] Phase 8: Autonomous allocation discovery — `AllocationEvaluator` tests 384 parameter combos (mode, max_weight, target_vol, rebalance_thresh, risk_per_trade_pct), scores by composite metric, saves per-regime recommendations. Governor runs evaluation in `update_from_trade_log()` feedback loop. `auto_apply_allocation` defaults to false.
  - *New files: `regime_tracker.py`, `allocation_evaluator.py`. Modified: governor.py, alpha_engine.py, signal_processor.py, risk_engine.py, policy.py, portfolio_engine.py, backtest_controller.py, governor_settings.json.*
- [x] **Regime Classification Threshold Calibration.** Transitional base score 0.30→0.15, confidence threshold 0.40→0.25. Validated across 2021-2024: regime labels now match market character (bull years → expansion, 2022 → cautious/turmoil). See `lessons_learned.md` 2026-04-20 entry.
- [x] **Governor Regime Tracker Window Fix.** Tracker now processes all trades (not just 90-day rolling window) since Welford's algorithm is designed for indefinite accumulation.
- [x] **CockpitLogger `regime_label` column.** Added to `TRADE_COLUMNS` so regime labels persist in trade CSVs.
- [x] **Short Bias Inversion Bug — RESOLVED (2026-04-21).** Root cause was 4 compounding issues: (1) `mode_controller.py` hardcoded all edge weights to 1.0, overriding config; (2) `alpha_settings.prod.json` diverged from validated weights; (3) `portfolio_settings.json` had `min_weight=-0.05` enabling shorts at the MVO level; (4) stale governor weights from the broken system. Fixes: mode_controller reads config weights, prod config synced, min_weight=0.0, governor reset. Post-fix: short bias eliminated, 55-60% win rate, trades across all years. See `lessons_learned.md` 2026-04-21 entry.
- [x] **Governor Kill-Switch Passthrough (code retained, claim FALSIFIED 2026-04-23).** `get_edge_weights()` passthrough `elif regime_val <= 1e-9: return 0.0` is principled defense against blend-dilution of killed edges. Re-tested under deterministic methodology (3-run PASS): reverting the branch produced bitwise-identical canon md5s, Sharpe 0.98 both ways. The originally-claimed 0.94→1.08 delta was noise from a logger thread race (since fixed). Branch is currently dormant because the anchor `regime_edge_performance.json` has no regime meeting the kill condition (negative Sharpe + ≥ min_trades). Code stays in for future activation; do not cite the Sharpe delta. See `project_killswitch_passthrough_win.md` memory.
- [x] **Backtest Determinism Methodology (2026-04-22).** Established that back-to-back backtest runs were non-deterministic because `governor.save_weights()` mutates `edge_weights.json` + `regime_edge_performance.json` at end of each run, so run 2 reads different seed state than run 1. Resolution: combine existing `--no-governor` flag with pre-run anchor restoration via `scripts/run_deterministic.py`. All prior A/B claims made without pinned state are noise-level and need re-verification. See `lessons_learned.md` 2026-04-22 entry and `execution_manual.md` "Deterministic A/B Testing" section.
- [ ] **Falsified: adverse-regime stop-tightening (2026-04-22).** Tried tightening trailing stops on open positions whose edge has `regime_weight=0` in current regime. Failed: Sharpe 1.08→0.96, MDD worse. Asymmetric effect (helped in `market_turmoil`, hurt in `cautious_decline` chop) — same "cut winners short" pattern as signal-exit bleed. Do not retry without (a) severity-conditioning or (b) a different dimension (portfolio-level exposure cuts, not per-position stops). Reverted. See `lessons_learned.md` 2026-04-22 entry.
- [~] Empower Governance (Engine F) to retire/activate edges based on regime-conditional performance (via `RegimePerformanceTracker`). *Infrastructure complete (Phases 1-8 all landed), but the per-edge per-regime mechanism is currently runtime-disabled (2026-04-23) after walk-forward falsification. Retire/activate logic is inert until a redesigned regime signal passes walk-forward. See Phase 2 entry above.*
- [x] **Engine D Discovery & Edge Ecosystem Overhaul.**
  - [x] **Feature Engineering Expansion:** 18 features -> 40+ across 7 categories (technical, fundamental, calendar, microstructure, inter-market, regime context, cross-sectional).
  - [x] **Two-Stage ML Pipeline:** LightGBM screening for feature importance -> shallow decision tree for interpretable rule extraction. Time-series CV with purge gap. Vol-adjusted targets (ATR-scaled thresholds).
  - [x] **Genetic Algorithm Engine:** Tournament selection, single-point crossover, Gaussian mutation, elitism. Persistent population in `ga_population.yml`. Seeding from existing composite edges.
  - [x] **4-Gate Validation Pipeline:** Backtest (Sharpe > 0) -> PBO robustness (50 paths, survival > 0.7) -> WFO degradation (OOS >= 60% IS) -> Monte Carlo significance (p < 0.05).
  - [x] **Expanded Gene Vocabulary:** 7 gene types in CompositeEdge (technical, fundamental, regime, calendar, microstructure, intermarket, behavioral) with weighted random generation.
  - [x] **New Stat/Quant Edges:** SeasonalityEdge (calendar patterns), GapEdge (overnight gap fill), VolumeAnomalyEdge (spike reversal / dry-up breakout).
  - [x] **New Behavioral Edges:** PanicEdge (multi-condition extreme reversion), HerdingEdge (cross-sectional contrarian), EarningsVolEdge (pre-earnings vol compression / post-earnings drift).
  - [x] **Edge Registration:** All 6 new edges registered in `edges.yml` with `status: active`, added to discovery template mutation pool.
  - [x] **Discovery Orchestration:** `run_backtest.py --discover` now runs: regime detection -> expanded feature hunt -> GA evolution -> 4-gate validation -> auto-promotion. JSONL audit logging via `DiscoveryLogger`.
  - *9 new files created, 6 files modified. See `lessons_learned.md` 2026-04-17 entry.*
- [x] **Architectural Refactoring — 7 Structural Fixes.**
  - [x] Fix 1: Single PnL path — `PortfolioEngine.apply_fill()` stamps `fill["pnl"]` as sole source of truth. Removed fallback computations from backtest_controller and logger.
  - [x] Fix 2: Paper mode SL/TP parity — `PaperTradeController` now has trailing stop management + SL/TP evaluation matching BacktestController. Removed incorrect forced-exit-all logic.
  - [x] Fix 3: Metrics consolidation — `MetricsEngine` is sole calculator; `cockpit/metrics.py` delegates via cached `_engine_metrics()`. Removed inline metrics from `run_benchmark.py`.
  - [x] Fix 4: Scripts → orchestration — All backtest orchestration (warmup, edge registry, governor init, discovery) moved to `ModeController.run_backtest()`. `run_backtest.py` slimmed to ~87 lines.
  - [x] Fix 5: Edge feedback → Engine F — Core feedback loop moved from `analytics/edge_feedback.py` to `governor.py` as `update_from_trade_log()`. Thin shim preserved for backward compat.
  - [x] Fix 6: BacktestController method extraction — 831-line `run()` refactored into 8 private methods. Pure refactor, no behavior change.
  - [x] Fix 7: Logger snapshot cleanup — Removed portfolio valuation fallback from `log_snapshot()`. Logger is now a pure recorder.
  - [x] Audit Correction A: Stop/TP propagation — `ExecutionSimulator.fill_at_next_open()` now preserves `stop`/`take_profit` from order to fill dict.
  - [x] Audit Correction B: Metrics index alignment — Fixed NaN-dropped equity row misalignment in timestamp mapping.
  - *See `lessons_learned.md` 2026-04-18 entry for full details and architectural takeaways.*
- [ ] Develop advanced edges: News Sentiment/Geopolitical scrapers, Grey edge data sources.

### Phase 4.5: Engine E Enhancements (Deferred)
- [ ] **HMM cross-validator:** Add Hidden Markov Model (hmmlearn) as a parallel statistical detector to validate rule-based regime classifications.
- [ ] **Cap-weighted sector returns:** Use market-cap-weighted (not equal-weighted) sector return series in CorrelationDetector. Requires market cap data integration.
- [ ] **Hurst exponent:** Add Hurst exponent computation in TrendDetector for trend quality/mean-reversion tendency assessment.
- [ ] **Credit spreads (HYG/LQD):** Add credit spread monitoring as additional forward stress input in ForwardStressDetector.
- [ ] **SKEW index:** Integrate CBOE SKEW index for tail-risk demand measurement in ForwardStressDetector.
- [ ] **F1 evaluation against NBER dates:** Formal calibration of macro regime classifications against NBER recession dates for accuracy scoring.
- [ ] **Full regime probability blending in Alpha (A):** Enable Engine A to weight forecasts by macro regime probability distribution (not just hard gate).

## Phase 5: The "Schwab Intelligent Portfolio" (SIP) Extension
- [ ] Create Portfolio Sleeves (e.g., partitioning custodial sub-accounts for Equity, Fixed-Income, Cash).
- [ ] Automatic drift monitoring and independent rebalance scheduling.
- [ ] Tax-loss harvesting (TLH) simulation scaffolding.

## Phase 6: Scaling & Live Operations
- [ ] CI/CD pipeline, Docker containerization, and AWS/Cloud deployment.
- [ ] Dual Paper-Trader Segregation (PT-A for testing, PT-B for validated strategies).
- [ ] Live execution graduation (moving from Paper to real capital).

## Phase 7: Human-in-the-Loop Cockpit Override (Long-Term Vision)
- [ ] Develop the "Big Red Button" global halt mechanism.
- [ ] Build global risk adjustment sliders and mobile push notifications for drawdown/alert tracking.
