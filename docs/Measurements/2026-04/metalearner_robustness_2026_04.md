# Phase 2.11 robustness gate — Portfolio meta-learner across windows + universes

**Date:** 2026-04-30
**Branch:** `metalearner-robustness`
**Worktree:** `/Users/jacksonmurphy/Dev/trading_machine-agentC`
**Question:** Does the Round-1 +0.749 Sharpe lift (`metalearner_portfolio_enable_2026_04.md`) survive when the universe shifts (C1) and when held-out years stress different regimes (C2)? And is the low_vol_factor_v1 fill increase a structural-primitive interaction or a model artifact (C3)?

## Summary

| Check | Pass criterion | Result | Verdict |
|---|---|---|---|
| **C1** Universe-B Sharpe | > 0.4 | **0.273** | **FAIL** |
| **C2** Walk-forward mean Sharpe | ≥ 0.5 AND ≥ 2/3 folds positive | **+0.873**, 2/3 positive | **PASS** |
| **C3** low_vol_factor_v1 increase under cap=0.20 | structural vs. model artifact | **fills 91 → 0** under tighter cap | **structural dominance** |

**Combined deployment verdict: FAIL.** C1 alone is sufficient; the
+0.749 Sharpe lift is concentrated on prod-109. The model does NOT
generalize across universes.

The +0.749 was **not artifact** of a single year (C2 confirms
window-robustness — 2/3 folds positive, mean +0.873). It IS
artifact of universe choice (C1 — 79% Sharpe collapse persists
when universe shifts to held-out 50 tickers).

## C1 — Universe-B Sharpe under ML-on

### Setup
- Window: 2021-01-01 → 2024-12-31 (in-sample integration window)
- Universe: 50 held-out tickers (seed=42, excluded from prod-109)
- `metalearner.enabled: true`, all Phase 2.10d primitives active
- Driver: `python -m scripts.run_oos_validation --task q2`
- Run UUID: `4bb5794b-ae63-4dd7-acb7-60f3c4db838c`

### Result

| Metric | Q2 anchor (ML off, pre-2.10d) | C1 (ML on, post-2.10d) | Δ |
|---|---|---|---|
| Sharpe | 0.225 | **0.273** | +0.048 |
| CAGR (%) | n/a | 2.31 | — |
| MDD (%) | n/a | -20.32 | — |
| Vol (%) | n/a | 10.31 | — |
| Win Rate (%) | n/a | 51.54 | — |
| Net Profit ($) | n/a | +9,530 | — |

The +0.048 Sharpe delta vs the pre-2.10d Q2 anchor (0.225) is
small. **Roughly speaking the meta-learner does almost nothing on
Universe-B — most of the prod-109 +0.749 lift evaporates.**

A clean comparison would require running Q2 ML-off post-2.10d. If
post-2.10d structural fixes alone lifted Q2 by, say, +0.2 Sharpe (a
plausible estimate given +0.36 lift on Q1), then the meta-learner is
**negative** on Universe-B (~0.425 expected baseline → 0.273 ML-on).
The exact baseline isn't measured, but every plausible value implies
weak-to-negative ML contribution.

### What this means

The meta-learner's 13 features are edge-IDs, several of which (esp.
`atr_breakout_v1`, `momentum_edge_v1`) operate primarily on the prod-
109 mega/mid-cap names. The model learned to suppress
`atr_breakout_v1` based on its prod-109 2022 disaster. Universe-B
contains 50 different tickers — those same edges fire differently,
and the suppression patterns the model encodes don't transfer.

**This was the 04-30 Universe-B test: prod-109 Sharpe 1.063
→ Universe-B Sharpe 0.225 (79% collapse, ML-off).** The +0.749
Round-1 lift was measured on prod-109 only. C1 demonstrates the lift
is prod-109-specific.

### C1 verdict

**FAIL** (0.273 < 0.4 threshold).

## C2 — Three-fold hold-one-year-out walk-forward

### Setup

For each `test_year ∈ {2022, 2023, 2024}`:
1. Filter the 04-29 source training run (`abf68c8e-…`, 2021-01-05 → 2024-12-31, 23,952 trades) to exclude `test_year` rows.
2. Re-train the meta-learner via `scripts/train_metalearner.py --run-id <fold-id>` on the 3-year subset.
3. Run a single-year backtest of `test_year` with `metalearner.enabled=true` against prod-109.
4. Capture Sharpe + supporting metrics.

Driver: `scripts/run_c2_walkforward.py` (new in this branch).
Output: `data/research/c2_walkforward_results.json`.

### Result

| Test year | Excluded from training | Sharpe | CAGR (%) | MDD (%) | Vol (%) | WR (%) | Net Profit | Test run UUID |
|---|---|---|---|---|---|---|---|---|
| **2022** | yes | **-0.453** | -4.01 | -8.32 | 8.25 | 40.39 | -$3,963 | `ccedaf36-e0e9-4bec-8d6a-e3448aabdca2` |
| **2023** | yes | **+0.894** | 4.25 | -3.51 | 4.78 | 53.60 | +$4,192 | `1a911cc0-4ec3-4e4b-98fd-7748076207be` |
| **2024** | yes | **+2.177** | 10.0 | -2.33 | 4.42 | 50.49 | +$9,963 | `8941c7c7-b13a-4086-b92f-d85e2d5ff6d5` |

**Mean Sharpe: +0.873**
**Folds with positive Sharpe: 2/3**

### What's underneath the numbers

Per-fold edge fill mix (top edges only):

| Edge | 2022 | 2023 | 2024 |
|---|---|---|---|
| `momentum_edge_v1` | 5,029 | 5,121 | 5,286 |
| `volume_anomaly_v1` | 269 | 193 | 261 |
| `gap_fill_v1` | 165 | 93 | 169 |
| `herding_v1` | 169 | 136 | 56 |
| `atr_breakout_v1` | **0** | **0** | **0** |
| `low_vol_factor_v1` | **0** | **0** | **0** |

The model's behavior is highly consistent across folds:
**`atr_breakout_v1` is zeroed in ALL three folds**, regardless of
which year was held out from training. `low_vol_factor_v1` likewise
zeroed in all folds. **The model executes a hard policy
("kill atr_breakout, lean heavily on momentum_edge_v1, allow tiny
allocations to volume_anomaly + gap_fill + herding")** that's
relatively independent of which year it trained on.

That hard policy works in trending years (2023 +0.894, 2024 +2.177)
and fails in 2022 chop (-0.453). Heavy momentum allocation in a
sideways/down year is exactly the wrong pivot. The model has no
mechanism to detect "this is a 2022-style year, dial back momentum"
because its features are per-bar edge raw scores — no regime input,
no second-order time-series signal.

### C2 verdict

**PASS** (mean +0.873 ≥ 0.5, 2/3 positive).

But the pass is structurally weak: the +0.873 mean is dominated by
2024's +2.177 outlier. If 2024's regime had been more like 2022's,
this would flip to a fail. **Window-robustness is "ok on average,
fragile in adverse regimes."** Note also that the 2022 backtest's
-4.01% CAGR is materially worse than the 2022 SPY CAGR (-19% in raw
SPY price — the system at least doesn't lose as much as the index
did, but it loses real money in raw terms).

## C3 — Low_vol_factor_v1 fill increase under tighter cap

### Background

Round-1 audit (`metalearner_portfolio_enable_2026_04.md`) flagged:
`low_vol_factor_v1` fills *increased* under ML-on (44 → 91) at
default cap=0.25, despite being a paused/failed edge. The question:
is this the model preferring the edge, or a structural-primitive
interaction (cap=0.25 letting more secondary edges through when
total fill count drops)?

### Setup

Same as Round-1 (2025 OOS, prod-109, realistic costs) but
`fill_share_cap = 0.20` (Agent A's recommended value from
`pruning-proposal`).

Run UUID: `3e644846-fa8d-4333-b63a-4dbd62de0eab`.

### Result

| Variant | Sharpe | low_vol_factor_v1 fills | Total fills |
|---|---|---|---|
| Round-1 anchor (cap=0.25, **ML off**) | +0.315 | 44 | 5,557 |
| Round-1 (cap=0.25, **ML on**) | +1.064 | 91 | 5,292 |
| **C3** (cap=0.20, **ML on**) | **+1.115** | **0** | 5,392 |

Per-edge fills for cap=0.25 ML-on → cap=0.20 ML-on:

| Edge | cap=0.25 | cap=0.20 | Δ |
|---|---|---|---|
| `momentum_edge_v1` | 3,782 | 4,891 | +1,109 |
| `macro_credit_spread_v1` | 797 | 0 | -797 |
| `volume_anomaly_v1` | 226 | 241 | +15 |
| `gap_fill_v1` | 124 | 143 | +19 |
| `growth_sales_v1` | 99 | 10 | -89 |
| `low_vol_factor_v1` | **91** | **0** | **-91** |
| `herding_v1` | 70 | 88 | +18 |
| `value_trap_v1` | 40 | 1 | -39 |
| `macro_dollar_regime_v1` | 38 | 0 | -38 |

### What this shows

Under cap=0.20, **most secondary edges go to zero** (or near-zero):
`macro_credit_spread`, `low_vol_factor`, `macro_dollar_regime`,
`value_trap`, etc. all squeezed out. `momentum_edge_v1` absorbs
+1,109 fills.

The fill_share_cap primitive limits how much of any single bar's
fill volume one edge can take. At cap=0.20 (vs 0.25), this becomes a
much harder constraint, and `momentum_edge_v1` — which is by far
the highest-frequency firing signal — claims the bulk of the room
that the secondary edges were getting.

**Mechanism interpretation.** The Round-1 44 → 91 increase was at
least partly the model preferring `low_vol_factor_v1` outputs over
the linear sum's allocation (model importance for that edge is
~0.02, low but non-zero). At cap=0.25 there's enough room for that
preference to manifest. At cap=0.20 the structural cap dominates and
the model's preference is moot.

So the answer to "structural-primitive interaction or model
artifact": **both, but the cap dominates**. Under cap=0.20 there's
no model preference left to express — momentum eats the room. Under
cap=0.25, the model gets ~+47 extra fills for `low_vol_factor` which
adds modest negative drag.

Sharpe also moved (1.064 → 1.115, +0.05). Within noise, but
directionally consistent with "tighter cap removes a paused/failed
edge's drag." This is independent evidence that capital allocation
under cap=0.25 still has some leakage.

### C3 verdict

**Structural-primitive dominance.** The low_vol fill increase is
not a stable model behavior — it's parametrically dependent on the
cap value. Under tighter caps (Agent A's recommended 0.20), the
issue disappears entirely.

This is the kind of cleanup that should be part of any deployment
decision. Not a blocker by itself but worth resolving before
declaring the model "deployable on prod-109."

## Combined deployment verdict

**FAIL — meta-learner is not deployment-ready.**

The +0.749 Sharpe lift in Round-1 was a real signal in one
dimension (window robustness, C2 PASSES) but a fragile signal in
another (universe robustness, C1 FAILS). Pre-committed gates were
explicit: **all three must pass for deployment**. C1 alone is
sufficient to block.

Round-1's headline lift was, in retrospect, partially a measure of
"how prod-109-specific is the system". The model's hard policy
(zero atr_breakout, lean on momentum_edge_v1) is robust across years
on prod-109 but doesn't survive the universe shift.

### Two paths forward

1. **Accept prod-109 specialization, deploy with explicit boundary.**
   The model only ever runs against prod-109. Universe expansions
   would re-trigger the validation gauntlet. This is a reasonable
   short-term operational stance — Phase 2.10b documented that
   prod-109 is the "favorable universe" the system was built around,
   and most strategies that "work" really only work on a specific
   universe. Not deployable to true OOS without re-validation.

2. **Retrain on a wider universe (or with universe-aware features)
   before deployment.** The model's 13 features are edge-IDs, which
   doesn't carry universe-shift information. Per-ticker training
   (Agent B's parallel infrastructure) is one path; including
   ticker-cluster features in the portfolio model is another.
   Either takes weeks of work.

The user-director should pick path. **The robustness gauntlet
correctly caught what would otherwise have been a Phase 2.10b-style
deployment trap.** Without C1, we would have shipped a model that
adds noise on any universe expansion.

## What the data unambiguously shows

- **Window robustness is real but conditional.** Under prod-109,
  the model's policy ("kill atr_breakout, default momentum") works
  2/3 of the time (2023, 2024 trending) and fails in chop (2022).
  Mean +0.873 across 3 folds.
- **Universe robustness is bad.** Sharpe 1.064 (prod-109) →
  0.273 (Universe-B). Most of the lift evaporates.
- **The mechanism is a hard policy, not adaptive prediction.** All
  three folds zero `atr_breakout_v1` and `low_vol_factor_v1` and
  pile capital on `momentum_edge_v1`. The 04-29 walk-forward report's
  "DOES NOT PASS" verdict (mean OOS corr +0.038) is consistent with
  this — point-prediction is weak, but the binary policy decision
  ("disable atr_breakout") is robust.
- **Capital allocation primitives matter a lot.** C3's cap=0.25 →
  cap=0.20 shift moves Sharpe by +0.05 and zeroes ~5 secondary
  edges. The model lives downstream of the cap; if Agent A picks
  cap=0.20 for prod, the model's effective contribution shrinks
  further (one fewer allocation lever to pull).

## Anything unresolved

1. **Q2 with ML-off, post-2.10d** wasn't measured — would clarify
   whether the meta-learner adds anything at all on Universe-B
   relative to the post-2.10d structural fixes alone, or whether
   it's a wash / negative.
2. **Per-ticker training (Agent B's parallel work)** is the obvious
   next experiment — universe-shift fragility is exactly what
   per-ticker features should help with. Not in scope here, but the
   case for that direction is now stronger.
3. **Round-1's +0.749 is now properly contextualized.** It was a
   real number on its OWN universe. It is not a deployment-ready
   number for the system overall.
4. **The 2024 fold's +2.177 Sharpe is high enough to deserve a
   side-eye.** The training set for that fold was 2021+2022+2023.
   The model trained on those years and tested in 2024 a regime
   continuous with 2023 (both moderate-trending bull). A more
   adversarial fold (say, "train on 2021+2023, test on the
   2022-bear + 2024-bull straddle") would stress-test more.
   Out of scope for this gate.

## Reproduction

```bash
# C1
python -m scripts.run_oos_validation --task q2

# C2
python -m scripts.run_c2_walkforward

# C3
# (requires temporary fill_share_cap=0.20 in alpha_settings.prod.json)
python -m scripts.run_oos_validation --task q1
```

Result files (this branch):
- C1: `data/research/oos_validation_q2.json`
- C2: `data/research/c2_walkforward_results.json`
- C3: `data/research/oos_validation_q1.json` (latest run; overwrites Round-1's)

Source training run (full 2021-2024): `abf68c8e-1384-4db4-822c-d65894af70a1`.
Round-1 anchor (ML off): `d7ae1ca3-3771-4366-a8a8-c46f6907ff50`.
Round-1 result (ML on, cap=0.25): `eb0f8270-6f61-46ca-9174-3919da5d0ef6`.
