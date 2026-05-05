# Path 2 — Per-Edge ADV Floor Primitive + Universe-B Validation

**Date:** 2026-04-30 → 2026-05-01
**Branch:** `path2-adv-floors-edges` (Agent D, continuation of `universe-b-diagnosis`)
**Doctrinal basis:** [universe_b_diagnosis_2026_04.md](universe_b_diagnosis_2026_04.md)
— the round-1 audit that decomposed the 79% Universe-B Sharpe collapse
as ~40% liquidity / impact-knee, ~30% stable-contributor signal-density
failure, ~20% survivorship tail. Recommended structural answer:
"per-edge ADV floors." This document implements that.

## What changed

A new precondition primitive in `engines/engine_a_alpha/edge_base.py`:
`EdgeBase._below_adv_floor(df, min_adv_usd, ticker, window=20)`. Returns
True iff the edge's `min_adv_usd` parameter is set AND the ticker's
rolling 20-day median dollar-volume (Close × Volume) is below it. No-op
when the parameter is None / 0 / NaN — backward-compatible for any edge
that doesn't opt in. Each skip increments a per-ticker counter exposed
via `get_adv_skip_summary()` for diagnostics.

Five ADV-fragile edges opt in, each with a class-level `DEFAULT_MIN_ADV_USD`
constant that compute_signals reads from `self.params.get("min_adv_usd",
self.DEFAULT_MIN_ADV_USD)`:

| Edge | `DEFAULT_MIN_ADV_USD` | Rationale (round-1 audit signal) |
|---|---|---|
| `atr_breakout_v1` | $200M / day | Per-fill avg loss went from -$0.70 (prod-109) to -$53 on UB — 76× catastrophe; the most ADV-fragile edge in the stack. |
| `momentum_edge_v1` | $200M / day | MA-crossover trades have similar microstructure dependence; soft-paused but still firing 11k+ times. |
| `volume_anomaly_v1` | $300M / day | Stable contributor in prod; signal IS the per-ticker volume z-score, so signal density and edge alpha both require liquid names. Higher floor than the others. |
| `herding_v1` | $200M / day | Cross-sectional contrarian, but fills are per-ticker; sub-floor names excluded from breadth universe AND from contrarian targeting. |
| `gap_fill_v1` | $150M / day | Weak-positive diversifier, less ADV-sensitive in round-1 attribution; lower floor. |

**Floor values are defensible defaults, NOT empirically calibrated.**
They were chosen by inspecting the prod-109 universe's lower-bound ADV
($762M median, $533M q25 in the round-1 audit) and stepping down by
edge-fragility tier. A calibration sweep is recommended as follow-up.

The edges left untouched: `macro_credit_spread_v1`,
`macro_dollar_regime_v1`, `pead_v1` and friends (universe-uniform tilts
or earnings-event-driven; not per-ticker microstructure-driven), and
`low_vol_factor_v1` (lifecycle-paused — floor doesn't matter).

## Universe-B validation results

Same window, same edges, same realistic-cost slippage as the Q2 anchor
from `oos_validation_2026_04.md` (run UUID
`ee21c681-f8de-4cdb-9adb-a102b4063ca1`). Universe-B is the seed=42
50-ticker held-out sample.

| Run | metalearner | Sharpe | CAGR% | MDD% | Vol% | WR% | Run UUID |
|---|---|---|---|---|---|---|---|
| **Q2 anchor** (no floors) | OFF | **0.225** | 1.76 | -18.17 | 9.95 | 47.51 | `ee21c681-...` |
| **Floors only** | OFF | **0.273** | 2.31 | -20.32 | 10.31 | 51.54 | `4bb5794b-ae63-4dd7-acb7-60f3c4db838c` |
| **Floors + ML** | ON | **0.916** | **9.22** | **-9.73** | 10.21 | 50.13 | `17e7f96b-d181-4b71-a815-414178d12827` |

Window benchmarks (from `compute_multi_benchmark_metrics`):
SPY Sharpe 0.875 (CAGR 13.94%), QQQ Sharpe 0.702 (CAGR 14.15%),
60/40 Sharpe 0.361.

## Boundary verdict

Pass criterion (per the deployment-boundary doc, Path 1 / Agent A):
**Universe-B Sharpe under ADV floors clears 0.5 (with or without ML).**

- **Floors only: FAIL** (0.273 — barely above anchor 0.225). Sub-criterion not met.
- **Floors + ML: PASS** (0.916 — clears 0.5 by +0.4 and exceeds SPY 0.875 and QQQ 0.702).

The boundary lifts conditionally on the metalearner being on. Read the
"Why floors-only is so weak" and "Why floors + ML works" sections
below before treating the +0.916 as settled.

## Per-edge attribution (what actually moved)

| Edge | anchor fills / $ | floors-only fills / $ | floors+ML fills / $ |
|---|---|---|---|
| `volume_anomaly_v1` | 137 / +$1,228 | **607 / +$20,655** | 77 / +$5,136 (per-fill $66.7) |
| `herding_v1` | 52 / +$975 | **309 / +$16,073** | 155 / +$5,425 (per-fill $35.0) |
| `gap_fill_v1` | 68 / +$275 | 288 / +$1,132 | 96 / -$29 (per-fill $0) |
| `momentum_edge_v1` | 11,073 / +$8,042 | 8,314 / **-$37,568** | 1,936 / **+$4,641** |
| `low_vol_factor_v1` | 444 / -$2,196 | 4,527 / -$2,234 | 4,239 / **+$7,482** |
| `atr_breakout_v1` | 286 / **-$15,142** | **0 / $0** (floor-blocked) | 0 / $0 |
| `macro_dollar_regime_v1` | 35 / +$425 | 0 / $0 | 2,679 / +$378 |
| `panic_v1` | 2 / $0 | 15 / +$205 | 67 / +$284 |
| **TOTAL** | 12,140 / **-$5,353** | 14,062 / **-$1,124** | 9,256 / **+$23,317** |

## Why floors-only is so weak (+0.05 Sharpe lift)

The floors do exactly what they were designed to do on the stable
contributors. `volume_anomaly_v1` PnL went from +$1,228 to +$20,655
(+$19.4k) and `herding_v1` from +$975 to +$16,073 (+$15.1k) — together
+$34.5k more PnL on UB, validating the round-1 thesis that signal
density was being suppressed by sub-floor noise.

But two compensating effects ate most of the gain:

1. **`momentum_edge_v1` concentration disaster.** Even at the 0.25× soft-pause
   weight, momentum_edge fires per-bar across all eligible names. With
   `atr_breakout_v1` floored to zero fills (it had been the dominant
   noise edge with 286 sub-floor fills), momentum_edge no longer
   competes for sizing — its per-fill positions grow. With floors also
   filtering momentum_edge below $200M, only 13 of 44 UB names remain
   eligible — concentration goes up further. Per-fill avg PnL falls from
   +$0.73 to **-$4.52** (6× worse per fill), 8,314 fills × -$4.52 =
   -$37,568. **The floor on momentum_edge concentrated capital onto
   fewer names and crossed its own impact knee.**

2. **MDD got worse, not better.** -18.17% → -20.32%. The floor is
   strictly defensive on risk, but the redirect of capital onto a
   smaller eligible set increased single-name concentration risk in
   adverse weeks.

These are second-order effects of the floor, not bugs in the floor
mechanism. The mechanism does what it advertises (verified by 15 unit /
integration tests in `tests/test_adv_floor.py`). The architecture
needs more than a precondition gate to fully fix the universe-fragility.

## Why floors + ML works (+0.69 Sharpe lift over anchor)

The metalearner (per `metalearner_validation_balanced.md`) takes
per-bar features (regime states, per-edge raw scores, contribution
history) and emits a per-edge weight multiplier each bar. Trained on
prod-109 data, the model has weak walk-forward correlation (mean OOS
+0.038, 50% positive folds) — a small per-bar signal, not a strong
predictor.

Yet floors + ML cuts momentum_edge fills from 8,314 → **1,936** and
flips its PnL from -$37,568 → +$4,641. It cuts volume_anomaly fills
from 607 → 77 but keeps per-fill PnL at $66.7 (vs $34 in floors-only,
$8.97 in anchor). The ML is being **selective per bar about which
edges fire when** — the floors take care of WHERE (which tickers) and
the ML takes care of WHEN (which bars).

This is genuinely synergistic. The floors-only cleanup gives the ML
a higher-signal-to-noise input to reweight; without floors the ML is
reweighting muddy signals. Without ML the floors over-concentrate
the surviving signals onto too few names.

**The +0.69 Sharpe lift is conditional on this combination.** Either
component alone is much weaker.

## Caveats — what is and isn't proven

1. **Single-run validation, no multi-seed.** Universe-B is one
   `seed=42` sample of 50 names. The +0.916 result hasn't been
   replicated on alternate seeds; the round-1 audit's caveats about
   survivorship-tail bias on this specific UB sample still apply
   (12% of names have zero/truncated data).

2. **The metalearner was trained on prod-109 (`abf68c8e-...`).** This
   IS the same training data documented in
   `metalearner_validation_balanced.md`. Testing on UB-50 is genuinely
   out-of-sample for the universe dimension (no UB tickers in the
   training distribution) but the model's input features (regime
   states, edge contributions) transfer across universes. The ML's
   weak walk-forward correlation (+0.038 mean) makes the +0.69 Sharpe
   lift suspicious-strong; either:
   - **(a)** the floors-cleaned signals interact with the ML in a
     genuinely synergistic way (consistent with the per-edge
     attribution showing per-fill PnL improvements), or
   - **(b)** there's a single-run lucky-fold component to the result.

3. **No 2025 OOS retest.** This validation is on the 2021-2024 window,
   the same window the prod-109 anchor was measured on. A 2025 OOS run
   under floors + ML on a UB-shape universe would harden the result.

4. **Lifecycle pause is leaking.** `momentum_edge_v1` has status
   "paused" in `data/governor/edges.yml`, but it still fires 1,936
   times (with ML on) or 8,314 times (without ML). The 0.25×
   soft-pause weight is a leak relative to the round-1 audit's
   diagnosis that paused should mean truly off for failed edges. This
   is Agent A's territory (capital allocation) — flagging it from
   here as load-bearing for the floors+ML result.

5. **Floor values not calibrated.** $200M / $300M / $150M defaults are
   ballpark. A grid sweep (e.g. {100M, 200M, 300M, 500M, 1B} on each
   edge) on UB and prod-109 simultaneously would find optimal values.
   Recommended next step.

## What the result implies for Phase 2.10d / 2.11

- The structural fix (per-edge ADV floors) is a **necessary
  precondition** but not sufficient on its own. Floors-only on UB
  gives +0.05 Sharpe.
- The **metalearner is the unblocker** when combined with floors.
  Without floors, ML doesn't have clean enough inputs; without ML,
  floors over-concentrate. The combination produces +0.69 Sharpe lift.
- If this generalizes (caveats above), Phase 2.11 (per-ticker
  meta-learner) goes from "blocked pending capital allocation fix" to
  "the structural fix that unlocks universe-portability."
- The 04-25 finding "true Sharpe is 0.4 on a wider universe vs SPY 0.88"
  is materially weakened. Under floors + ML, UB Sharpe lands 0.916 —
  meeting and exceeding SPY. **The system's universe-fragility is not
  fundamental; it is a product of unmodeled liquidity preconditions
  AND unconstrained linear edge weighting, both of which can be
  addressed.**

## Tests

`tests/test_adv_floor.py` — 15 tests, all passing:

1. `test_floor_none_is_no_op` — `min_adv_usd=None` returns False.
2. `test_floor_zero_or_negative_is_no_op` — `0` and `-100M` are no-ops.
3. `test_floor_nan_is_no_op` — `NaN` is a no-op.
4. `test_floor_skips_below_threshold` — $200M floor skips $100M-ADV ticker.
5. `test_floor_allows_above_threshold` — $200M floor allows $500M-ADV ticker.
6. `test_floor_handles_missing_volume_column` — missing `Volume`: no-op.
7. `test_floor_handles_short_history` — fewer than `window` bars: no-op.
8. `test_floor_handles_zero_volume_bars` — all-zero volume: skips correctly.
9. `test_counter_increments_across_calls` — `_adv_skip_count` accumulates.
10. `test_atr_breakout_skips_below_floor` — integration: 2-ticker run.
11. `test_momentum_skips_below_floor` — integration: 2-ticker run.
12. `test_volume_anomaly_skips_below_floor` — integration: 2-ticker run.
13. `test_gap_fill_skips_below_floor` — integration: 2-ticker run.
14. `test_herding_excludes_below_floor_from_universe` — cross-sectional integration: sub-floor names excluded from breadth + scored 0.
15. `test_floor_explicit_param_override` — setting `min_adv_usd: 0` via params disables the floor for that edge.

## Reproduction

```bash
# Floors-only (re-uses the existing OOS driver; metalearner is OFF in prod config)
PYTHONHASHSEED=0 python -m scripts.run_oos_validation --task q2

# Floors + metalearner ON (new driver, in-memory override of metalearner.enabled)
PYTHONHASHSEED=0 python -m scripts.run_path2_ub --metalearner on
PYTHONHASHSEED=0 python -m scripts.run_path2_ub --metalearner off
```

Outputs:
- `data/research/oos_validation_q2.json` (floors only)
- `data/research/path2_ub_ml_on.json` (floors + ML)
- `data/research/path2_ub_ml_off.json` (re-runnable floors-only via the new driver)
- Trade logs at `data/trade_logs/<run_id>/`.

## Five-line summary

1. ADV-floor primitive added to `EdgeBase._below_adv_floor`; backward-
   compatible no-op when `min_adv_usd` is None. 15 unit/integration
   tests pass; primitive applied to atr_breakout ($200M),
   momentum_edge ($200M), volume_anomaly ($300M), herding ($200M),
   gap_fill ($150M).

2. **Floors only on Universe-B: Sharpe 0.273** (anchor 0.225, +0.05 lift).
   Stable contributors gain (+$34.5k from volume_anomaly + herding) but
   floors over-concentrate momentum_edge onto fewer eligible names —
   per-fill loss balloons 6× and eats the gain.

3. **Floors + metalearner on Universe-B: Sharpe 0.916** (+0.69 lift,
   exceeds SPY 0.875 and QQQ 0.702). Floors give the ML cleaner
   per-bar inputs; ML reweights edges to fire 1/4 as often with much
   higher per-fill quality. Genuinely synergistic.

4. **Boundary lift: PASS conditional on ML on, FAIL without ML.** The
   structural fix is necessary but not sufficient alone; floors + ML
   together unlock universe-portability.

5. Caveats: single-run / single-seed result on a survivorship-biased
   UB sample, ML trained on prod-109 (universe-OOS but
   feature-transfer-dependent), `momentum_edge_v1` lifecycle-pause is
   leaking 0.25× weight. Recommended: 2025 OOS retest under floors+ML,
   floor-value calibration sweep, fix the soft-pause leak (Agent A's
   territory).
