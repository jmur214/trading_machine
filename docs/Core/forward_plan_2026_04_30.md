# Forward Plan — 2026-04-30

> **Live plan.** Supersedes `forward_plan_2026_04_29.md` after Phase
> 2.10c diagnostics resolved the apparent paradox between Q3
> standalone falsification and the integration's per-year alpha.
> The 04-29 plan's body is historical context; its "Result" section
> documents the same-day OOS-gate failure that triggered Phase
> 2.10c; the architectural pivot below is the new live direction.

## What changed between 04-29 and 04-30

**Yesterday (04-29):** Phase 2.10b OOS gate failed three-way. 2025
OOS Sharpe -0.049, Universe-B Sharpe 0.225, both supposed alphas
(`volume_anomaly_v1`, `herding_v1`) fail standalone Gate 1. The
reading was "the system has no real alpha."

**Today (04-30):** Phase 2.10c diagnostic triage ran three pieces in
sequence + parallel — lifecycle counterfactual, 2025 OOS edge-by-edge
decomposition, per-edge per-year attribution across 2021-2025. Both
parallel agents independently identified `volume_anomaly_v1` as a
stable, every-year, every-regime contributor that **only trades that
way in the soft-paused config**. The standalone gauntlet failure was
real measurement, but the wrong test.

**The reconciliation (impact-knee math).** Realistic Almgren-Chriss
cost is `k × σ × √(qty/ADV) × 10000` — non-linear in trade size. In
the production ensemble, `risk_per_trade_pct = 2.5%` is split across
all firing edges → individual fills are small → `qty/ADV` stays
sub-knee → impact tax is single-digit bps → signal survives. In
standalone gauntlet, the same edge gets the full 2.5% per fill →
trade size is ~17× larger → crosses impact knee → cost tax eats the
signal. **Same edge, different costs, opposite verdict — both
correctly executed.**

**The system has real alpha. It's just wasted.**

## The diagnosis (as concrete as we can be)

Three structural problems consume most of what the alpha is producing:

### 1. Capital rivalry — no per-edge participation floor
- 2025: bottom-3 edges (`low_vol_factor_v1`, `atr_breakout_v1`,
  `momentum_edge_v1`) consumed **83% of fill share** for **-$5,645**
  realized losses
- Same year: top-2 best-PnL edges got **4.3% of fill share**
- Counterfactual: un-pausing momentum edges flipped
  `volume_anomaly_v1` per-fill avg from **+$10.12 to -$1.17** (191
  → 19 fills)
- Mechanism: position slots / sector caps / vol target are rivalrous.
  High-frequency momentum signals crowd out low-frequency anomaly
  signals.

### 2. Soft-pause weight leak
- `low_vol_factor_v1` was marked failed/paused (memory
  `project_low_vol_regime_conditional_2026_04_25`) but fired
  **1,613 times in 2025** for **-2.53%** annual contribution
- Mechanism: weight 0.5 × `regime_gate {benign:0.15, stressed:1.0,
  crisis:1.0}` — the regime_gate amplifies it back to full weight in
  exactly the regimes where it's worst
- "Paused" is currently a soft-pause-with-regime-amplification, not
  an actual pause for failed edges

### 3. No regime-aware slot reduction
- April-2025 `market_turmoil` regime: **-$3,551** simultaneous loss
  across 5 edges in one month — 122% of the full-year loss in that
  one month
- Mechanism: portfolio engine has no primitive to reduce concurrent
  slot count in stressed/crisis regimes, so all edges that fire in
  those regimes pile correlated losses on top of each other

## What's actually true about the alpha

Per-edge per-year attribution (Agent B, audit doc
`per_edge_per_year_attribution_2026_04.md`) on 2021-2025 integration
runs:

| Bucket | Count | Notes |
|---|---|---|
| Stable contributors (positive ≥4 of 5 years) | **2** | `volume_anomaly_v1` (+1.93% to +4.94%/yr), `herding_v1` (+0.55% to +2.43%/yr) |
| Regime-conditional | 2 | (positive in some years, clearly negative in others) |
| Weak-positive diversifiers | 6 | (`gap_fill_v1`, `macro_credit_spread_v1`, others — small but non-negative) |
| Noise / sparse | 6 | 3 noise + 3 sparse (rarely fire, near-zero contribution) |
| Zero-fill registered active | 6 more | dead weight in the active list |
| **All 3 lifecycle pause decisions vindicated** | | atr_breakout (-5.78% in 2022), momentum_edge (-9.17% in 2022), low_vol_factor (-2.53% in 2025) |

**Bottom line: of 22 registered-active edges, ~6-7 carry the alpha.
The other 15-16 contribute nothing or actively drag.**

## Phase 2.10d — Pruning + capital allocation fix

This is the active next phase. Three tasks; first two parallel.

### A. Attribution-based pruning proposal (Agent B)

Document per-edge keep/cut decision with justification from the
per-year attribution. Target: ~6-7 active edges. Pure config proposal
on a branch — does NOT modify `data/governor/edges.yml` yet.

Output: `docs/Audit/pruning_proposal_2026_04.md`

### B. Capital allocation defect investigation (Agent A)

Validate the three defect surfaces with hard data; propose specific
code-change designs:
1. Per-edge participation floor in `signal_processor`
2. Audit/fix of soft-pause weight leak (1,613 fills for a "paused"
   edge needs explanation + mitigation)
3. Regime-aware slot reduction primitive — **likely Engine B (Risk)
   or Engine C (Portfolio); requires user approval before code
   change**

Output: `docs/Audit/capital_allocation_diagnosis_2026_04.md` with
proposals only, NOT code changes.

### C. Apply + re-test (sequential, after A+B + user approval)

Cut the 9-11 noise edges, implement structural fixes from B, re-run
2025 OOS under realistic costs. Compare to Q1 anchor's -0.049.

**Phase 2.10d gate:** post-fix 2025 OOS Sharpe must clear at least
SPY 2025 minus 0.3 (so > ~0.65) to confirm the structural diagnosis.
- Pass → Phase 2.11 (per-ticker meta-learner) and Phase 2.12
  (growth profile) unblock.
- Fail → the rivalry/dilution diagnosis was incomplete; deeper
  architectural rework needed.

## What's no longer true from the 04-29 plan

The 04-29 forward plan said:
- Phase 2.11 BLOCKED (per-ticker meta-learner) — **conditional on
  Phase 2.10d outcome.** Reasoning: the in-sample base was real
  production output; per-ticker training could lift it further; but
  there's no point until the rivalry/dilution waste is fixed first.
- Phase 2.12 BLOCKED (growth profile) — **same.** Switching profiles
  re-weights allocation, but allocation is broken right now. Fix
  allocation first.
- Phase 2.5 BLOCKED (Moonshot Sleeve) — **still blocked indefinitely.**
  Spinning up a parallel sleeve while the core sleeve doesn't express
  its alpha is premature. Re-evaluate after Phase 2.10d gate passes.

The 04-29 plan's recommendation to do "more edges, then meta-learner,
then moonshot" was **the wrong sequence given what we now know**. The
right sequence is **prune existing → fix capital allocation → re-test
→ then more edges**. Adding edges to a system that doesn't express its
existing alpha just adds more noise to the rivalry.

## Status of moonshot sleeve (goal C) given the new finding

Goal C (asymmetric upside / catch moonshots) is still a real
architectural gap, but the priority is even lower than yesterday's
"blocked." Reasoning: the core sleeve might genuinely produce real
risk-adjusted alpha *post-fix*. If post-2.10d 2025 OOS lands in the
0.65-0.95 Sharpe range with reasonable CAGR, the case for adding a
high-vol moonshot sleeve weakens — the user's goal A (compound) and
goal B (beat market) might both be addressable with the core. Goal C
becomes a Phase 4+ consideration after Phase 3 (deployment infra).

If post-fix the core still trails SPY by a wide margin, the moonshot
sleeve argument becomes stronger again as the asymmetric-upside lever
the core can't pull. Decision waits on data.

## Single-paragraph TL;DR

**Pruning + capital allocation fix, then re-test 2025 OOS.** The
system has real alpha (verified across 5 years of integration data
on 2 stable contributors + 4-5 weak-positive diversifiers); the
problem is structural waste — capital rivalry, soft-pause leak,
no regime-aware slot reduction. Phase 2.10d implements the diagnostic
proposals (parallel) then the structural fix (sequential, with user
approval for Engine B/C touches). Pass the gate and Phases 2.11/2.12
unblock. Don't pass and we have bigger problems than rivalry.
