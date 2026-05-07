# Phase C Dispatch Prompts — branched on F6 verdict

**Status:** Pre-drafted 2026-05-07 while Phase A is finishing. To be activated when B1 (UniverseLoader wire + multi-year rerun) returns its verdict.

The B1 dispatch (in `/Users/jacksonmurphy/.claude/plans/foamy-foraging-horizon.md`) reports one of three outcomes. Each maps to one Phase C path below. Pick the matching path's prompt(s) and fire as fresh sessions per the same end-of-cycle pattern.

---

## How to use this file

When B1 returns its verdict (`docs/Measurements/2026-05/universe_aware_verdict_2026_05_09.md`), read the verdict line and pick the branch:

| Verdict | Phase C path | First dispatch |
|---|---|---|
| Mean Sharpe within ±0.15 of 1.296 | C-survives | C-survives-1 (V/Q/A 2022 bear smoke + grid search) |
| Mean Sharpe 0.7-1.1 | C-partial | C-partial-1 (substrate-aware hyperparameter retune) |
| Mean Sharpe 0.3-0.5 | C-collapses | C-collapses-1 (substrate-honest edge audit) |

Each branch has 2-3 dispatches that can fire sequentially or in parallel depending on dependencies.

---

# C-survives — substrate is real, downstream work confirmed

## C-survives-1 — V/Q/A 2022 bear smoke + sustained_score grid search

**Why this is first:** the 2026-05-07 V/Q/A sustained-scores fix passed 2021 smoke (Sharpe 1.607 vs baseline 1.666 = -0.06 drag) but 2021 was a bull regime. 2022 bear is the diagnostic gate before promoting V/Q/A to default-on production. Plus `sustained_score=0.3` was a heuristic — grid-search validates it.

### SETUP

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git worktree add .claude/worktrees/csurv1-vqa-bear -b c-survives-vqa-bear-grid
cd .claude/worktrees/csurv1-vqa-bear
claude
```

### PROMPT

```
You are working on the ArchonDEX trading system. Read CLAUDE.md first. Full autonomous cycle: setup, work, propose end-of-cycle ops.

## Setup

```bash
git worktree add .claude/worktrees/csurv1-vqa-bear -b c-survives-vqa-bear-grid
cd .claude/worktrees/csurv1-vqa-bear
```

## Background

V/Q/A sustained-scores fix landed 2026-05-07 (memory `project_vqa_sustained_scores_win_2026_05_07.md`). 2021 smoke Sharpe 1.607 vs baseline 1.666 — within noise band. But 2021 = bull regime. The "diagnostic gate" before default-on is the 2022 bear regime smoke + sustained_score grid search.

The F6 universe-aware substrate test (B1) survived per its verdict in `docs/Measurements/2026-05/universe_aware_verdict_2026_05_09.md` — meaning the existing V/Q/A test substrate is real, not survivorship-biased.

## Goal

Two complementary tests:

### 1. 2022 bear smoke — does V/Q/A hold during a real bear regime?

Run single-year 2022 backtest under the harness with V/Q/A active (current production state):

```bash
PYTHONHASHSEED=0 python -m scripts.run_multi_year --years 2022 --runs 3
```

Compare to:
- Baseline 2022 (pre-V/Q/A, from project_foundation_gate_passed_2026_05_04.md): Sharpe 0.583
- The expected outcome under the integration-mismatch hypothesis: V/Q/A's defensive vote should HELP in bear regimes (holds positions when other edges panic-sell)

Acceptance: Sharpe within ±0.10 of baseline 0.583 = "holds across regimes"; meaningfully better = "V/Q/A net-positive in bear"; meaningfully worse = "design issue, do NOT promote default-on, defer".

### 2. sustained_score grid search

Test 4 values of `sustained_score`: 0.0 (entry-only, the fixed-but-broken state), 0.2, 0.3 (current default), 0.5.

For each value, run a 1-year smoke on 2024 (the most-volatile-bull year, good signal-to-noise) with V/Q/A active and `sustained_score` overridden via env var or config patch.

Output: 4 Sharpe values + canon md5s + trade counts. Identify the value with best Sharpe AND no pathological behavior (e.g., 0.5 might cause edges to over-defend losing positions).

## Acceptance

- 2022 bear smoke completes (3 reps, bitwise-identical canon md5)
- 4-point grid search completes for 2024
- `docs/Measurements/2026-05/vqa_2022_bear_grid_<date>.md` reports both with verdict on whether to promote default-on
- If 2022 looks bad: explicit recommendation to leave V/Q/A in current state (active with sustained_score=0.3) but skip the multi-year rerun until next iteration

## Hard constraints

- Do NOT modify production V/Q/A code beyond the parameterized grid invocation
- Don't touch `data/governor/` outside the harness's snapshot scope
- Branch: `c-survives-vqa-bear-grid`
- Time budget: 2-3 hours including all backtest runs (2022 single year ≈ 5-15 min, grid 4×5-15 min)

## End-of-cycle

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git checkout main
git merge --no-ff c-survives-vqa-bear-grid -m "Merge branch 'c-survives-vqa-bear-grid' — V/Q/A 2022 bear smoke + sustained_score grid: <PROMOTE|HOLD|REGRESS>"
git push origin main
git worktree remove .claude/worktrees/csurv1-vqa-bear
```

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

## Report

2022 Sharpe per rep, canon md5, comparison to baseline. Grid search table (sustained_score → 2024 Sharpe). Verdict + final main commit hash.
```

## C-survives-2 — Minimal-HMM regime experiment on existing FRED features

**Why this is second:** the slice-1 HMM panel rebuild work found that yield-curve and credit features ALREADY in the panel were quietly leading (78-day lead before 2025 -18.8% drawdown), drowned out by coincident features. The cheap-validation Branch 3 (memory `project_cheap_input_validation_branch3_2026_05_06.md` — same memory captures both the VIX-term coincident verdict and the surviving FRED features for the next experiment) confirmed VIX term structure is decisively coincident.

The minimal-HMM experiment isolates the leading subset.

### SETUP

```bash
git worktree add .claude/worktrees/csurv2-minimal-hmm -b c-survives-minimal-hmm
cd .claude/worktrees/csurv2-minimal-hmm
claude
```

### PROMPT

```
You are working on the ArchonDEX trading system. Read CLAUDE.md first. Full autonomous cycle.

## Setup

```bash
git worktree add .claude/worktrees/csurv2-minimal-hmm -b c-survives-minimal-hmm
cd .claude/worktrees/csurv2-minimal-hmm
```

## Background

The 2026-05-06 regime-signal validation showed HMM is empirically coincident (AUC 0.49 on 20d-fwd drawdowns, coin flip). The slice-1 panel-rebuild dispatch found VIX term structure also coincident BUT exposed that yield_curve_spread + credit_spread_baa_aaa + dollar_ret_63d (already in the panel) carried a 78-day OOS lead before the 2025 -18.8% drawdown — drowned out by other features.

The cheap-validation Branch 3 confirmed: stop adding features (VIX term confirmed coincident across 4 tenor pairs in 3 measurements; CBOE P/C unobtainable in 2026 on free endpoints). The next experiment is feature SELECTION not feature ACQUISITION.

This is the regime panel slice-2 plan codified in `docs/Core/Ideas_Pipeline/regime_panel_slice_2_plan.md`.

## Goal

Train a fresh HMM on ONLY 4 leading-candidate features:
- `yield_curve_spread` (10Y - 2Y or 10Y - 3M)
- `credit_spread_baa_aaa` (BAA - AAA)
- `dollar_ret_63d` (USD 63-day return)
- `spy_vol_20d` (kept as the universe-vol regime indicator)

Compare to:
- Baseline HMM (current panel, already validated as coincident)
- Slice-1 HMM (added VIX term structure, also coincident but with state-space rotation effects)

Run all three through `scripts/validate_regime_signals.py`:
- AUC vs SPY 20d-fwd drawdown ≤ -5%
- Coincident-vs-leading correlation flip (forward corr > trailing corr)
- Per-state breakdown (does the "stress" state lead, or do mean reversion / quality-of-fit issues drown the signal)

User's VIX-term-paired hypothesis from 2026-05-07: test 3 minimal-HMM variants:
- A: 4 leading FRED features alone
- B: A + VIX term as confirmation feature (does it ratify stress calls)
- C: A + VIX term as interaction term (is there nonlinear value)

## Acceptance

Audit doc at `docs/Measurements/2026-05/minimal_hmm_2026_05_<date>.md` with:
- AUC table for all 3 variants × 4 horizons (5d, 20d, 60d)
- Coincident-leading correlation flip status for each
- 2025 OOS event analysis: how many days each variant called stress before the -18.8% drawdown
- Verdict: which variant (if any) clears AUC > 0.55 AND coincident-leading flip
- If yes: scope Engine B integration of the minimal HMM (propose-first per CLAUDE.md)
- If no: regime work needs novel input data (Schwab IV skew gated on historical-chains verification, or paid options-history provider)

## Hard constraints

- READ-ONLY analysis on existing panel + price data
- DO NOT modify Engine B / live_trader/
- DO NOT promote any HMM model to production this dispatch
- Reuse `scripts/validate_regime_signals.py` and `scripts/train_hmm_vix_term.py` as starting points
- Branch: `c-survives-minimal-hmm`
- Time budget: 2-3 hours

## End-of-cycle

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git checkout main
git merge --no-ff c-survives-minimal-hmm -m "Merge branch 'c-survives-minimal-hmm' — minimal HMM verdict: <LEADING|PARTIAL|NOT-LEADING>"
git push origin main
git worktree remove .claude/worktrees/csurv2-minimal-hmm
```

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

## Report

AUC for each variant + horizon, coincident-leading correlation table, branch verdict, final main commit hash.
```

## C-survives-3 — Charter restoration: HRP + TurnoverPenalty out of signal_processor

**Why optional:** F4 from the consolidated audit. `engines/engine_a_alpha/signal_processor.py:228-242` instantiates `HRPOptimizer` and `TurnoverPenalty` from Engine C. Charter says A → B → C is the data flow; A consuming C's optimizers is charter inversion. signal_processor is 715 LOC and is the de facto portfolio composition layer because of this.

This is a 1-2 day refactor. Defer if other priorities.

(Prompt skeleton — flesh out with grep results when activating)

```
You are working on the ArchonDEX trading system. Read CLAUDE.md first. Full autonomous cycle.

This is a charter-restoration refactor. F4 from the 2026-05-06 consolidated audit. signal_processor (Engine A) imports HRPOptimizer + TurnoverPenalty from Engine C, violating the A → B → C data flow charter.

Goal: move both invocations out of signal_processor.py into Engine C's portfolio_engine.py. signal_processor produces signals only; Engine C consumes signals + applies HRP/turnover.

Acceptance:
- signal_processor.py LOC reduces to <500 (currently 715)
- portfolio_engine.py expands appropriately
- Existing tests pass
- New tests verify the charter boundary
- Audit doc at docs/Measurements/2026-05/charter_restoration_signal_to_portfolio_<date>.md

[Add detailed file:line refactor map after grep on the active code]

End-of-cycle, branch c-survives-charter-restoration.
```

---

# C-partial — universe artifact partial; recalibrate

## C-partial-1 — Substrate-aware hyperparameter retune

**Why first:** F8 from the audit identified that `fill_share_cap=0.20`, `PAUSED_MAX_WEIGHT=0.5`, ADV floors, AND `sustained_score=0.3` were ALL tuned on 2025 data using the static (now-known-biased) universe. If F6 returns "partial," the fix is to retune those hyperparameters on the substrate-honest universe — but with discipline: define a frozen-code OOS window first (e.g., 2026-Q1 forward) where retuning is forbidden.

### SETUP

```bash
git worktree add .claude/worktrees/cpart1-retune -b c-partial-substrate-retune
cd .claude/worktrees/cpart1-retune
claude
```

### PROMPT

```
You are working on the ArchonDEX trading system. Read CLAUDE.md first. Full autonomous cycle.

## Setup

```bash
git worktree add .claude/worktrees/cpart1-retune -b c-partial-substrate-retune
cd .claude/worktrees/cpart1-retune
```

## Background

F6 (UniverseLoader wire + multi-year rerun) returned PARTIAL — Sharpe 0.7-1.1 on substrate-honest universe vs 1.296 on biased universe. Per audit F8, multiple hyperparameters were tuned on biased substrate. They likely need retuning. But: this is a curve-fitting hazard if done carelessly.

## Goal

Three deliverables:

### 1. Define a frozen-code OOS window

Pick 2026-Q1 forward (or whatever's most recent post-merge data). DOCUMENT this in `docs/State/forward_plan.md` as the new OOS standard. Hyperparameters tuned BEFORE this window must NOT be re-tuned ON it.

Add a `config/oos_window.json` or similar that records: (a) the window start date, (b) the code-state hash at window-open, (c) the parameters that were FROZEN at window-open.

### 2. Identify which hyperparameters need recalibration on the substrate-honest universe

The audit named these:
- `fill_share_cap` (current 0.20, tuned via `scripts/sweep_cap_recalibration.py`)
- `PAUSED_MAX_WEIGHT` (current 0.5, tuned by inspecting 2026-04 atr_breakout fill counts)
- ADV floors $200M / $300M (tuned via `path2_adv_floors_under_new_gauntlet_2026_05`)
- `sustained_score` (current 0.3, hand-picked 2026-05-07)

For each: re-run the sweep on the substrate-honest universe (2021-2024 only — leave 2025 untouched as semi-OOS, even though F8 noted it's pseudo-OOS).

### 3. Re-run multi-year measurement on the retuned config

After retunes, run multi-year (2021-2024 only — frozen from 2025-Q1 forward).

Compare to F6's substrate-honest baseline. Verdict:
- Substrate-honest Sharpe recovers to >0.9 on retuned config: recalibration is sufficient
- Stays at 0.7-0.9: real edge attrition vs the biased universe; consider edge-by-edge attribution
- Drops below 0.7: deeper problem; defer to C-collapses path

## Acceptance

- Frozen-code OOS window documented in `docs/State/forward_plan.md`
- Each hyperparameter retune logged in `docs/Measurements/2026-05/substrate_retune_<param>_<date>.md`
- Final multi-year measurement on retuned config in `docs/Measurements/2026-05/multi_year_substrate_retuned_<date>.md`
- Verdict + recommendation for next phase

## Hard constraints

- DO NOT touch parameters frozen for the 2025+ OOS window
- DO NOT modify Engine B / live_trader/
- Branch: `c-partial-substrate-retune`
- Time budget: 4-6 hours (multiple sweeps + measurement)

## End-of-cycle

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git checkout main
git merge --no-ff c-partial-substrate-retune -m "Merge branch 'c-partial-substrate-retune' — hyperparameter recalibration on substrate-honest universe, verdict: <RECOVERS|PARTIAL|REGRESS>"
git push origin main
git worktree remove .claude/worktrees/cpart1-retune
```

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

## Report

Retune deltas per parameter, multi-year retuned vs baseline, verdict, final main commit hash.
```

## C-partial-2 — Per-edge contribution analysis

(Skeleton — flesh out when activated)

```
After C-partial-1 retunes hyperparameters, run per-edge attribution on the substrate-honest universe to identify which edges hold up vs which were universe-dependent.

Existing infrastructure: scripts/per_edge_per_year_attribution.py (uses hardcoded UUIDs — update to use latest substrate-aware run_ids).

Acceptance: per-edge Sharpe contribution table on substrate-honest universe; flag edges where Sharpe drops by >0.3 vs biased-universe baseline; recommend status changes (active → paused → failed) per Engine F lifecycle.
```

---

# C-collapses — most "alpha" was selection bias; reset directive

## C-collapses-1 — Substrate-honest edge audit

**Why this is first:** if F6 returns Sharpe 0.3-0.5 on the substrate-honest universe, the project's headline alpha narrative was substrate bias, not real edge contribution. The fix is NOT retuning — the previous edges were measured on a biased substrate, so retuning them on the honest substrate is incremental at best. The fix is auditing each edge for what it actually CAN do on a representative universe.

### SETUP

```bash
git worktree add .claude/worktrees/ccoll1-edge-audit -b c-collapses-edge-audit
cd .claude/worktrees/ccoll1-edge-audit
claude
```

### PROMPT

```
You are working on the ArchonDEX trading system. Read CLAUDE.md first. Full autonomous cycle.

## Setup

```bash
git worktree add .claude/worktrees/ccoll1-edge-audit -b c-collapses-edge-audit
cd .claude/worktrees/ccoll1-edge-audit
```

## Background — somber framing

F6 (UniverseLoader wire + multi-year rerun) returned COLLAPSES — Sharpe 0.3-0.5 on substrate-honest universe. Per the verdict criterion: most "alpha" was selection bias, not real edge contribution. The discipline framework caught this early — that's the project working as designed.

What survives: all infrastructure (Foundry, observability, harness, decision diary, code-health audits, doc lifecycle). Edge code itself is intact. What's invalidated: the headline Sharpe narrative.

## Goal

Edge-by-edge audit on the substrate-honest universe to identify what each edge ACTUALLY does on a representative universe (vs what it appeared to do on the biased universe).

### Per-edge audit protocol

For each `status: active` edge in `data/governor/edges.yml` (verify count via `grep -c "status: active"`):
1. Run single-edge backtest on the substrate-honest universe, 2021-2024 (leave 2025 as OOS).
2. Compute per-edge Sharpe contribution.
3. Compare to claimed Sharpe contribution in audit history (memory + docs/Measurements/).
4. Classify the edge:
   - **CONFIRMED** — substrate-honest Sharpe within ±0.2 of biased Sharpe → keep active
   - **DEGRADED** — substrate-honest Sharpe drops 0.2-0.5 → status='paused' with `failure_reason='universe_too_small'`
   - **FALSIFIED** — substrate-honest Sharpe drops >0.5 → status='failed' with `failure_reason='universe_too_small'`

This applies the existing edge graveyard tagging schema (memory `project_path_c_deferred_2026_05_06` mentions WS-J).

### Surviving-edges-only multi-year

Run the multi-year measurement again with ONLY the CONFIRMED edges. This is the substrate-honest "real" Foundation Gate — what the system is actually capable of.

### Honest reset of forward_plan

Update `docs/State/forward_plan.md` with:
- Substrate-honest Sharpe (the new ceiling)
- Confirmed edges (the new active set)
- Path forward: what kind of edges are needed to lift Sharpe on a representative universe (not mega-cap-only)

## Acceptance

- Per-edge audit table in `docs/Measurements/2026-05/substrate_collapse_edge_audit_<date>.md`
- Updated `data/governor/edges.yml` with status changes (additive only — don't lose history)
- Surviving-edges multi-year measurement
- Honest forward_plan update — no goalpost-moving
- Memory entry capturing what survived and what didn't

## Hard constraints

- DO NOT promote any "fix" that's just retuning on the substrate-honest universe (curve-fitting hazard per audit F8)
- DO NOT delete edge code; mark status only
- DO NOT modify Engine B / live_trader/
- Branch: `c-collapses-edge-audit`
- Time budget: 6-8 hours (full edge audit + multi-year)

## Honest interpretation guidance

This is a hard reset. The project's last 30 days of measurement narrative is partly invalidated. That is genuinely difficult but it's what the discipline framework is FOR. The infrastructure investments (Foundry, observability, harness) are not invalidated — they're what made this finding possible.

The right next-round work after this audit lands: substrate-honest edge construction. Edges that work on a representative universe, not just on mega-caps that survived to today. That's a real workstream and it starts from a clean foundation.

## End-of-cycle

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git checkout main
git merge --no-ff c-collapses-edge-audit -m "Merge branch 'c-collapses-edge-audit' — substrate-honest edge audit: <N>/<total> edges confirmed, surviving Sharpe <X>"
git push origin main
git worktree remove .claude/worktrees/ccoll1-edge-audit
```

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

## Report

Per-edge classification (CONFIRMED/DEGRADED/FALSIFIED), surviving-edges multi-year Sharpe, forward_plan update summary, final main commit hash.
```

## C-collapses-1.25 — Factor decomposition on volume_anomaly + herding under substrate-honest universe

**Why this is added (2026-05-09 outside-reviewer dev recommendation):** The outside-reviewer dev specifically flagged that two edges were factor-decomposed against benchmark factors and produced t-stats > 4 (volume_anomaly t=4.36, herding t=4.49 — see `docs/Measurements/2026-04/oos_2025_decomposition_2026_04.md` and `project_ensemble_alpha_paradox_2026_04_30.md`). Those decompositions were on the static-109 substrate. **The cleanest single test of whether ANY genuine alpha survives F6 is to re-run the factor decomposition on the substrate-honest universe and check whether t-stats hold above 2.**

This is more surgical than C-collapses-1's per-edge audit (which produces a CONFIRMED/DEGRADED/FALSIFIED ladder for ALL active edges); this targets the two specific names that previously produced statistically-significant alpha. ~2 hr budget.

If both t-stats hold up at >2: those are 2 genuine real edges to build on, just at smaller scale than thought. If both collapse below 2: the factor decomposition was substrate-dependent and the alpha thesis is in deeper question. **This is the result that decides the project's framing for the next quarter.**

### SETUP

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git worktree add .claude/worktrees/ccoll1-25-factor-decomp -b c-collapses-factor-decomp
cd .claude/worktrees/ccoll1-25-factor-decomp
claude
```

### PROMPT

```
You are working on the ArchonDEX trading system. Read CLAUDE.md first. Full autonomous cycle.

## Setup

```bash
git worktree add .claude/worktrees/ccoll1-25-factor-decomp -b c-collapses-factor-decomp
cd .claude/worktrees/ccoll1-25-factor-decomp
```

## Background

The 2026-04 oos_2025_decomposition (`docs/Measurements/2026-04/oos_2025_decomposition_2026_04.md`) ran factor decomposition (FF5 + momentum) on each edge's per-bar return contribution. Two edges produced statistically-significant intercept (alpha) AFTER controlling for known factors:
- volume_anomaly_v1: t=4.36, alpha ≈ 0.0006/day
- herding_v1: t=4.49, alpha ≈ 0.0007/day

Memory: `project_ensemble_alpha_paradox_2026_04_30.md` reframes these results — they're real ensemble contributors despite Gate 1 standalone failures.

The F6 verdict (2026-05-09) showed those decompositions were measured on the static-109 substrate. If the alpha is substrate-dependent (i.e., comes from concentrated mega-cap positioning rather than genuine factor-orthogonal signal), the t-stats will collapse on substrate-honest universe.

## Goal

Re-run the factor decomposition on volume_anomaly_v1 and herding_v1 under `use_historical_universe=true`, on a multi-year window (2021-2024 inclusive — leave 2025 as semi-OOS).

### Steps

1. Generate per-bar attribution streams for both edges on substrate-honest universe (similar to how the per-edge audit is done; the C-collapses-1 audit's machinery may already produce these — reuse if available)
2. Run `core/factor_decomposition.py` (or wherever the FF5+mom regression lives) on each edge's stream
3. Report:
   - Intercept (alpha) point estimate + 95% CI
   - t-stat on the intercept
   - Adjusted R² of the factor model
   - Per-year breakdown (2021/2022/2023/2024) — does the alpha persist or is it 2023-only?
4. Compare to the 2026-04 baseline (which had t=4.36 and 4.49 on static-109)

### Acceptance criteria

- Audit doc at `docs/Measurements/2026-05/factor_decomp_substrate_honest_2026_05_<date>.md`
- Per-edge t-stat with 4 different verdict buckets:
  - **HOLD UP** (t > 2.0 on substrate-honest, both edges): 2 real edges to build on
  - **PARTIAL** (one holds, one collapses): 1 real edge; investigate why the other was substrate-dependent
  - **REGIME-CONDITIONAL** (t > 2.0 in 2023 only, < 2 elsewhere): edges work in broad-participation regimes only — this overlaps with the multi-year-dilution-decomposition's finding
  - **COLLAPSE** (t < 2.0 both): factor decomposition itself was substrate-dependent; alpha thesis in question
- Per-year breakdown to identify whether the 2023 hold-up reflects genuine factor exposure or artifact

### Hard constraints

- DO NOT modify Engine B / live_trader/
- DO NOT touch `data/governor/` outside the harness's snapshot scope
- DO NOT promote any edges based on this dispatch (it's a diagnostic, not a decision)
- Branch: `c-collapses-factor-decomp`
- Time budget: 2-3 hours

### End-of-cycle

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git checkout main
git merge --no-ff c-collapses-factor-decomp -m "Merge branch 'c-collapses-factor-decomp' — factor decomp on substrate-honest universe, verdict: <HOLD_UP|PARTIAL|REGIME_CONDITIONAL|COLLAPSE>"
git push origin main
git worktree remove .claude/worktrees/ccoll1-25-factor-decomp
```

Co-Authored-By in commit(s): Claude Opus 4.7 (1M context) <noreply@anthropic.com>

### Report

Per-edge t-stat (substrate-honest), per-year breakdown, verdict bucket, comparison to 2026-04 baseline (t=4.36 and 4.49 on static-109), final main commit hash.
```

---

## C-collapses-1.5 — Concentration-equivalent capital test (LOAD-BEARING follow-on)

**Why this is the load-bearing test (added 2026-05-09 per multi-year-dilution analysis):** The C-collapses-1 audit will find that most edges produce near-zero or negative Sharpe at substrate-honest universe with normal capital. That's expected — `docs/Measurements/2026-05/multi_year_dilution_decomposition_2026_05_09.md` showed ~91% of the 2024 substrate gap was pure dilution on shared mega-caps. The tiny per-trade signals (~$1/trade on each name) drown when capital allocation drops 4.4×.

The right next test is: **do the same edges produce signal on substrate-honest universe at concentration-equivalent capital?** Two outcomes possible, both informative:

1. **Sharpe recovers under scaled capital** → edges have small per-name signal that needs concentration to surface. The path forward is **deliberate small-universe construction** with explicit rationale (an asymmetric-upside or concentrated-quality sleeve). The 109-name list's curation was accidental; build it intentionally.
2. **Sharpe stays low under scaled capital** → the system has no per-name alpha; the static-109 result was 100% concentration accident. The path forward is **genuine new alpha generation** (substrate-honest edge construction per C-collapses-2), not portfolio-construction tweaks.

This test alone doesn't tell us whether to ship — it tells us which workstream to fund. It's the cheapest path to that decision.

### SETUP

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git worktree add .claude/worktrees/ccoll1-5-cap-equiv -b c-collapses-cap-equiv
cd .claude/worktrees/ccoll1-5-cap-equiv
claude
```

### PROMPT

```
You are working on the ArchonDEX trading system. Read CLAUDE.md first. Full autonomous cycle.

## Setup

```bash
git worktree add .claude/worktrees/ccoll1-5-cap-equiv -b c-collapses-cap-equiv
cd .claude/worktrees/ccoll1-5-cap-equiv
```

## Background

C-collapses-1 (just merged) established the substrate-honest per-edge baseline at NORMAL capital. As expected, most edges produce near-zero or negative Sharpe — confirmed by the multi-year-dilution decomposition (`docs/Measurements/2026-05/multi_year_dilution_decomposition_2026_05_09.md`): the strategy's per-trade signal is too small to survive 4.4× position-size dilution.

The load-bearing question now: do those same edges produce signal at concentration-equivalent capital on substrate-honest universe?

## Goal

Run a controlled test: SAME edges, SAME substrate-honest universe, but CAPITAL scaled to keep average per-name position size equal to the static-109 baseline.

The static-109 baseline allocates ~$1.83k average position. The substrate-honest universe with the same total capital allocates ~$420 average position (4.4× smaller). To make positions comparable, the test multiplies total capital by ~4.4 (or equivalently scales position-sizing parameters).

### Implementation options

Pick the cleanest:

OPTION A — scale starting equity 4.4× and `risk_per_trade` 1× (per-trade dollar risk scales with equity). Simplest implementation; preserves all other parameters.

OPTION B — scale `risk_per_trade` 4.4× while keeping starting equity constant. Mathematically equivalent but might trip volatility guards.

OPTION C — scale `fill_share_cap` (currently 0.20) and the per-trade dollar caps. More surgical but needs careful trace through the position-sizing pipeline.

Recommend Option A unless it breaks an unrelated invariant (e.g., risk_engine assumes max_drawdown_pct against starting equity — fine because it's a percent).

### Two tests

#### Test 1: 2024 only (the largest collapse year)

```bash
PYTHONHASHSEED=0 python -m scripts.run_multi_year --years 2024 --runs 3 \
  --use-historical-universe --starting-equity-multiplier 4.4 \
  --output docs/Measurements/2026-05/cap_equiv_2024_<date>.md
```

(May need to add `--starting-equity-multiplier` CLI flag — implement if absent.)

Compare to:
- Static-109 2024 baseline (Sharpe 1.890)
- Universe-aware 2024 normal capital (Sharpe 0.268)

Expected outcomes:
- Sharpe recovers to ≥1.4 → concentration was the alpha; small-universe construction is the path forward
- Sharpe stays at 0.2-0.6 → no per-name signal; need genuine new alpha
- Sharpe in 0.7-1.3 range → ambiguous; both effects present

#### Test 2: 2023 (the year that already worked at normal capital)

Same setup, year 2023. Expected: Sharpe stays roughly the same (1.292 → 1.4 with scaled capital, modest improvement). 2023 had broad-participation; concentration-equivalent shouldn't swing it much.

If Test 2 swings dramatically, that contradicts the dilution-decomposition finding and is itself important data.

### Acceptance

- Audit doc at `docs/Measurements/2026-05/cap_equiv_test_2026_05_<date>.md` with:
  - Sharpe under scaled capital, both tests
  - Per-edge contribution under scaled capital (use the same per-edge harness from C-collapses-1)
  - Verdict: which of the 3 outcomes (above)
  - Recommendation for next workstream

### Hard constraints

- DO NOT modify Engine B / live_trader/
- DO NOT touch `data/governor/` outside the harness's snapshot scope
- The `--starting-equity-multiplier` flag (or equivalent) MUST default to 1.0 (no regression on existing measurements)
- Branch: `c-collapses-cap-equiv`
- Time budget: 3-4 hours

### Honest interpretation guidance

This test is a fork in the road. If concentration-equivalent recovers Sharpe, the project pivots to deliberate small-universe construction (asymmetric-upside framing per `project_retail_capital_constraint_2026_05_01.md`). If it stays low, the project pivots to genuine new alpha generation. Don't soften the verdict — both outcomes are real workstreams; the difference is which one funds.

### End-of-cycle

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git checkout main
git merge --no-ff c-collapses-cap-equiv -m "Merge branch 'c-collapses-cap-equiv' — concentration-equivalent capital test, verdict: <SIGNAL_NEEDS_CONCENTRATION|NO_PER_NAME_ALPHA|AMBIGUOUS>"
git push origin main
git worktree remove .claude/worktrees/ccoll1-5-cap-equiv
```

Co-Authored-By in commit(s): Claude Opus 4.7 (1M context) <noreply@anthropic.com>

### Report

2024 + 2023 Sharpes under scaled capital, per-edge contribution table, verdict bucket, primary recommendation.
```

---

## C-collapses-2 — Substrate-honest edge construction kickoff (after C-collapses-1.5)

**Why this is conditional:** Whether C-collapses-2 fires depends on C-collapses-1.5's verdict.

- If **SIGNAL_NEEDS_CONCENTRATION**: C-collapses-2 reframes as "deliberate small-universe construction" — building an explicit asymmetric-upside or concentrated-quality sleeve with intentional name selection. Different work than below.
- If **NO_PER_NAME_ALPHA**: C-collapses-2 is "substrate-honest edge construction" — genuine new alpha generation. The skeleton below applies.
- If **AMBIGUOUS**: Re-run with finer-grain capital scaling (1×, 2×, 3×, 4.4×, 6×) to map the curve. Workstream definition deferred until the curve is read.

(Skeleton — flesh out after C-collapses-1.5)

```
After C-collapses-1.5 confirms (verdict: NO_PER_NAME_ALPHA) that the system has no per-name alpha at any capital scaling, kick off substrate-honest edge construction.

Focus: edges that exploit small-cap inefficiencies, sector rotation, or factors that work on representative universes (not mega-cap-tilted by selection). Reference: project_thematic_conviction_gap_2026_05_01.md flagged the narrative-picks gap. Combined with substrate honesty, the path forward is edges that work where mega-cap edges fail.

This is a multi-week workstream, not a single dispatch. The first dispatch identifies 1-2 candidate edges and proves them out on the substrate-honest universe.

(Detailed prompt to be drafted at activation time, using C-collapses-1.5's verdict to set the framing.)
```

---

# Director-side notes

- Each Phase C dispatch follows the same end-of-cycle pattern as Phase A: agent does the merge + push + worktree-remove with user approval
- After B1 verdict lands, copy the matching branch's first dispatch into a fresh `claude` session
- Update `/Users/jacksonmurphy/.claude/plans/foamy-foraging-horizon.md` Phase C section with the activated branch's name + commit hashes as they merge
- These are first-dispatch sketches; the second/third dispatches in each branch should be flesh-outed at the time of dispatch using current state (avoid premature specificity)

The point of pre-drafting Phase C: when B1 returns, we don't lose 2-3 hours of waiting time drafting fresh — we paste the matching branch's prompt and resume momentum.
