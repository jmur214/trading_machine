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

## C-collapses-2 — DEFERRED indefinitely (2026-05-09 evening reframe)

**Status:** parked until C-remeasure verdict (after engine completion).

**Reason:** The 2026-05-09 evening user reframe identified that the substrate-honest result of 0.507 reflects "the strategy operating without portfolio management on representative universe" — not a fair test of the architecture. The engines aren't operating per their charters (Engine C's `compute_target_allocations` is never called; HRP+Turnover live in Engine A's signal_processor; Engine D produces 0 promoted edges; Engine E HMM is empirically coincident). Building Goal C / Moonshot Sleeve on top of an incomplete foundation skips the prerequisite work.

The user's framing: *"if we can't get the bones working properly we shouldn't be working on the golden apple yet."*

C-collapses-2 (substrate-honest edge construction OR Moonshot Sleeve scoping) becomes meaningful AFTER:
1. The C-engines-N dispatches complete the engine work
2. C-remeasure produces the engine-complete substrate-honest baseline
3. The new pre-commit gate is defined against that baseline
4. The verdict bucket from C-engines validates that the architecture has signal at all

If C-remeasure shows engine-complete + substrate-honest produces meaningful Sharpe → Goal C scoping resumes.
If C-remeasure shows engine-complete + substrate-honest produces near-zero Sharpe → fundamental rethink. The system as architected may not be a deployable trading strategy regardless of edge construction.

---

# C-engines — engine completion (2026-05-09 evening structural review)

**Why this section exists:** The kill thesis triggered 2026-05-09 evening. Pre-commit said *"net of all costs incl. taxes + borrow."* Universe-aware 2025 pre-tax 0.436; after-tax estimated negative; missing-CSV upper bound pushes lower. Strict reading triggers.

The structural review that the pre-commit calls for = engine completion. Engine C activation was the original lead deliverable; **as of 2026-05-09 night (post-`cae2002`)**, Engine C is closed (F4 inversion resolved; HRP/Turnover relocated; signal_processor 715→522 LOC). The original framing's claim that `compute_target_allocations` was "never called" was empirically wrong — `BacktestController._prepare_orders:508` wired it all along (see correction in `forward_plan.md` 2026-05-09 night block + lessons rule #13). What WAS misplaced (HRP/Turnover in signal_processor) is now correctly located.

> **Key insight surfaced by C-engines-1's determinism follow-on (2026-05-07):** the audit's surviving-edges 0.9154 mean Sharpe was measured via `exact_edge_ids` mode — bypassing tier filtering. In production-default mode, only 1 of the 6 surviving edges is `tier="alpha"` (volume_anomaly_v1); the other 5 are `tier="feature"` (research inputs that need the meta-learner). MetaLearner is default-OFF. So **production-default and audit-mode are not measuring the same system**. The audit-geometry note (`docs/Measurements/2026-05/c_engines_1_determinism_followon_2026_05_07.md`) captures the full finding. **Implication for the dispatch queue: MetaLearner re-enable becomes higher priority than originally scoped — possibly inserted as a new C-engines-1.5 between Engine C activation and Engine E HMM work.**

Remaining engine drift (4 of 6 engines):
- HRPOptimizer + TurnoverPenalty live in Engine A's `signal_processor.py:228-242` (charter inversion F4 from audit) ✓ **CLOSED** by C-engines-1 (cae2002)
- Engine A's `EDGE_CATEGORY_MAP` still imported from Engine F (smaller charter inversion; closes in C-engines-5)
- No portfolio-level vol-targeting; no correlation-aware sizing in Engine B (C-engines-2 propose-first)
- Engine D's Discovery cycle has produced 0 promoted edges across the project's history (C-engines-4 Bayesian opt scaffolding)
- Engine E's HMM is empirically coincident (C-engines-3 minimal-HMM on leading FRED features)
- **NEW (2026-05-07 night):** MetaLearner default-OFF means 5 of 6 surviving edges are inert in production. Re-attempt under substrate-honest 6-edge baseline is queued.

Engine completion = make each engine actually do what its charter specifies. Then re-measure. The result becomes the new pre-commit baseline.

These dispatches are substrate-independent — they don't claim Sharpe; they restore architecture. Each one closes one or more open audit findings. They can run sequentially or with limited parallelism (each modifies different files, but C-engines-1 and C-engines-5 both touch signal_processor.py so should sequence).

## C-engines-1 — Engine C activation (closes F4, makes portfolio management real)

**Why this is FIRST:** It's the lowest-effort, highest-leverage engine work. Engine C's `compute_target_allocations` and `PortfolioPolicy.allocate()` are already written — they just aren't wired into the backtest loop. This dispatch wires them, moves the misplaced HRP+Turnover code OUT of `signal_processor.py`, and restores Engine A → B → C dataflow per `docs/Core/engine_charters.md`.

This closes audit finding F4 (charter inversion), reduces signal_processor from 715 LOC to a smaller pure-signals module, and surfaces whether the portfolio-management code that was DEFINED but UNCALLED actually contributes to the strategy.

### SETUP

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git worktree add .claude/worktrees/c-engines-1 -b c-engines-1-portfolio-activation
cd .claude/worktrees/c-engines-1
claude
```

### PROMPT

```
You are working on the ArchonDEX trading system. Read CLAUDE.md first. Full autonomous cycle.

## Setup

```bash
git worktree add .claude/worktrees/c-engines-1 -b c-engines-1-portfolio-activation
cd .claude/worktrees/c-engines-1
```

## Background — somber framing

The kill thesis triggered 2026-05-09 evening. Phase C reframed from edge audit + Moonshot pivot to ENGINE COMPLETION (the structural review the pre-commit calls for). The user surfaced that Engine C's portfolio-management logic is defined but never called — the backtest loop uses Engine A's signals → Engine B's per-trade sizing → PortfolioEngine's accounting only. There is no portfolio-level diversification or correlation-aware allocation today.

This dispatch closes that gap. It's substrate-independent — no Sharpe claims; it's architecture restoration.

## Goal — three deliverables

### 1. Wire Engine C's allocation logic into the backtest loop

Read carefully:
- `engines/engine_c_portfolio/portfolio_engine.py:310-323` — `compute_target_allocations()` is defined
- `engines/engine_c_portfolio/policy.py:108` — `PortfolioPolicy.allocate()` is the actual logic
- `engines/engine_c_portfolio/optimizer.py` — `PortfolioOptimizer` class
- `engines/engine_c_portfolio/optimizers/hrp.py` — HRP implementation
- `orchestration/mode_controller.py` — the backtest loop that needs to call it

Currently the backtest loop sources signals from `Engine A.compute_signals()`, sizes positions via `Engine B.size_position()`, and books fills via `PortfolioEngine.apply_fill()`. The allocation step is skipped entirely.

Wire in: after Engine A produces signals and before Engine B sizes positions, call `PortfolioEngine.compute_target_allocations(signals, price_data, equity)` to get target weights. Use those weights to drive sizing. The policy's existing logic (HRP, turnover penalty, regime gating, etc.) becomes the portfolio-composition layer.

Gating: behind a config flag `engine_c_active: false` (default false to preserve current measurement reproducibility). When true, the allocation step fires; when false, current path. Same pattern as B1's `use_historical_universe` flag.

### 2. Move HRP + TurnoverPenalty OUT of signal_processor.py

Read:
- `engines/engine_a_alpha/signal_processor.py:228-242` — HRPOptimizer + TurnoverPenalty currently instantiated and called HERE (charter inversion F4 from the 2026-05-06 audit)

These should live in Engine C, not Engine A. Move:
- The `HRPOptimizer` instantiation and call to `engines/engine_c_portfolio/policy.py` (or a new optimizer wrapper inside Engine C)
- The `TurnoverPenalty` similarly
- The decision logic that decides when to apply each (regime-conditional, edge-count-conditional, etc.) — move into the policy

`signal_processor.py` should reduce in LOC (currently 715, target < 500 per audit's "approaching god-class threshold" finding). What stays in signal_processor: edge aggregation (weighted_sum, the per-edge → per-ticker score collation). What moves out: any portfolio-composition logic.

### 3. Tests + integration check

- Unit test: `compute_target_allocations` produces expected weights for a known signal set + price panel
- Integration test: backtest with `engine_c_active=true` produces a different (or determinism-equivalent) run from `engine_c_active=false`. Both should be bitwise-identical within their own flag setting (3-rep determinism check).
- LOC test: `signal_processor.py` should be smaller after the move; HRP/Turnover imports should NOT appear in Engine A files.
- Charter check: `grep -rn "HRPOptimizer\|TurnoverPenalty" engines/engine_a_alpha/` should return zero hits.

### 4. Audit doc

`docs/Measurements/2026-05/engine_c_activation_2026_05_<date>.md` documenting:
- Before/after: where HRP + Turnover lived; where they live now
- LOC delta: signal_processor.py size before/after
- Charter check: dependency direction A → C is now correct
- Determinism harness 3-rep check on both flag values
- Any unexpected findings (the existing PortfolioPolicy.allocate may have bugs that surface only when actually called — document them)

## Hard constraints

- DO NOT modify Engine B / live_trader/ (CLAUDE.md propose-first)
- The `engine_c_active` flag MUST default false (no regression on prior measurements, even though those measurements are now substrate-conditional + engine-incomplete)
- Don't claim Sharpe lift or any measurement contribution — this is architecture restoration, not alpha. If you accidentally find a Sharpe change, REPORT IT but don't promote it.
- DO NOT touch `data/governor/` outside the harness's snapshot scope
- Stay inside `engines/engine_a_alpha/`, `engines/engine_c_portfolio/`, `orchestration/`, `config/`, `tests/`, `docs/Measurements/2026-05/`
- Branch: `c-engines-1-portfolio-activation`
- Time budget: 4-6 hours

## Honest interpretation guidance

This is foundation work, not a Sharpe claim. The success criterion is "Engine C is real now; charter inversion closed; signal_processor pure-signals; backtest loop uses Engine C's allocation step." Whether the Sharpe goes up, down, or stays the same is interesting data but not the goal. The goal is correct architecture.

The gauntlet's previous "wins" were generated by an architecturally-incorrect system. Restoring the architecture might reveal that Sharpe drops further (the misplaced HRP code was effectively doing portfolio management informally; making it formal and adding correlation-awareness might surface that the strategy hasn't been doing what we thought it was doing).

EITHER outcome is honest. The point is: the next pre-commit gate (after C-remeasure) gets defined against an architecturally-correct baseline.

## End-of-cycle

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git checkout main
git merge --no-ff c-engines-1-portfolio-activation -m "Merge branch 'c-engines-1-portfolio-activation' — Engine C activated, F4 charter inversion closed, signal_processor pure-signals"
git push origin main
git worktree remove .claude/worktrees/c-engines-1
```

Co-Authored-By in commit(s): Claude Opus 4.7 (1M context) <noreply@anthropic.com>

## Report

LOC delta on signal_processor.py, files modified, integration test result, 3-rep determinism (both flag values), charter check (grep), final main commit hash. Note any unexpected behavior surfaced by actually calling `PortfolioPolicy.allocate()` for the first time.
```

## C-engines-2 — Engine B portfolio vol-targeting + correlation-aware sizing (PROPOSE-FIRST)

**Status: scoping doc, not a fire-and-forget dispatch.** Per CLAUDE.md, Engine B work requires explicit user approval before any code lands. This section captures the design space for the user to make decisions on; only after the user resolves the open questions does this become an actionable dispatch.

### Current state of Engine B (`engines/engine_b_risk/risk_engine.py`, 955 LOC)

Read for orientation:
- `RiskConfig` (line 12): config schema for risk-engine behavior
- `RiskEngine` (line 62): the live class. Per-trade ATR-based sizing; per-position stops; advisory exposure cap; vol-target multiplier; risk_per_trade_pct (default 0.025).

**What Engine B does today:**
- Sizes each trade individually to a per-trade vol budget (`risk_per_trade_pct` of equity)
- Caps gross exposure via `exposure_cap_enabled` (advisory from Engine E regime)
- Applies vol-target multiplier (max 2.0x leverage when realized vol below target)
- Applies stop-loss + take-profit per position
- Has wash-sale-avoidance ledger (prior work; partially-validated)

**What Engine B doesn't do (per audit + this engine-completion review):**
- **Portfolio-level vol targeting.** Per-trade vol-targeting can produce portfolio vol radically off-target if positions are correlated. The current `vol_scalar` upper-cap-of-2.0 hits every bar in low-realized-vol regimes (memory `project_vol_target_in_sample_measured_2026_04_24`). This is "max 2x leverage when calm" — not regime-aware portfolio vol management.
- **Correlation-aware sizing.** Each trade is sized as if independent. A portfolio of 10 mega-cap tech longs has correlation ~0.6-0.8; the realized portfolio vol is much higher than the sum of per-trade vol budgets. The system survives this because total positions are small, but it's a structural gap.
- **GARCH/HAR-RV vol forecasting.** Realized ATR is backward-looking; better-conditioned forecasts exist (ARCH package, ~100 LOC).
- **Stress testing.** Current portfolio replayed against historical regimes (2008 GFC, 2020 COVID, 2022 bear). Builds the muscle, doesn't claim Sharpe.

### Open design questions for the user

**Q1 — Scope.** Three escalating levels:
- (a) **Minimum viable portfolio vol-target.** Replace per-trade `risk_per_trade_pct` with a portfolio-vol target (e.g., 12% annualized). Each bar, scale all positions to keep realized portfolio vol = target. ~150 LOC. ~2 days.
- (b) **(a) + correlation-aware sizing.** Add covariance matrix input from Engine C (which it should already be computing per the C-engines-1 work). Position sizes scale via inverse-covariance contribution to portfolio vol. ~250 LOC. ~3 days.
- (c) **(b) + GARCH/HAR-RV forecasting.** Replaces realized ATR with conditional-vol forecasts. Materially better in regime transitions. ~350 LOC + arch dependency. ~4-5 days.

Recommendation: start with (a). It's the cleanest test of "does portfolio vol-targeting matter for the Sharpe question?" If (a) materially helps, escalate to (b). If (a) doesn't help, the engine isn't the issue.

**Q2 — Backward compatibility.** Existing measurements were taken under per-trade vol-targeting. Two options:
- **Hard cutover:** new portfolio-vol behavior becomes default; old behavior is removed. Cleanest, but loses reproducibility for prior measurements.
- **Flag-gated:** `engine_b_portfolio_vol_target: false` (default) preserves current path; flag-on enables new behavior. Same pattern as B1's `use_historical_universe`.

Recommendation: flag-gated. Same discipline as Phase A.

**Q3 — Vol target value.** What's the target? Three reasonable defaults:
- 8% annualized (conservative; Goal A retiree-aligned per fitness profile)
- 12% annualized (balanced; matches typical balanced-fund volatility)
- 15% annualized (matches SPY's typical long-run vol; aggressive)

Recommendation: 12% as default, configurable per fitness profile (`config/fitness_profiles.yml` already supports profile-conditional behavior).

**Q4 — Interaction with Engine C activation (C-engines-1).** Once Engine C is wired (C-engines-1), the portfolio composition has weights. Engine B's portfolio-vol-target needs the COMPOSED portfolio's vol, not the raw signal-weighted portfolio's vol. So C-engines-2 sequences AFTER C-engines-1.

**Q5 — Branch + safety.** This is Engine B work. CLAUDE.md says: stop and propose first for "Engine B / live_trader/." This scoping doc IS the proposal. The user's explicit approval is required before any code lands.

### Recommended defaults — the user just approves/rejects each

Updated 2026-05-07 to reduce the user's decision surface from open-ended scoping to four yes/no-or-pick-one questions. Recommended defaults shown first; the rationale flags what would tip the recommendation the other way.

#### Q1 — Scope: **(a) MV portfolio vol-target only**

**Recommendation:** start with (a). The minimum-viable test of "does portfolio vol-targeting matter for the substrate-honest Sharpe at all?" If (a) materially helps, escalate to (b). If (a) doesn't help, the engine isn't the bottleneck and (b)/(c) would be wasted scope. ~150 LOC, ~2 days.

Tip the other way if: you have direct evidence that correlation-aware sizing is the load-bearing fix (we don't, currently — we have evidence that something is wrong with portfolio composition, but not the specific shape).

#### Q2 — Backward compat: **flag-gated (`engine_b_portfolio_vol_target: false` default)**

**Recommendation:** flag-gated. Same pattern as Phase A (`use_historical_universe`) and B1's universe-loader wire. Preserves prior measurement reproducibility. Hard-cutover wins are illusory because pre-fix measurements remain in the project's measurement history; flag-gated keeps them comparable.

Tip the other way if: you decide the prior measurements are so substrate-conditional that reproducing them isn't valuable (likely true for some, but the discipline of "default false → opt-in" costs nothing).

#### Q3 — Vol target value: **12% annualized as default, profile-conditional**

**Recommendation:** 12% as default. Matches typical balanced-fund vol; below SPY's ~15% so it's net-conservative; above the strategy's current ~4% realized vol so it would meaningfully scale up positions. Profile-aware override: `retiree` profile → 8%, `growth` profile → 15%, `balanced` → 12% (the architecture in `config/fitness_profiles.yml` already supports profile-conditional behavior).

Tip the other way if: your account is genuinely retirement-only (then 8%) or you're explicitly building a growth sleeve (then 15% — though this contradicts Goal A compounding behaviour).

#### Q4 — Sequence: **AFTER C-engines-1 (fixed)**

**Recommendation:** confirmed. Engine B's portfolio-vol-target needs the COMPOSED portfolio's vol, which requires Engine C's allocation layer to be wired (C-engines-1 deliverable). No alternative sequencing.

#### Q5 — Branch + safety: **propose-first acknowledged**

**Recommendation:** branch `c-engines-2-portfolio-vol-target`. CLAUDE.md propose-first explicitly satisfied by user approving Q1-Q3 above before this section gets rewritten as an actionable dispatch.

### How to approve

Reply with `Q1: a / Q2: flag-gated / Q3: 12% default / Q4: confirmed / Q5: approved` (or any divergent answer). When all five land, this section gets rewritten as a fully-fleshed actionable dispatch in the same shape as C-engines-1 / C-engines-3, and you fire it after C-engines-1 lands.

### Time budget when fired

Depends on scope choice. (a) = 2 days. (b) = 3 days. (c) = 4-5 days.

### Branch (when activated)

`c-engines-2-portfolio-vol-target`

---

## C-engines-3 — Engine E minimal-HMM on leading FRED features + Engine B de-grossing wire

**Why this works substrate-independently:** The HMM model itself is universe-independent. Engine E reads macro features (yield_curve_spread, credit_spread_baa_aaa, dollar_ret_63d, spy_vol_20d), trains an HMM, outputs a regime label. The wire-into-Engine-B step does require Engine B work, so this dispatch's deliverable #2 needs to be carefully scoped (it could be flag-gated or the dispatch could just produce the signal stream and Engine B integration stays a separate propose-first decision).

The 2026-05-06 cheap-validation Branch 3 finding (memory `project_cheap_input_validation_branch3_2026_05_06`) showed that VIX term structure is decisively coincident; the FRED features above carry forward signal but get drowned by coincident features when mixed in. This dispatch isolates the leading subset and tests whether they predict drawdowns.

### SETUP

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git worktree add .claude/worktrees/c-engines-3 -b c-engines-3-minimal-hmm
cd .claude/worktrees/c-engines-3
claude
```

### PROMPT

```
You are working on the ArchonDEX trading system. Read CLAUDE.md first. Full autonomous cycle.

## Setup

```bash
git worktree add .claude/worktrees/c-engines-3 -b c-engines-3-minimal-hmm
cd .claude/worktrees/c-engines-3
```

## Background

The 2026-05-06 cheap-validation work found:
- VIX term structure: coincident across all 4 tenor pairs (memory `project_cheap_input_validation_branch3_2026_05_06`)
- 4 FRED features (yield_curve_spread, credit_spread_baa_aaa, dollar_ret_63d, spy_vol_20d) carried a 78-day OOS lead before the 2025 -18.8% drawdown — drowned out by coincident features in the larger panel

The current Engine E HMM (`engines/engine_e_regime/hmm_classifier.py`) trains on the full panel and is empirically coincident (memory `project_regime_signal_falsified_2026_05_06`). Crisis AUC 0.49 on 20d-fwd drawdowns — coin flip.

The hypothesis: a minimal HMM trained on ONLY the 4 leading FRED features might recover the 78-day lead.

## Goal — three deliverables

### 1. Train fresh minimal-HMM on the 4 leading FRED features only

Read for orientation:
- `engines/engine_e_regime/hmm_classifier.py` — current HMM trainer
- `engines/engine_e_regime/macro_features.py` — feature panel construction
- `scripts/train_hmm_vix_term.py` — slice-1 training script (existing pattern to mirror)
- `data/macro/` — FRED feature CSVs

Implementation:
- New script `scripts/train_minimal_hmm.py`
- Loads ONLY: yield_curve_spread, credit_spread_baa_aaa, dollar_ret_63d, spy_vol_20d
- Trains HMM with N states (try 2, 3, 4 — pick by BIC/cross-validation)
- Outputs a regime label time series saved to `data/macro/minimal_hmm_states.parquet`
- Includes log of train/eval split + holdout metrics

### 2. Validate vs forward drawdowns

Reuse `scripts/validate_regime_signals.py` patterns:
- AUC vs SPY 20d-fwd drawdown ≤ -5%
- Coincident-vs-leading correlation flip (forward corr > trailing corr — the criterion the existing HMM fails)
- Per-state breakdown (which state precedes drawdowns)

Three variants to test (per `docs/Core/Ideas_Pipeline/regime_panel_slice_2_plan.md`):
- A: 4 leading FRED features alone
- B: A + VIX term as confirmation feature (does the dual gate help)
- C: A + VIX term as interaction term (nonlinear value test)

### 3. Wire-readiness assessment (do NOT actually wire into Engine B in this dispatch)

If at least one variant clears AUC > 0.55 AND coincident-leading flip:
- Document the wire-into-Engine-B integration plan in the audit doc (file:line refactor map)
- Engine B integration becomes a separate propose-first dispatch (CLAUDE.md requires Engine B work to be approved before code lands)
- DO NOT modify `engines/engine_b_risk/risk_engine.py` in this dispatch

If no variant clears the threshold:
- Document explicitly: "minimal-HMM on FRED features does not lead drawdowns at AUC > 0.55"
- Recommend the next experiment (paid options-history provider for IV skew, OR earnings-revision dispersion, OR retire the regime-conditional sleeve infra)

## Acceptance

- 3 minimal-HMM variants trained
- AUC + coincident-leading correlation flip + per-state breakdown for each
- Audit doc at `docs/Measurements/2026-05/minimal_hmm_2026_05_<date>.md`
- Verdict: which variant (if any) clears AUC > 0.55 AND coincident-leading flip
- Wire-into-Engine-B plan (NOT executed) if leading; "no signal found" recommendation if not
- New unit tests in `tests/test_minimal_hmm.py`

## Hard constraints

- DO NOT modify Engine B / live_trader/ in this dispatch (separate propose-first)
- DO NOT promote any HMM model to production
- Read-only on existing data; no new data integration required (uses existing FRED panel)
- Branch: `c-engines-3-minimal-hmm`
- Time budget: 3-4 hours

## Honest interpretation guidance

This is read-mostly research. The output is "does the leading FRED subset predict drawdowns?" Yes/no. If yes, Engine B integration becomes a separate workstream. If no, the regime-conditional sleeve infrastructure stays parked indefinitely (per the 2026-05-06 falsification).

## End-of-cycle

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git checkout main
git merge --no-ff c-engines-3-minimal-hmm -m "Merge branch 'c-engines-3-minimal-hmm' — minimal HMM on leading FRED features, verdict: <LEADING|PARTIAL|NOT_LEADING>"
git push origin main
git worktree remove .claude/worktrees/c-engines-3
```

Co-Authored-By in commit(s): Claude Opus 4.7 (1M context) <noreply@anthropic.com>

## Report

AUC for each variant + horizon (5d, 20d, 60d), coincident-leading correlation table, branch verdict, Engine B integration plan if leading, final main commit hash.
```

---

## C-engines-4 — Engine D Bayesian opt scaffolding (replaces GA noise factory)

**Why this is autonomous-improvement territory:** Engine D's GA (`engines/engine_d_discovery/genetic_algorithm.py`) has been documented as a "strip-mined search space" that produces 0 promoted edges (memory `project_alpha_diagnosis_2026_04_22` and the 2026-04-24 finding still open in `health_check.md`). Replacing the search method with Bayesian optimization via BoTorch is substrate-independent infrastructure work — it doesn't claim Sharpe; it produces candidates that still go through the existing gauntlet.

The dev's earlier pushback (don't optimize on absent signal) applies at the EDGE level: Bayesian opt won't manufacture alpha that doesn't exist. But the engine MACHINERY upgrade is still correct — replacing a known-broken search method is unambiguous improvement, and the gauntlet still gates anything Bayesian opt produces.

### SETUP

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git worktree add .claude/worktrees/c-engines-4 -b c-engines-4-bayesian-opt
cd .claude/worktrees/c-engines-4
claude
```

### PROMPT

```
You are working on the ArchonDEX trading system. Read CLAUDE.md first. Full autonomous cycle.

## Setup

```bash
git worktree add .claude/worktrees/c-engines-4 -b c-engines-4-bayesian-opt
cd .claude/worktrees/c-engines-4
```

## Background

Engine D's discovery loop uses a genetic algorithm at `engines/engine_d_discovery/genetic_algorithm.py:25` (called from `discovery.py:184` `_run_ga_evolution`). The GA has produced 0 promoted edges across the project's history despite many cycles. The 2026-04-24 finding (still open in `docs/State/health_check.md`) documents the search space as effectively strip-mined — the gene vocabulary doesn't allow the GA to find new alpha.

Replacing GA with Bayesian optimization via BoTorch (`pip install botorch`) is the audit's recommendation (F10-F11 territory). The Gaussian-process surrogate model is much better-suited to this problem than evolutionary search.

## Goal — three deliverables

### 1. New `engines/engine_d_discovery/bayesian_optimizer.py`

- `class BayesianOptimizer` with the same interface contract as `GeneticAlgorithm` (so it can be a drop-in)
- Uses BoTorch for the GP surrogate + acquisition (Expected Improvement default)
- Search space defined by the same gene vocabulary as the GA (don't change the parameter space yet — that's a separate workstream)
- Initialization: 10 random points (Sobol sequence); then 20 BO iterations
- Returns candidates as `List[Dict[str, Any]]` matching the GA's output format

### 2. `discovery.py:_run_ga_evolution` becomes `_run_search_evolution` with method dispatch

- Read config flag `discovery_search_method: "ga" | "bayesian"` (default "ga" — no regression)
- Dispatch to the appropriate optimizer
- Same downstream gauntlet processing for either method

### 3. Tests + integration

- `tests/test_bayesian_optimizer.py` with at least:
  - Synthetic test: known-good objective (e.g., parabola peak at `(0.5, 0.5)`) — BO finds it within 30 calls
  - Same-interface test: returns same shape as GA output
  - Determinism: same seed produces same trajectory
- Integration: discovery cycle runs end-to-end with `discovery_search_method: "bayesian"` and produces candidates that hit the gauntlet
- Determinism harness: 3-rep run with the new method should be bitwise-identical (set BoTorch's torch seed)

## Acceptance

- BoTorch added to project dependencies (verify `pip install botorch torch` works in venv)
- BayesianOptimizer class produces candidates indistinguishable in shape from GA
- Discovery cycle works end-to-end with the new method
- 6+ new tests; all pass
- Audit doc at `docs/Measurements/2026-05/engine_d_bayesian_opt_2026_05_<date>.md`
- DOES NOT promote any edges; Bayesian-opt-produced candidates still go through the existing gauntlet (which currently kills 30/30 candidates per `project_gauntlet_consolidated_fix_2026_05_01`)

## Hard constraints

- DO NOT modify the gauntlet itself (validate_candidate); only the upstream candidate-generation
- DO NOT promote any edges based on this dispatch
- DO NOT modify Engine B / live_trader/
- The default `discovery_search_method: "ga"` MUST be preserved (no regression on prior measurement reproducibility)
- Branch: `c-engines-4-bayesian-opt`
- Time budget: 6-8 hours

## Honest interpretation guidance

This is engine machinery, not alpha generation. The success criterion is "Bayesian opt is wired and produces gauntlet-eligible candidates." Whether those candidates survive the gauntlet is a separate question — addressed by C-collapses-1's gauntlet-on-substrate-honest-universe work. The two workstreams compose.

## End-of-cycle

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git checkout main
git merge --no-ff c-engines-4-bayesian-opt -m "Merge branch 'c-engines-4-bayesian-opt' — Bayesian optimization scaffolding for Engine D, GA replaced under flag"
git push origin main
git worktree remove .claude/worktrees/c-engines-4
```

Co-Authored-By in commit(s): Claude Opus 4.7 (1M context) <noreply@anthropic.com>

## Report

Files added/modified, BoTorch dependency added, synthetic-objective convergence test result, determinism harness verification, final main commit hash.
```

---

## C-engines-5 — Engine A pure-signals refactor (sequenced AFTER C-engines-1)

**Why this sequences after C-engines-1:** C-engines-1 moves HRP+TurnoverPenalty out of `signal_processor.py:228-242`. C-engines-5 strips remaining cross-charter responsibilities. Both touch the same file; sequence them.

### SETUP

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git worktree add .claude/worktrees/c-engines-5 -b c-engines-5-pure-signals
cd .claude/worktrees/c-engines-5
claude
```

### PROMPT

```
You are working on the ArchonDEX trading system. Read CLAUDE.md first. Full autonomous cycle.

## Setup

```bash
git worktree add .claude/worktrees/c-engines-5 -b c-engines-5-pure-signals
cd .claude/worktrees/c-engines-5
```

## Background

After C-engines-1 moved HRPOptimizer and TurnoverPenalty OUT of `engines/engine_a_alpha/signal_processor.py`, the file should be smaller but still contains residual cross-charter responsibilities. This dispatch finishes the pure-signals refactor.

Read for orientation:
- `engines/engine_a_alpha/signal_processor.py` (post-C-engines-1 size)
- `engines/engine_a_alpha/alpha_engine.py` (984 LOC; complementary)
- `docs/Core/engine_charters.md` — Engine A's charter (signals only)

## Goal — three deliverables

### 1. Identify and move all remaining cross-charter responsibilities

Audit signal_processor.py post-C-engines-1 for:
- Risk-engine-shaped logic (anything making capital decisions) → should be Engine B
- Portfolio-shaped logic (anything making cross-ticker allocation decisions) → should be Engine C (already moved in C-engines-1, but double-check)
- Lifecycle-shaped logic (anything reading/mutating edges.yml) → should be Engine F
- Regime-shaped logic (anything making regime calls beyond consuming) → should be Engine E

`grep -n "EDGE_CATEGORY_MAP\|regime_tracker\|edges_yaml\|risk_per_trade" engines/engine_a_alpha/signal_processor.py`

The known charter inversion documented in `health_check.md`: signal_processor imports `EDGE_CATEGORY_MAP` from `engine_f_governance/regime_tracker.py`. Move the taxonomy to `engines/engine_a_alpha/edge_taxonomy.py` (new file) and have Engine F import from there.

### 2. Calibrated probability outputs (refactor binary/ternary signals to probabilities)

Most edges output binary (1.0 / 0.0) or ternary (1.0 / 0.0 / -1.0) signals. Continuous probabilities (e.g., logistic-calibrated) carry richer information for downstream Engine C composition.

This is a deeper refactor; for this dispatch, scope is:
- Add `signal_strength: float` field alongside the existing binary/ternary `signal: int` in EdgeOutput
- Edges that already produce continuous signals (some Foundry features) populate this field
- Edges that don't (legacy edges) leave it None
- `signal_processor` weights by signal_strength when present, falls back to signal when not

This is additive — no edges break, but new edges can produce richer signal info.

### 3. Edge horizon metadata explicit

Each edge has an implicit holding period (e.g., V/Q/A is quarterly; momentum is daily). Make it explicit:
- Add `holding_period_bars: int` to EdgeSpec (default None)
- Edges that know their natural cadence populate this
- signal_processor uses it for sustained-score logic (currently hardcoded 0.3 for held positions per V/Q/A fix)

## Acceptance

- signal_processor.py LOC reduced toward < 500 (from current ~700 post-C-engines-1)
- `grep -rn "EDGE_CATEGORY_MAP" engines/engine_a_alpha/` returns import from edge_taxonomy.py only
- `grep -rn "from engines.engine_f_governance" engines/engine_a_alpha/` returns zero hits (charter direction restored)
- New tests in `tests/test_signal_processor_refactor.py` covering:
  - Charter check: A doesn't import from F
  - Calibrated probability path produces same output as binary path when signal_strength=signal
  - Holding-period metadata threading
- Determinism harness 3-rep on default config (signal_strength=None falls back to existing path) — bitwise identical to pre-refactor

## Hard constraints

- DO NOT modify Engine B / live_trader/
- DO NOT touch `data/governor/` outside the harness's snapshot scope
- Default behavior MUST be unchanged (signal_strength=None, holding_period_bars=None preserve existing path)
- Branch: `c-engines-5-pure-signals`
- Time budget: 6-8 hours

## End-of-cycle

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git checkout main
git merge --no-ff c-engines-5-pure-signals -m "Merge branch 'c-engines-5-pure-signals' — Engine A charter restored, calibrated probabilities + horizon metadata"
git push origin main
git worktree remove .claude/worktrees/c-engines-5
```

Co-Authored-By in commit(s): Claude Opus 4.7 (1M context) <noreply@anthropic.com>

## Report

LOC delta on signal_processor.py, charter check (grep), tests added, determinism harness result, final main commit hash.
```

## C-remeasure — Engine-complete substrate-honest multi-year (skeleton)

After all C-engines-N dispatches land + close their respective charter gaps, re-run the multi-year measurement on substrate-honest universe. THIS is the result that defines the next pre-commit gate. Three outcomes:

- **Sharpe meaningfully > 0.5 (e.g. 0.8+):** the architecture was the issue, not the strategy concept. New pre-commit at the new level. Resume forward feature work.
- **Sharpe 0.4-0.7:** the architecture was partially the issue. Per-edge audit on engine-complete substrate to identify what helps. Conservative pre-commit.
- **Sharpe ≤ 0.4 (engine-complete + substrate-honest still fails):** the system as architected is not a deployable strategy. Fundamental rethink. THIS is when Goal C / Moonshot Sleeve becomes the right next conversation — not before.

The C-remeasure outcome decides whether C-collapses-2 (Goal C scoping) ever fires.

---

# Director-side notes

- Each Phase C dispatch follows the same end-of-cycle pattern as Phase A: agent does the merge + push + worktree-remove with user approval
- After B1 verdict lands, copy the matching branch's first dispatch into a fresh `claude` session
- Update `/Users/jacksonmurphy/.claude/plans/foamy-foraging-horizon.md` Phase C section with the activated branch's name + commit hashes as they merge
- These are first-dispatch sketches; the second/third dispatches in each branch should be flesh-outed at the time of dispatch using current state (avoid premature specificity)

The point of pre-drafting Phase C: when B1 returns, we don't lose 2-3 hours of waiting time drafting fresh — we paste the matching branch's prompt and resume momentum.
