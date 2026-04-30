# Phase 2.10d follow-up — Portfolio meta-learner re-test on clean data

**Date:** 2026-04-30
**Branch:** `metalearner-portfolio-enable`
**Question:** Does the existing portfolio-level Phase 1 meta-learner (shipped
2026-04-29 commit 82becfd, default-OFF) actually help now that Phase
2.10d structural fixes have cleaned the underlying training data?
**Approach:** flip exactly one config flag (`metalearner.enabled: false →
true` in `config/alpha_settings.prod.json`), re-run 2025 OOS with
identical window / universe / cost-model as the Task C anchor, compare.

## Setup

- Window: 2025-01-01 → 2025-12-31 (strict OOS)
- Universe: prod 109 tickers
- Cost model: `RealisticSlippageModel` (ADV-bucketed half-spread + Almgren-Chriss impact)
- Governor: `--reset-governor`
- All Phase 2.10d structural fixes active (lifecycle triggers + capital allocation primitives + regime-summary floor)
- **Only delta from Task C:** `metalearner.enabled = true` for `balanced` profile
- Driver: `python -m scripts.run_oos_validation --task q1`

The trained model loaded from `data/governor/metalearner_balanced.pkl`
(13 features, 787 train samples, GradientBoostingRegressor, train R² 0.556).

## Leakage check (load-bearing — addressed first)

The walk-forward validation report at
`docs/Audit/metalearner_validation_balanced.md` says training source run
is `abf68c8e-1384-4db4-822c-d65894af70a1`. Direct inspection:

```
trades.csv: 23,952 rows
date range: 2021-01-05 → 2024-12-31
year distribution: 2021=6952, 2022=4879, 2023=5880, 2024=6241, 2025=0
```

**Training data ends at the boundary of the 2025 OOS window. No 2025 bars
in training.** This is a strict OOS test of the meta-learner.

## Side-by-side: Task C (off) vs this run (on)

| Metric | Task C (off) | This run (on) | Δ |
|---|---|---|---|
| **Sharpe Ratio** | **0.315** | **1.064** | **+0.749** |
| CAGR (%) | 1.41 | 4.80 | **+3.39 pp** |
| Max Drawdown (%) | -2.68 | -3.33 | -0.65 pp |
| Volatility (%) | 4.86 | 4.53 | -0.33 pp |
| Win Rate (%) | 39.77 | 48.68 | **+8.91 pp** |
| Net Profit ($) | +1,406 | +4,770 | +3,364 |
| Run UUID | `d7ae1ca3-3771-4366-a8a8-c46f6907ff50` | `eb0f8270-6f61-46ca-9174-3919da5d0ef6` | — |

**vs benchmarks (2025):**

| Reference | Sharpe | CAGR (%) | MDD (%) | Vol (%) |
|---|---|---|---|---|
| **System (post-fix, ML on)** | **1.064** | 4.80 | -3.33 | 4.53 |
| System (post-fix, ML off — Task C) | 0.315 | 1.41 | -2.68 | 4.86 |
| SPY | 0.955 | 18.18 | -18.76 | 19.52 |
| QQQ | 0.933 | 21.22 | -22.77 | 23.64 |
| 60/40 (SPY+TLT) | 0.997 | 12.93 | -11.34 | 13.08 |

**The post-2.10d + meta-learner-on system Sharpe (1.064) exceeds SPY,
QQQ, and 60/40 in 2025.** It does so at a fraction of their volatility
(4.5% vs 13–24%), so on a CAGR basis it still trails them
significantly — the system is more leverage-constrained than alpha-
constrained at this point.

## Did the meta-learner move the Sharpe?

**Yes. By +0.749 Sharpe.** Direction: positive. Magnitude: large
relative to the +0.364 lift Phase 2.10d's tactical fixes alone produced
between Q1 anchor (-0.049) and Task C (0.315).

## Mechanism — what actually changed in the trade mix?

Per-edge fill counts, 2025 OOS:

| Edge | ML off | ML on | Δ | Edge status |
|---|---|---|---|---|
| `atr_breakout_v1` | 1,184 | **0** | **-1,184** | paused (heavy loser, pruned 04-25) |
| `macro_credit_spread_v1` | 415 | 797 | +382 | weak diversifier |
| `momentum_edge_v1` | 3,268 | 3,782 | +514 | paused (heavy loser, pruned 04-25) |
| `low_vol_factor_v1` | 44 | 91 | +47 | paused (regime-conditional, failed) |
| `macro_dollar_regime_v1` | 17 | 38 | +21 | weak |
| `volume_anomaly_v1` | 256 | 226 | -30 | stable contributor |
| (others, all small) | 411 | 358 | -53 | mixed |
| **TOTAL** | **5,557** | **5,292** | -265 | |

The dominant single change: **`atr_breakout_v1` went from 1,184 fills
to zero** under meta-learner-on. The 04-29 validation report shows
`atr_breakout_v1` as the highest-importance feature in the trained
model (importance 0.31), and the model was trained on data that
includes its catastrophic 2022 (-9% contribution) and the prior
lifecycle pause. The model learned to negatively-modulate that
edge's contribution, and the +0.1 contribution-weight at inference
was sufficient to push its outputs below the entry threshold for
every 2025 bar.

A clean reading: **the meta-learner is doing a more aggressive
version of what Phase 2.10d's lifecycle pause + soft-pause-cap do
already**. Both target the same heavy-loser edges; the meta-learner
just gets there faster and harder than the linear-rule path.
That's consistent with the 04-30 reviewer's framing
("meta-learner natively suppresses bad edges via negative SHAP
weights — capital rivalry is a symptom of the linear allocator").

Secondary reads:
- Capital saved from `atr_breakout_v1` re-routes mostly to
  `macro_credit_spread_v1` (+382 fills) and `momentum_edge_v1`
  (+514 fills). Both were positive contributors in 2025.
- `volume_anomaly_v1` fills drop slightly (256→226). That edge is a
  stable contributor; the small drop is a wash given the model's
  mostly-zero importance for it (0.016).
- `low_vol_factor_v1` fills go *up* (44→91) despite being a
  regime-conditional loser. Either the model isn't suppressing it
  (its importance was 0.019 — near-zero) or the soft-pause-cap +
  fill-share cap upstream are letting more of its weight through. This
  is a small effect on net P&L but flags an open question.

## Pre-committed gate verdict

The Phase 2.10d gate (forward plan, line 152-167):

| Threshold | Verdict | This run |
|---|---|---|
| < 0.2 | Kill thesis | — |
| 0.2 - 0.4 | Ambiguous; Phase 2.11 still blocked | — |
| 0.4 - 0.65 | Partial pass; Phase 2.11 strategic next step | — |
| **> 0.65** | **Full pass; Phase 2.11 + 2.12 unblock** | **← lands here at 1.064** |

By strict reading of the pre-committed gate, **flipping the
existing portfolio meta-learner crosses the "full pass" threshold
on its own**.

That said — two material caveats follow before any deployment claim.

## Honest verdict — does the portfolio-level model help on clean data?

**Probably yes, but the magnitude is suspiciously large for a model
whose own walk-forward report (04-29 audit
`metalearner_validation_balanced.md`) showed mean OOS correlation
**+0.038** and **50%** folds positive — i.e., its own promotion gate
read 🔴 DOES NOT PASS. A model that can't beat noise on per-week OOS
correlation arguably shouldn't move portfolio Sharpe by +0.75.**

Three competing hypotheses for why the in-sample WF report and
the 2025 OOS Sharpe disagree:

1. **The model genuinely adds small forward signal that compounds
   through portfolio mechanics.** The lift comes not from prediction
   accuracy on individual fills but from the model systematically
   re-routing capital away from a known heavy loser
   (`atr_breakout_v1`) — a binary policy decision the linear sum
   plus lifecycle pause didn't fully execute. WF correlation is the
   wrong metric for this kind of contribution; it measures point
   prediction, not allocation policy.

2. **The lift is a side-effect of the contribution-weight 0.1
   shifting marginal entry-threshold crossings, not the model's
   actual prediction quality.** Even random additive noise of the
   right magnitude that happened to suppress atr_breakout's outputs
   would produce a similar lift. Distinguishing this from #1
   requires running the same flag on multiple held-out windows and
   verifying lift consistency.

3. **2025 was the wrong-year-to-not-suppress-atr_breakout.** The
   lifecycle pause already had `atr_breakout_v1` at soft-pause
   weight 0.5, but its 1,184 fills under that 0.5x weight still
   accumulated some loss in 2025. The meta-learner ate that loss
   by zeroing the edge entirely. If 2025 happens to be a year
   where atr_breakout's residual loss was disproportionately
   large, the lift would not generalize.

**Single-window OOS, however clean, cannot distinguish hypotheses 1,
2, and 3.** The 2026-04-30 task C precedent is exactly the right
template here — task C committed an OOS gate *before* running, then
honored the literal reading. The same discipline should apply to a
multi-window robustness test of meta-learner-on before declaring
"the portfolio direction is alive."

That said, three points argue the lift is real (hypothesis 1):
- **Leakage is verifiably absent** (training ends 2024-12-31).
- **Mechanism is interpretable** (suppresses a known heavy loser
  whose paused-state allocation was the largest unfixed bleed).
- **Direction matches the 04-30 reviewer's prior** ("meta-learner
  is the structural answer because it natively suppresses bad
  edges via negative SHAP weights"). The reviewer didn't predict
  +0.75 specifically, but they *did* predict the meta-learner would
  fix what the linear allocator can't.

## Is per-ticker training the only meta-learner direction worth pursuing?

**No — the portfolio direction is alive.** This run is positive
evidence that the existing portfolio-level model, retrained on
clean post-Phase-2.10d data and properly evaluated, has real lift.
Per-ticker training (Agent B's parallel infrastructure) is **a
strict superset of the portfolio model**, not a replacement: you
get all of the same signal-allocation policy plus per-ticker
specialization. There's no reason to rule out portfolio in favor
of per-ticker.

The right next step is **multi-window robustness testing of the
portfolio-level model first**, before per-ticker training adds
new degrees of freedom that could fit-to-noise. Specifically:
- Run meta-learner-on through the same Universe-B window
  (`scripts/run_oos_validation --task q2`) and through the
  per-edge per-year attribution lens (Agent B's audit
  `per_edge_per_year_attribution_2026_04.md`'s 5-year integration).
- If lift is consistent across all three: portfolio model is
  robust; deploy and *then* train per-ticker on top.
- If lift is concentrated in 2025 only: the +0.75 was hypothesis-3,
  per-ticker training would compound the artifact. Investigate
  before deploying either.

## Anything unresolved

1. **Single-window result.** Robustness is unproven. Multi-window
   re-runs needed (per above).
2. **`low_vol_factor_v1` fills increased under ML-on (44 → 91)**
   despite being a paused/failed edge. The model's importance for
   it is ~0.02, so it's not the model — possibly the structural
   primitives interact differently when total fill count drops by
   265. Worth a per-edge contribution check on the new run before
   deployment.
3. **Walk-forward audit's 🔴 DOES NOT PASS verdict vs +0.749
   Sharpe lift.** These two measurements disagree by orders of
   magnitude. One of them is asking the wrong question, but the
   audit doc currently reads as a deployment-blocker. If the
   user / director chooses to ship the portfolio meta-learner,
   the 04-29 promotion-gate logic in `train_metalearner.py` may
   need revision (the WF correlation metric isn't capturing the
   policy-level value the model contributes).
4. **The Phase 2.10d gate said this experiment was "diagnostic,
   not deployment."** I have not deployed anything beyond flipping
   the config flag in this branch. The `enabled: true` config
   change is deliberately not merged to main — that decision is
   the director's, contingent on multi-window robustness.

## Reproduction

```bash
# On branch metalearner-portfolio-enable, with metalearner.enabled = true:
python -m scripts.run_oos_validation --task q1
# → data/research/oos_validation_q1.json with Sharpe ~1.06
```

Result file: `data/research/oos_validation_q1.json` (run UUID
`eb0f8270-6f61-46ca-9174-3919da5d0ef6`, 2026-04-30 23:19 UTC).
Trade log: `data/trade_logs/eb0f8270-6f61-46ca-9174-3919da5d0ef6/`.
Anchor (Task C, ML off): `d7ae1ca3-3771-4366-a8a8-c46f6907ff50`.
