# HRP Slice 3 — Normalization Fix (Redistribution, Not Reduction)

**Branch:** `hrp-slice-3-normalization`
**Date:** 2026-05-02
**Predecessor:** Slice 2, merged 2026-05-02 in `path-a-tax-efficient-core`
**Driving finding:** `project_wash_sale_exposes_turnover_bug_2026_05_02.md` —
> "Cell C underperforms because HRP_weight × N composition is strict size-reducer; slice 3 needs mean = 1.0 normalization."

---

## What was wrong with slice 2

Slice 2's composition layer in `signal_processor._apply_portfolio_optimizer`
emitted the per-ticker optimizer multiplier as:

```python
magnitude = float(w) * scale                    # HRP_weight × N
magnitude = max(0.0, min(1.0, magnitude))       # clamp to [0, 1]
out[t]["optimizer_weight"] = magnitude          # composed path
```

`committed` is the post-turnover-gate HRP weight vector summing to 1.0.
With N firing tickers, `committed × N` has mean **exactly 1.0** by
construction (Σwᵢ = 1, scaled by N). The intent of slice 2 was a
multiplier centered at 1.0 that *redistributes* size — above-mean
tickers scaled up, below-mean tickers scaled down, ensemble exposure
preserved.

The upper clamp at 1.0 broke that invariant in one direction:
- **Above-mean ticker** (w × N > 1.0): clamped DOWN to exactly 1.0.
  No amplification.
- **Below-mean ticker** (w × N < 1.0): unaffected. Scaled down.

Net: every position size ≤ baseline, none above. The "composition" was
a strict reducer, not a redistributor. Cell C's pre-tax Sharpe (0.557)
was *below* Cell B (1.624) precisely because the wash-sale gate had
already cut entry rate, then HRP composition cut sizing on what
remained.

## The fix (slice 3)

**Option chosen: 1 — remove the upper clamp on the composed path.**

```python
# Slice 3
out[t]["optimizer_weight"] = max(0.0, raw_magnitude)
```

The slice-1 *replacement* path (`method == "hrp"`) keeps the original
`[0, 1]` clamp. There the magnitude becomes `aggregate_score`, which is
conventionally bounded in `[-1, 1]`, so the original clamp is correct
on that path. Only the composed path is changed.

### Why option 1 over the alternatives

The user spec offered three normalization shapes:

1. **Remove upper clamp** — `clamp(HRP_weight × N, 0, ∞)`. Above-mean
   amplified; below-mean reduced. Most faithful to HRP's intent;
   relies on Engine B's `max_gross_exposure` cap to clip pathological
   amplification.
2. **Symmetric clamp around 1.0** — `clamp(HRP_weight × N, 0.5, 2.0)`.
   Bounds amplification but discards the long-tail shape HRP produces
   when one ticker has materially lower variance.
3. **Multiplicative around mean** — divide by `mean(HRP_weight × N)`
   inside the firing set. Mathematically a no-op when committed sums
   to 1.0 (mean is already 1.0); this option only matters if the
   turnover gate returns a non-unit-sum vector.

Option 1 is correct because:
- The mean = 1.0 invariant already holds analytically (committed is a
  probability vector × N). No further normalization is needed.
- HRP's sizing intent — "size proportional to inverse-variance share"
  — collapses if you cap the amplifier. The whole point is that when
  one cluster has materially lower variance, HRP wants you over-sized
  there relative to equal-weight.
- Engine B's `max_gross_exposure` cap (`config/risk_settings.json`,
  default 1.0) and the per-ticker `max_position` check are the
  right place to discipline extreme amplification — not the
  optimizer's output. Doing it at the optimizer would conflate two
  concerns (HRP's relative-sizing signal vs portfolio-level exposure
  budget).
- Engine B already has the gross-exposure check at
  `risk_engine.py:813-814` and `:912-914` — pathological amplification
  hits these bounds and gets clipped.

Option 2 was rejected because the symmetric `[0.5, 2.0]` band would
silently cap a regime where HRP correctly identified one
low-variance diversifier (e.g. the post-2022 SPY-like names in our
prod-109 universe). The audit's diagnostic test
`test_hrp_slice3_no_upper_clamp_degeneracy` constructs this exact
scenario and shows the multiplier exceeds 1.05 — option 2 would
silence it.

Option 3 was rejected because committed's sum equals 1.0 by HRP
construction, so `mean(committed × N) = 1.0` already. The only edge
case is when the turnover gate returns a stale vector that no longer
matches the active set (i.e. some active tickers have w=0 because
they weren't in the prior committed set). In that case option 3 would
over-correct by ignoring the missing mass; option 1 leaves the
zero-weighted tickers at the intended 0× sizing, which is the right
behavior. (If the firing set changes, those tickers should re-enter
on the next rebalance via `turnover.evaluate`.)

## Test coverage

`tests/test_path_a_tax_efficient_core.py::TestHRPCompositionVsReplacement`:

- `test_hrp_composed_preserves_aggregate_score` — updated invariant
  from `0 ≤ ow ≤ 1` to `ow ≥ 0`. Confirms aggregate_score is still
  preserved exactly (composition, not replacement).
- `test_hrp_slice3_redistribution_not_reduction` — NEW. On 8-ticker
  2-cluster synthetic data, asserts mean(optimizer_weight) ≈ 1.0,
  max > 1.0, min < 1.0. Slice 2 would FAIL this test (max ≤ 1.0).
- `test_hrp_slice3_no_upper_clamp_degeneracy` — NEW. Constructs a
  4-ticker covariance with one ticker at 10× lower variance and
  asserts that ticker receives optimizer_weight > 1.05. Slice 2
  would clamp it to exactly 1.0.

All 45 path-A + engine-c-hrp tests pass under `PYTHONHASHSEED=0`.

---

## A/B/C/D harness verification

Harness: `scripts/ab_path_a_tax_efficient_core.py`. 3 replicates per
cell, run inside `scripts.run_isolated.isolated()`. Same prod-109
universe / 2025-01-01 → 2025-12-31 OOS / `PYTHONHASHSEED=0`.

**Cells (unchanged from slice 2):**

| Cell | `portfolio_optimizer.method` | `wash_sale.enabled` | `lt_hold.enabled` |
|---|---|---|---|
| A | weighted_sum | false | false |
| B | weighted_sum | true | true |
| C | hrp_composed | true | true |
| D | hrp (slice-1 replacement) | false | false |

### Pass criterion

**Slice 3 passes if Cell C ≥ Cell B (1.624 pre-tax).** That tests
whether HRP redistribution adds value on top of wash-sale alone, or
whether HRP composition is fundamentally not additive in this
3-active-edge / prod-109 ensemble.

Stretch: Cell C ≥ 1.7 — HRP redistribution genuinely additive.

### Results — 12-backtest run

Raw JSON: `docs/Audit/hrp_slice_3_ab_results.json`. PYTHONHASHSEED=0,
prod-109 universe, 2025-01-01 → 2025-12-31 OOS,
`scripts/run_isolated.isolated()` snapshot+restore around each run.

| Cell | Mean Sharpe pre-tax | Mean Sharpe post-tax | Tax drag $ | Wash blocks | LT defers | Canon unique/3 |
|---|---:|---:|---:|---:|---:|---:|
| A baseline | **0.9533** | -0.5865 | $12,617 | 0 | 0 | 2/3 |
| B tax-only | **1.6240** | -0.4139 | $12,212 | 6,335 | 0 | 1/3 |
| C full Path A (slice 3) | **0.7400** | -0.6009 | $11,636 | 6,024 | 0 | 1/3 |
| D HRP slice-1 | **0.3310** | -0.7447 | $9,941 | 0 | 0 | 1/3 |

**Δ vs cell A baseline:**

| Cell | Δ pre-tax | Δ post-tax | Slice 2 Δ pre-tax (for comparison) |
|---|---:|---:|---:|
| B tax-only | **+0.670** | **+0.173** | +0.670 |
| C slice 3 | **-0.213** | **-0.014** | -0.397 |
| D HRP slice-1 | -0.622 | -0.158 | -0.623 |

**Slice 3 lift over slice 2 (Cell C):**

| Metric | Slice 2 | Slice 3 | Δ |
|---|---:|---:|---:|
| Mean pre-tax Sharpe | 0.557 | **0.740** | **+0.183** |
| Mean post-tax Sharpe | -0.673 | -0.601 | +0.072 |
| Tax drag $ | $7,516 | $11,636 | +$4,120 (more turnover) |
| Wash-sale blocks | 5,852 | 6,024 | +172 |

The bug fix is technically correct: removing the upper clamp at 1.0
lifts Cell C +0.183 pre-tax. The redistribution invariants
(mean=1.0, mass above and below) are verified by both unit tests and
the histogram diagnostic. The increase in tax drag (+$4,120) is the
expected signature of more aggressive sizing: above-mean tickers
are now amplified above 1.0, generating more dollar-volume turnover
and proportionally more taxable activity.

**But Cell C (0.740) is still 0.884 below Cell B (1.624).** HRP
composition does not add value over wash-sale-only on this
3-active-edge / prod-109 / 2025 ensemble.

### Determinism note

Cell A produced 2/3 unique canon md5s — run 1 (`7c1d33c6...`,
Sharpe 0.952) differed by 0.002 from runs 2 & 3 (`1ee035b1...`,
Sharpe 0.954). This is a first-run cold-start drift in the
governor anchor saved at `--save-anchor` time on this worktree, not
something slice-3 introduces. Cells B, C, and D each produced
1/3 unique canon (bitwise-identical reps). The 0.002 cell-A
spread is below the 0.183 slice-3 lift, so the slice-2 vs slice-3
comparison is robust to it.

### Optimizer-weight distribution (structural sanity)

`scripts/hrp_slice_3_redistribution_histogram.py` exercises the
composition layer on synthetic two-cluster panels at production
ticker counts (N=10, 20, 30) and dumps the resulting weight
distribution. Full output:
`docs/Audit/hrp_slice_3_histogram.json`. Summary:

| N | Mean | Min | Max | Stdev | %>1.0 | %<1.0 |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | **1.0000** | 0.028 | **2.153** | 0.837 | 50% | 50% |
| 20 | **1.0000** | 0.072 | **1.758** | 0.715 | 50% | 50% |
| 30 | **1.0000** | 0.106 | **1.613** | 0.600 | 50% | 50% |

The invariants are satisfied: mean is exactly 1.0 to 4 decimals,
distribution is bimodal-by-cluster as expected, max meaningfully
exceeds 1.0 at every N. The 1/N decay in stdev is the natural
HRP-on-2-cluster shape — as N grows, within-cluster weight
splitting drives both modes toward 1.0.

The slice-2 signature would have been: every weight ≤ 1.0, mass
piled at exactly 1.0, no values above. None of those signatures
are present in the slice-3 distribution.

This is a structural — not Sharpe — sanity check. The
A/B/C/D harness below measures Sharpe.

### Within-cell determinism

All four cells should produce 1/3 unique canon md5 across the 3
replicates (bitwise-identical) per the 2026-05-01 determinism floor.

---

## Pass/fail evaluation

| Criterion | Threshold | Result |
|---|---|---|
| C ≥ B pre-tax (HRP composition adds value over wash-sale alone) | 1.624 | **FAIL** (0.740, gap of −0.884) |
| C ≥ 1.7 pre-tax (stretch — HRP genuinely additive) | 1.700 | **FAIL** |
| D ≈ slice-1 0.331 (harness honest) | 0.30 ≤ D ≤ 0.36 | **PASS** (0.331 exact) |
| B ≈ slice-2 1.624 (harness honest) | 1.62 ≤ B ≤ 1.63 | **PASS** (1.624 exact) |
| Within-cell determinism (B, C, D) | 1/3 unique canon | **PASS** (all three) |
| Within-cell determinism (A) | 1/3 unique canon | **DEGRADED** (2/3, spread 0.002 — pre-existing first-run drift) |
| Mean optimizer_weight ≈ 1.0 (structural sanity) | abs(mean − 1) < 1e-3 | **PASS** (1.0000 at N=10/20/30) |
| Slice 3 lifts Cell C above slice 2 | C_slice3 > C_slice2 | **PASS** (0.740 > 0.557, Δ +0.183) |

### Verdict

Slice 3 is **technically correct** — the bug fix removes the upper
clamp, the redistribution invariants are verified, and Cell C lifts
+0.183 pre-tax over slice 2. **But the pass criterion C ≥ B fails
by a wide margin.** HRP composition does not add value on top of the
wash-sale gate alone on this 3-active-edge / prod-109 / 2025
ensemble; it removes value (−0.884 vs Cell B).

### Recommendation: PAUSE further HRP work

Per the user's pre-committed pass criterion:

> "If Cell C < Cell B, HRP composition is fundamentally not adding
> value to this 3-active-edge ensemble — flag and recommend pausing
> further HRP work."

The gap is ~5x larger than any noise floor in this measurement and
~5x larger than the slice-3 fix's own lift. Two more iterations on
HRP composition shape (e.g. options 2 or 3 from the design rationale,
or other normalizations) would not close 0.884 of Sharpe gap without
a structural change. The actionable recommendation is:

1. **Ship slice 3 as the bug fix it is** — the merged code on
   `main` is bit-identical to current main for `weighted_sum`
   default. The `hrp_composed` path is no longer broken; if a
   future regime/universe makes HRP additive, the path is ready.
2. **Do NOT flip `method = "hrp_composed"` in
   `config/portfolio_settings.json`.** The deployable retail config
   should remain `weighted_sum` + wash-sale + LT-hold (Cell B
   shape). That gives the 1.624 pre-tax Sharpe.
3. **Pause Engine C HRP work until one of:**
   - The active edge count grows large enough (≫ 3) that
     covariance-aware reweighting has more degrees of freedom to
     exploit. The current 3-active ensemble is fundamentally too
     thin for cross-ticker covariance to be additive.
   - A regime shift / universe change re-tests HRP under
     conditions where the inverse-variance signal becomes
     decisive.
4. **The Engine C HRP optimizer + turnover gate code (slice 1
   scaffolding)** stays in the tree. It works correctly. It just
   doesn't add value in the current ensemble. Re-running the
   harness in a future state — different active edge count,
   different universe, different cost regime — is a single-command
   operation: `python -m scripts.ab_path_a_tax_efficient_core
   --runs 3`.

### Why HRP composition fails on this ensemble — hypothesis

With only 3 active edges and a ~109-ticker universe, the
cross-ticker covariance signal is dominated by sector / index
beta (the prod-109 is concentrated in a handful of sectors). HRP
identifies those structural correlations and tries to size away
from the variance-rich names — but Engine A's edge-ensemble
conviction is *already* picking the highest-conviction names by
signal magnitude, which on prod-109 / 2025 happens to overlap with
the variance-rich names HRP wants to suppress. The composition
ends up cancelling part of conviction's directional bet.

This is consistent with slice 1's failure mode (where HRP
*replaced* conviction outright and dropped to 0.331). Slice 3's
multiplicative composition softens that cancellation but doesn't
eliminate it. The structural fix is more degrees of freedom in the
upstream conviction signal — i.e. a larger / more diverse active
edge ensemble — not a different HRP normalization.

---

## Engine boundary audit

- **Engine A (Alpha):** owns the composition layer. Modified the
  per-ticker `optimizer_weight` emission only on the composed path.
  Aggregate_score is still preserved exactly.
- **Engine B (Risk):** unmodified. Already consumes
  `optimizer_weight` from `signal.meta` in both ATR-risk and
  target-weight sizing paths (Path A merge, 2026-05-02). The same
  multiplier semantics apply — slice 3 just changes the *value* the
  multiplier can take.
- **Engine C (Portfolio):** unmodified. HRP optimizer + turnover
  gate behave identically.
- **Engines E, F, live_trader:** untouched.

## What ships to main

Default behavior on `main` after merge is bit-identical to pre-Path-A
(slice 2 already shipped default-OFF). The slice-3 change only
matters when `portfolio_optimizer.method == "hrp_composed"` is set in
`config/portfolio_settings.json` — which is itself default-off.

Per the verdict above, the recommendation is **NOT** to flip the
`hrp_composed` flag for deployable retail config. The bug fix ships
to keep the codebase honest (no broken-by-design code paths), but the
deployable retail config remains `weighted_sum` + wash-sale + LT-hold.

This branch's value is:

1. The slice-2 bug is fixed with test coverage and explicit
   invariants (mean=1.0 redistribution, no upper clamp degeneracy,
   low-vol ticker amplification > 1.05).
2. The A/B/C/D harness now produces a fair slice-3 measurement,
   re-runnable on any future universe / cost-model evolution via
   `python -m scripts.ab_path_a_tax_efficient_core --runs 3`.
3. The audit captures both the slice-2 design flaw and the
   slice-3 falsification under the same deterministic harness.
4. The clear recommendation to pause further HRP work until the
   active edge count materially grows or the universe / regime
   makes inverse-variance reweighting decisive.
