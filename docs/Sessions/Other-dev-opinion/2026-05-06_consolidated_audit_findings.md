# External Audit Findings — Consolidated (2026-05-06)

> Both findings sets condensed into a single review document.

## Context

Two independent AI reviewers were given concise audit prompts (varying minor
wording) with read access to the codebase. Both were instructed to verify
findings against code, distinguish in-sample from OOS, cite file paths, and
flag what they couldn't verify. The second review was scoped to deprioritize
execution / OMS findings since deployment infrastructure is intentionally
deferred.

The two audits ran independently. They overlap on five findings (highest
confidence — corroborated independently) and each contributes unique
findings the other missed.

This document consolidates both. **Findings flagged HIGH/MEDIUM here have
been verified at file:line level by at least one reviewer.** Disagreements
should be resolved with grep first, then by reading code, before any
discussion of remediation.

The execution / OMS / live_trader findings from review #2 are
intentionally excluded per project's deferred-deployment posture.

---

## Findings — Tier 1 (HIGH confidence: both audits independently identified)

### F1. Engine E is shipped but dormant — and built on empirically falsified features

- All four flags in `engines/engine_e_regime/regime_config.py:121,151,173,204` default to **False**.
- HMM is enabled only in `scripts/run_ws_c_smoke.py` (a smoke test). Production decision paths consume zero output from Engine E.
- ~1500 LOC of regime code in active namespace: `regime_detector.py` (624), `multires_hmm.py`, `transition_warning.py` (305), `cross_asset_confirm.py` (183), `hmm_classifier.py` (464), plus 582 LOC of tests.
- Validation memo `project_regime_signal_falsified_2026_05_06.md`:
  - HMM AUC = 0.49 on 20d-fwd drawdowns (coin flip)
  - Cross-asset 2-of-3 gate: TPR = 0% on -5% drawdowns over 1086 days
  - OOS 2025 AUC = 0.36 (worse than coin flip on actual event)
- HMM input features (`spy_ret_5d`, `spy_vol_20d`) are coincident by construction — verified at `engines/engine_e_regime/hmm_classifier.py:55-63`.

**Action:** Archive the dormant + falsified components: `cross_asset_confirm.py`, `multires_hmm.py`, `transition_warning.py`, plus the slice of `regime_detector.py` dependent on the falsified panel. Don't preserve dormant code in active engine namespaces.

### F2. V/Q/A merge follows the wash-sale +0.670 false-positive pattern

- 6 V/Q/A edges shipped to `data/governor/edges.yml` as `status: active` with weight 0.5 each (`config/alpha_settings.prod.json:38-44`).
- Validation: 2021 Sharpe **1.607 vs baseline 1.666 = -0.06 drag**, framed as "within noise band". **In-sample. Bull market. 2021 only.**
- 2022 bear smoke (the team's own named diagnostic test) has not been run.
- `sustained_score = 0.3` is a function default at `engines/engine_a_alpha/edges/_fundamentals_helpers.py:199` — shared by all 6 edges, no grid search performed.
- Same shape as wash-sale gate +0.670 finding (in-sample win → ship to active → multi-year falsification later showed 2021 Δ = -0.966).

**Action:** Pause V/Q/A from active until (a) 2022 bear smoke runs, (b) `sustained_score` grid search runs across (0.0, 0.2, 0.3, 0.5). Treat the parameter as a hyperparameter, not a function default.

### F3. Discovery-gauntlet bare-except remediation is partial; "RESOLVED" status is misleading

- 13 bare `except Exception` blocks remain in `engines/engine_d_discovery/discovery.py` (verified by grep).
- Only Gate 3 (line 1006) and Gate 6 (line 1114) got the defensive promotion `if isinstance(e, (TypeError, AttributeError)): raise`.
- Gates 2/4/5/6 at lines 975, 1026, 1078, 1114 still catch broad `Exception`. Outer wrapper at line 1183 still bare.
- Specific silent-pass patterns:
  - Gate 5: `gate_5_passed = bool(math.isnan(universe_b_sharpe) or universe_b_sharpe > 0)` — NaN passes
  - Gate 6 default: `factor_alpha_passed = True` on exception
  - Gate 4 bypass: `if significance_threshold is None: sig_passed = True`
- `engines/engine_d_discovery/robustness.py:303` still has placeholder `original_sharpe_percentile = 0.0  # TODO`.
- 2026-05-02 "gauntlet architectural fix RESOLVED" addressed measurement geometry only; failure-mode handling still latent.

**Action:** Replicate Gate 3's narrowed-catch pattern across gates 2/4/5/6 + outer wrapper. Eliminate the NaN-passes-Gate-5 and default-True-on-exception patterns. Should be hours of work.

### F4. Charter inversion accumulating in signal_processor

- `engines/engine_a_alpha/signal_processor.py` is **715 LOC** and imports from BOTH:
  - Engine F: `EDGE_CATEGORY_MAP` at line 27
  - Engine C: `HRPOptimizer` and `TurnoverPenalty` instantiated at lines 228-242
- `engines/engine_c_portfolio/portfolio_engine.py` is **366 LOC** — half the size of the engine importing from it.
- Per charter: A → B → C is the data flow. A consuming both F's taxonomy and C's optimizers means signal_processor is the de facto portfolio composition layer.
- Reviewer doc said C is the biggest engine gap. Team agreed. Then HRP got built in A.

**Action:** Move HRP and TurnoverPenalty invocation out of signal_processor and into Engine C. signal_processor should produce signals only, per charter.

### F5. `risk_engine_bak.py` shouldn't exist in active engine namespace

- `engines/engine_b_risk/risk_engine_bak.py` is 752 LOC, never imported (verified).
- 203 LOC of drift between it and the real engine.
- CLAUDE.md says "Archive, never delete" — does not say "never archive either."
- Other files in active namespaces with similar status: `engines/engine_f_governance/system_governor.py` (653 LOC), `engines/engine_f_governance/evolution_controller.py` (387 LOC), `engines/engine_a_alpha/not-yet_edges/`.

**Action:** `git mv engines/engine_b_risk/risk_engine_bak.py Archive/`. Repeat for the other dead files. ≥2400 LOC of confusion surface removed in one commit.

---

## Findings — Tier 2 (HIGH confidence: only one audit found, but with file:line evidence)

### F6. UniverseLoader exists but is wired into ZERO backtests — survivorship bias dominates Foundation Gate measurement

*(From audit 1)*

- `engines/data_manager/universe.py:226-240` defines a working `historical_constituents(as_of)` method.
- Documentation in `engines/data_manager/index.md:98` explicitly states: "**Not yet wired into any engine**."
- `grep -rn "historical_constituents\|UniverseLoader" engines orchestration backtester scripts` returns zero production callers.
- Every backtest consumes `config/universe.json` — a static 115-name list of *current* S&P 500 mega-caps.
- `health_check.md:85`: "Universe-B held-out 50, in-sample window: Sharpe **0.225 vs in-sample 1.063 — a 79% Sharpe collapse**". This collapse has NOT been re-measured since the gauntlet rewrite, cost layer, V/Q/A merge, etc.
- Every Sharpe number in `multi_year_foundation_measurement.md` is conditional on the favorable, survivorship-biased universe.
- Building the survivorship-aware loader and not wiring it is **worse than not building it** — creates the appearance of solved bias.

**Action:** Wire `UniverseLoader.historical_constituents()` into the backtest data path. Generate survivorship-aware S&P 500 price panel for 2010-2025. Re-run multi-year measurement with frozen code. Three possible outcomes:
- Sharpe ~1.296 survives → real foundation, downstream work confirmed
- Sharpe drops moderately (0.7-1.1) → universe artifact partial, recalibrate edges
- Sharpe collapses to 0.3-0.5 → most "alpha" was universe-selection bias

**This is the highest-leverage single experiment available. Until it runs, every other measurement is conditional on assumed-not-verified substrate.**

### F7. The "5 years × 3 reps = 15 runs" Foundation Gate is one statistical sample × 3 determinism checks per year

*(From audit 1)*

- `multi_year_foundation_measurement.md:10-14`: for each year, `Sharpe (rep1, rep2, rep3) = (1.6660, 1.6660, 1.6660)` (or equivalent triple-identical values).
- "Canon md5 unique 1/3, Determinism PASS (bitwise)" — the determinism harness producing bit-identical output across reruns. **Not statistical robustness.**
- Mean Sharpe 1.296 is a **single point estimate**; standard error is undefined.
- Range 0.583 (2022) → 1.890 (2024) is the true cross-year noise envelope on N=1 measurements per year.
- The "Foundation Gate: PASS" headline conflates "harness is reproducible" with "system has alpha."

**Action:** Update Foundation Gate framing in `forward_plan.md` to acknowledge N=1 per year. To get statistical robustness, would need either (a) bootstrap resampling within each year, (b) different random seeds for any stochastic components, or (c) walk-forward sliding windows producing multiple independent samples per year.

### F8. Parameter tuning happened on the period labeled OOS — 2025 is pseudo-OOS, not real OOS

*(From audit 1)*

Specific parameters tuned during/with 2025 data:
- `fill_share_cap = 0.20` chosen by `scripts/sweep_cap_recalibration.py` explicitly optimizing 2025 OOS Sharpe (`docs/Measurements/2026-04/cap_bracket_sweep_2026_04.md`).
- `PAUSED_MAX_WEIGHT = 0.5` chosen by inspecting 2026-04 in-sample atr_breakout fill counts (`health_check.md:232-236`).
- ADV floors $200M / $300M chosen via `path2_adv_floors_under_new_gauntlet_2026_05.md` sweep.
- `sustained_score = 0.3` hand-picked to bring 2021 Sharpe within "noise band" of 1.666 baseline.

Net result: 2025 Sharpe **0.954 ≈ SPY 0.955** (zero alpha vs benchmark on the favorable universe with parameters tuned to the period). CAGR **4.39% vs SPY ~13%**.

**Action:** Define a real OOS window (e.g., 2026-Q1 forward) where code AND config are frozen. No tuning, no peeking. Until that runs, "OOS Sharpe" claims should be qualified.

### F9. Latent non-determinism in non-snapshot module-level caches

*(From audit 2)*

The 2026-05-01 determinism harness (`scripts/run_isolated.py`) snapshots/restores 4 governor files. But code-health flagged additional mutable globals:
- `_LAST_OVERLAY_DIAGS` in `scripts/path_c_synthetic_compounder.py:799,967,1295`
- `_PANEL_CACHE` and `_PANEL_LOAD_FAILED` singletons in `engines/engine_a_alpha/edges/_fundamentals_helpers.py:43-66`

These are latent — same shape as the SPY-cache bug and the registry status-stomp bug, both of which were found only after they corrupted measurements.

**Determinism is currently maintained by user discipline (running through `run_isolated.py`), not by structure.** The day someone runs an experiment outside the harness on a long-lived REPL or notebook, the ±1.4 Sharpe variance era can return.

**Action:** Enumerate all module-level mutable state via grep (`grep -rn "^_[A-Z]" engines/ core/ scripts/` is a starting filter). Either (a) snapshot/restore them in `run_isolated.py` like the four governor files (band-aid), or (b) refactor them into instance state with explicit lifecycle (structurally correct).

### F10. MetaLearner is a -0.4 to -0.6 Sharpe drag under the harness; production "ensemble" is hand-tuned JSON weights

*(From audit 1)*

- `config/alpha_settings.prod.json:32-58` — every edge weight is a hardcoded float (atr_breakout_v1: 2.5, momentum_edge_v1: 1.5, V/Q/A: 0.5 each, etc.).
- `path1_revalidation_under_harness_2026_05.md:42-58`: under the harness, ML-on (`metalearner.enabled: true`) costs **-0.578 Sharpe** at cap=0.20, **-0.436 Sharpe** at cap=0.25. The +0.749 Sharpe lift previously cited from ML stacking was governor-drift coincidence.
- Result: every "ensemble combination" claim is a human tuning a JSON file. The narrative of "autonomous improvement" in CLAUDE.md is, in production, a no-op.

**Action:** Either (a) acknowledge in CLAUDE.md and forward_plan that ensemble combination is currently human-curated, OR (b) prioritize getting MetaLearner to non-negative Sharpe under harness. Don't pretend the autonomous-learning narrative is operational when it isn't.

### F11. Governor's autonomous lifecycle is mathematically incompatible with reproducible measurement

*(From audit 1)*

`evaluate_lifecycle` and `evaluate_tiers` mutate `data/governor/edges.yml` at end-of-run, which the next run reads at start. The harness papers over this by snapshot/restore.

The deeper symptom: `health_check.md` now contains finding after finding where the "fix" is "remember to call `--reset-governor`" or "wrap in `lifecycle_readonly: true`" or "snapshot+restore." **The autonomous learning loop is being domesticated by manual ceremonies rather than redesigned.**

**Action:** Architectural decision needed. Either (a) make lifecycle writes go to a separate file that's explicitly versioned per-run (not state read by next run), OR (b) accept that production = lifecycle-write and measurement = lifecycle-readonly, and enforce the flag at API boundary, not at script-call discipline.

---

## Confidence interpretation

**Tier 1 (F1-F5):** Both reviewers found independently. Highest confidence. Should not be controversial.

**Tier 2 (F6-F11):** One reviewer found, but with file:line evidence. Audit 1 found F6, F7, F8, F10, F11. Audit 2 found F9. All are grep-verifiable.

If any specific finding is disputed, the fastest falsification is to grep the cited file:line. Every claim has a path attached.

---

## Things flagged but not verified

From both audits combined:

- Whether the Round-N+1 dispatch ever fired against the gate-conditional condition.
- Whether SimFin V/Q/A panel has unintentional point-in-time leakage (helper has `publish_date <= asof_ts` filter at `_fundamentals_helpers.py:130, 161`, but full SimFin adapter not exercised).
- Whether the "2025 OOS" runs actually used end-of-2024 governor state vs. current governor state.
- Independence of trade fills across "reps" in multi-year measurement beyond canon-md5 reproduction.
- Current contents of `data/governor/edges.yml` and active-edge set (gitignored).
- `data/processed/` price panel content / freshness.

---

## Recommended action ordering

Sequenced by leverage and dependency:

1. **F6 — Wire UniverseLoader** *(2-3 days)* — single highest-leverage experiment. All downstream measurements gated on this.
2. **F9 — Snapshot non-governor mutable globals** *(few hours)* — measurement integrity, prerequisite for trustworthy reruns.
3. **F3 — Replicate Gate 3 narrowed-catch to gates 2/4/5/6 + outer wrapper** *(few hours)* — discovery integrity.
4. **F5 — Archive dead files in active namespaces** *(15 minutes)* — `git mv risk_engine_bak.py`, `system_governor.py`, `evolution_controller.py`, `not-yet_edges/` to `Archive/`.
5. **F2 — V/Q/A 2022 bear smoke + sustained_score grid search** *(half day)* — already on the dev's queue. Audit confirms.
6. **F1 — Archive Engine E dormant + falsified code** *(1-2 hours)* — `cross_asset_confirm.py`, `multires_hmm.py`, `transition_warning.py`, falsified slice of `regime_detector.py` to `Archive/`.
7. **F4 — Move HRP/TurnoverPenalty from signal_processor to Engine C** *(1-2 days)* — charter restoration.
8. **F8 — Define real frozen-code OOS window** *(forward, no work needed)* — process discipline going forward.
9. **F10 — Decide on MetaLearner narrative** *(decision, not engineering)* — either fix the model or update the docs.
10. **F11 — Architectural decision on Governor write-back** *(propose-first)* — affects engine charters.

---

## What this means

The team has done substantial engineering rigor on findings F1-F5; the audits' main contribution is showing **F6 (substrate) and F9 (latent non-determinism)** are larger than appreciated. F6 in particular invalidates the foundation of every Sharpe number quoted to date until proven otherwise.

**The single experiment that dominates everything else: wire UniverseLoader and rerun multi-year. Until it runs, all other progress is conditional on an assumption.**

Both audits' bottom-line framing converges:
- Audit 1: "You are doing extensive engineering rigor on the wrong substrate."
- Audit 2 (excluding execution): "Polish on a substrate that doesn't support the conclusions."

Same finding, different phrasings.
