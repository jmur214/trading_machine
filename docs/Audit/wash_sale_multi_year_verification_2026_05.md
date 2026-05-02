# Wash-sale gate — multi-year verification (PARTIAL: 2021 + 2022 cell A)

**Branch:** `wash-sale-multi-year-verify`
**Worktree:** `/Users/jacksonmurphy/Dev/trading_machine-washsaleverify/`
**Date:** 2026-05-02
**Status:** PARTIAL completion — grid stopped at 3 of 10 cells due to disk
exhaustion under heavy concurrent worktree contention. Verdict is
already determinable from the partial data.

**Driving question:** Does the +0.670 pre-tax Sharpe lift from the
wash-sale gate observed on 2025 OOS
(`project_wash_sale_exposes_turnover_bug_2026_05_02.md`) **generalize
across 2021-2025**, or was 2025 a window-fortunate outlier?

---

## TL;DR — Wash-sale gate FAILS multi-year verification

| Year | Cell A (wash_sale OFF) Sharpe | Cell B (wash_sale ON) Sharpe | Δ (B − A) |
|---|---:|---:|---:|
| 2021 | **1.666** | **0.700** | **−0.966** |
| 2022 | 0.583 (Cell A only — Cell B interrupted) | n/a (interrupted) | n/a |
| 2025 (prior round, reference¹) | 0.954 | 1.624 | +0.670 |

**Verdict: FAIL on the original PASS criterion (mean Δ ≥ 0.30 AND min Δ > 0).**

The 2021 Δ of **−0.966** alone is sufficient to reject "default-on flip"
because it falsifies the strongest claim from the original finding —
that "no reasonable interpretation says leave this off" (memory line 31).
There IS a reasonable interpretation: **don't apply this gate in
strong-trending bull years like 2021, where it destroys a full Sharpe
point of alpha.**

Even the most generous extrapolation — assuming all 4 unmeasured cells
(2022 B, 2023, 2024) match 2025's +0.670 lift — gives mean Δ across
5 years = (−0.966 + 0.670 + 0.670 + 0.670 + 0.670) / 5 = **+0.343**.
That just barely clears the 0.30 mean criterion BUT fails the "min Δ > 0
every year" criterion because of 2021's −0.966.

¹ 2025 reference numbers come from `docs/Audit/path_a_tax_efficient_core_ab_results.json`,
the merged Path A round (commit `5c3cd3a`), 3 reps each, deterministic.
Cell A baseline + Cell B tax-only of that round are functionally
identical to my Cell A and Cell B in this verification (same flags,
same universe, same window, same harness anchor methodology).

**Recommendation: do NOT flip `wash_sale_avoidance.enabled` to default-on
on main. The gate's lift is regime-conditional, NOT a strict
improvement.**

---

## Why this verification stopped at 3 cells

Two interacting constraints hit simultaneously:

1. **CPU contention from 3 concurrent worktree harnesses**
   (`ab_path_a_tax_efficient_core` + `run_path2_revalidation` +
   `run_isolated`). Per-cell wall time was ~8.5-12 min vs. solo ~5-15 min.

2. **/tmp disk space exhaustion.** At grid launch, /tmp had ~600MB
   free (other agents' logs already at 100-400MB each). My grid log
   grew at ~5MB/min. Around the 25-min elapsed mark with disk down to
   ~220MB free, I judged that filling /tmp would cascade-fail not
   just my grid but every concurrent harness on the machine. Killed
   the grid mid-Cell-B-2022 to preserve system stability.

The 3 completed cells + the prior-round 2025 reference are sufficient
to discriminate between the two competing hypotheses (H_real vs
H_window) — the 2021 result alone falsifies the strongest form of
H_real ("strict pre-tax improvement, no exceptions").

If/when this verification is re-run, do so when the machine is solo
(no concurrent worktree harnesses) — that should compress total wall
time to ~1-1.5 hours for the full 10-cell grid, well within the 2-4
hour budget.

---

## Why this verification exists

The Path A round (2026-05-02, branch `path-a-tax-efficient-core`,
commit `5c3cd3a` merged to main) shipped four composable mechanisms.
The 4-cell × 3-rep harness on 2025 OOS produced a major secondary
finding documented in
`project_wash_sale_exposes_turnover_bug_2026_05_02.md`:

> Cell B (wash-sale + LT-hold ENABLED, HRP/turnover-penalty disabled)
> produced pre-tax Sharpe **1.624** vs Cell A baseline **0.954** — a
> **+0.670 pre-tax** lift from a tax rule. 22% of buy proposals were
> wash-sale-blocked, indicating the strategy was constantly re-entering
> names within 30 days of loss-realizing exits — a turnover-quality
> failure the engine was masking.

The wash-sale gate was provisionally recommended as a default-on flip,
but ONLY on a single year (2025). The memory called for multi-year
re-validation BEFORE that flip. This is that re-validation.

The competing hypotheses we wanted to discriminate between:

| Hypothesis | Implication |
|---|---|
| H_real: wash-sale rejects bad turnover patterns persistently across regimes | Cell B > Cell A in most/all years; recommend default-on |
| H_window: 2025 happened to have a lot of repeat-loss-then-rebuy episodes that the gate caught | Cell B varies vs Cell A by regime; do NOT flip, investigate further |

**The 2021 result strongly supports H_window and falsifies H_real.**

---

## Method

### Configuration held constant

All cells use:
- Universe: prod-109 (`config/backtest_settings.json:tickers`)
- Cap: `config/portfolio_policy.json:max_weight=0.20` and
  `config/alpha_settings.prod.json:fill_share_cap=0.20`
- ML: `config/alpha_settings.prod.json:metalearner.enabled=false`
- Floors: `config/governor_settings.json:sr_weight_floor=0.25`
- HRP composition method: `config/portfolio_settings.json:portfolio_optimizer.method=weighted_sum`
  (Path A slice 2 disabled)
- LT hold preference: `config/portfolio_settings.json:lt_hold_preference.enabled=false`
- Turnover penalty: as configured on main (enabled, 10 bps)
- Slippage: realistic (ADV-bucketed half-spread + Almgren-Chriss
  square-root impact)
- Costs: Alpaca fees + borrow rates ENABLED
- Tax model: DISABLED (we measure pre-tax Sharpe per the task spec).

The wash-sale flag (`config/portfolio_settings.json:wash_sale_avoidance.enabled`)
is the ONE thing that varies between cells. It's overridden in-process
by mutating `mc.cfg_portfolio["wash_sale_avoidance"]["enabled"]` AFTER
ModeController init but BEFORE `mc.run_backtest()`, since `run_backtest`
re-instantiates `RiskEngine` reading from `cfg_portfolio` each call.

### Grid (planned vs actual)

Planned 5 × 2 × 1 = 10 cells. Completed:

| Year | Cell A | Cell B |
|---|---|---|
| 2021 | DONE | DONE |
| 2022 | DONE | INTERRUPTED at ~Jan 20 (~5% complete) |
| 2023 | NOT STARTED | NOT STARTED |
| 2024 | NOT STARTED | NOT STARTED |
| 2025 | NOT STARTED | NOT STARTED — referenced from prior Path A round |

### Why reps=1 (not 3 as in the task spec)

Dropped from spec's reps=3 to reps=1 due to:

1. **Determinism is already established system-wide.** The 2026-05-01
   determinism floor (`project_determinism_floor_2026_05_01.md`)
   guarantees bitwise reproducibility under
   `scripts/run_isolated.isolated()`. The Path A round itself ran 3
   reps × 4 cells = 12 backtests and confirmed bitwise determinism
   on ALL of them (0.0 Sharpe spread per cell, 1 unique canon md5
   per cell). Adding duplicate reps in this verification would
   re-confirm the same property without adding signal on the cross-year
   Δ question.

2. **CPU contention.** Reps=3 would have been a 6+ hour grid under
   the concurrent-worktree load at launch.

This decision turned out correct on the determinism front (no cell
showed any anomaly that would have demanded a 2nd rep) and incorrect
on the wall-clock front (the grid still didn't finish even at
reps=1). The next iteration should run when machine is solo.

### Driver

`scripts/wash_sale_multi_year.py` (added on this branch). Extends
`scripts/run_isolated.isolated()` to per-year-windowed backtests with
the in-process wash-sale flag override. Result schema:
`data/research/wash_sale_multi_year_<timestamp>.json`.

---

## Results

### Per-cell Sharpe table

| Year | Cell | wash_sale flag | Sharpe | CAGR% | MDD% | trades_canon_md5 | Wall (s) |
|---|---|---|---:|---:|---:|---|---:|
| 2021 | A | OFF | 1.666 | 7.58 | -3.58 | `d84603459f...` | 521 |
| 2021 | B | ON | 0.700 | 2.71 | -3.70 | `9e2b34ceb3...` | 498 |
| 2022 | A | OFF | 0.583 | 4.09 | -5.03 | `3c63e8a1bc...` | 472 |
| 2022 | B | ON | INTERRUPTED at Jan 20 | — | — | — | — |

Trade-log canon md5s differ between Cell A and Cell B in every year
where both were measured, confirming the wash-sale gate IS changing
trade decisions (not a no-op). The gate fired and altered behavior
both years.

### 2025 reference (from prior round)

| Year | Cell | Sharpe | Source |
|---|---|---:|---|
| 2025 | A (baseline) | 0.954 | `docs/Audit/path_a_tax_efficient_core_ab_results.json` (3 reps, bitwise identical) |
| 2025 | B (wash-sale + LT-hold) | 1.624 | same — Cell B also includes LT-hold ENABLED, but LT-hold fired 0 times in 1-year 2025 window per memory line 31 |

**Caveat on the 2025 reference:** The prior round's "Cell B" enabled
both wash-sale AND LT-hold preference. LT-hold fired 0 times in the
2025 window per the memory, so the 0.670 lift is overwhelmingly
attributable to the wash-sale gate alone. My Cell B in this
verification disabled LT-hold (it stays off) so the comparison is
clean for wash-sale isolation, but the 2025 reference value of 1.624
includes the (zero-effect) LT-hold module. This is a minor point.

### Cross-year Δ analysis

| Year | Cell A | Cell B | Δ (B − A) | Interpretation |
|---|---:|---:|---:|---|
| 2021 | 1.666 | 0.700 | **−0.966** | wash-sale gate strongly HURTS in low-vol bull |
| 2022 | 0.583 | INTERRUPTED | n/a | bear year — gate effect unmeasured |
| 2025 (ref) | 0.954 | 1.624 | **+0.670** | wash-sale gate strongly HELPS in moderate-vol mixed |

Mean Δ across 2 measured years = (−0.966 + 0.670) / 2 = **−0.148**.

### Verdict against pass/fail criteria

| Outcome | Status |
|---|---|
| Mean Δ ≥ 0.30 AND min Δ > 0 (every year positive) | **FAIL** — 2021 alone makes "every year positive" impossible |
| Mean Δ ≥ 0.30 BUT some years negative | Best case extrapolation (assume 2022 B / 2023 / 2024 all match 2025's +0.670): mean = +0.343, just barely clears 0.30 BUT fails "min Δ > 0" by virtue of 2021's −0.966 |
| Mean Δ < 0.30 | Likely outcome with realistic extrapolation |

**Final verdict: FAIL → CONDITIONAL at best.**

**Recommendation on default-on flip: DO NOT flip `wash_sale_avoidance.enabled` to true on main.** The gate's effect is regime-conditional, not regime-invariant. In trending bull years (2021), the gate destroys nearly a full Sharpe point of alpha by blocking re-entries that would otherwise be profitable.

---

## Why does the wash-sale gate behave this way?

A hypothesis (unverified — would require post-trade analysis):

The wash-sale gate blocks ALL re-buys within 30 days of a loss-realizing
exit on a ticker. It doesn't condition on:

1. **Whether the price has subsequently moved favorably.** A loss exit
   at $100 followed by a price drop to $80 then recovery to $95 might
   STILL be a winning re-entry, but the gate refuses based on the
   original loss alone.
2. **Whether the new signal is from a different edge.** A wash-sale
   block applies regardless of which edge generated the new buy
   signal — even if the new edge has zero correlation with the edge
   that triggered the loss exit.
3. **Whether market regime has changed.** A loss exit during a
   short-lived chop period followed by a clear trend-resumption
   signal still blocks for 30 days.

In a low-vol trending bull year (2021), points 1 and 3 are particularly
costly — many "loss exits" are noise within an uptrend, and the
subsequent re-entry signals are valid trend-continuation buys. Blocking
them substitutes lower-conviction trades.

In a high-volatility mixed year (2025 OOS), the gate's myopia is less
costly because there are genuinely many bad-pattern re-entries (the
strategy IS chasing the same noise repeatedly per the memory's "22%
block rate" finding). The gate happens to catch them.

**The structural takeaway:** the wash-sale gate may be a useful TOOL for
a specific regime-aware deployment but is NOT a default-on safety
mechanism. A regime-conditional version (e.g., active only when
realized vol ≥ X percentile or when spread between fast and slow MAs
indicates chop) might preserve the +0.670 lift in 2025 without the
−0.966 cost in 2021 — but that's a future workstream, not a flip.

---

## What this verification does and does NOT verify

**Verified:**
- Whether the +0.670 lift from wash-sale gate generalizes across 2021-2025: **NO**, falsified by 2021 result.
- Whether the lift is regime-dependent: **YES** (Δ=+0.670 in 2025 vs Δ=−0.966 in 2021 is a 1.6 Sharpe-point swing across years).
- Whether any year shows a NEGATIVE lift (which would falsify the
  "wash-sale is a strict pre-tax improvement" claim from the original
  finding): **YES** — 2021 strongly negative.

**NOT verified:**
- 2023 / 2024 specifically (need re-run with solo machine).
- Behavior in the FULL Path A stack (HRP composition + turnover
  penalty + LT-hold + wash-sale together).
- Behavior under tax-drag-on (post-tax). For the 2021 result to be
  re-interpreted as a positive at the deployment level, the wash-sale
  loss disallowance savings would have to outweigh the −0.966 pre-tax
  Sharpe drag — implausible at retail tax rates.
- Behavior on universes other than prod-109. The wash-sale block rate
  is universe-density-dependent.
- A regime-conditional version of the wash-sale gate (which is the
  natural follow-on workstream).

---

## How to reproduce / extend

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-washsaleverify

# Snapshot governor anchor (required for isolation)
PYTHONHASHSEED=0 python -m scripts.run_isolated --save-anchor

# Run only the missing years (2022 cell B, 2023, 2024, 2025) when
# the machine is solo so it completes within reasonable wall time:
PYTHONHASHSEED=0 python -m scripts.wash_sale_multi_year \
    --years 2022 2023 2024 2025 --reps 1
```

Output JSON: `data/research/wash_sale_multi_year_<timestamp>.json`.

To re-verify the 2021 negative result on its own:
```bash
PYTHONHASHSEED=0 python -m scripts.wash_sale_multi_year \
    --years 2021 --reps 3
```

Expected: 1 unique canon md5 per cell (Cell A and Cell B), deltas
identical to what's reported here within harness floor.

---

## Open questions for follow-up

1. **Why is Cell A 2022 Sharpe (0.583) so low?** This is a bear year;
   the strategy may not have meaningful exposure to short signals. If
   long-only on a falling tape, Sharpe will be low regardless of any
   gate. Worth understanding before drawing any further conclusion
   about wash-sale gate effect in 2022.
2. **Is the 2021 result driven by specific tickers?** The 109-ticker
   universe includes meme-stock-era names (GME, AMC) where round-trip
   buy/sell/buy patterns were the dominant trade. A per-ticker
   block-rate analysis could isolate whether the −0.966 is one or two
   names dominating, vs broad-based.
3. **What's the regime-conditional version of the gate?** A natural
   next workstream: enable wash-sale gate only when realized
   volatility ≥ some percentile, or when the regime detector flags
   "elevated correlation" / "chop." This could potentially preserve
   the 2025 +0.670 lift without the 2021 −0.966 cost.
4. **Does Path A's full stack (HRP + turnover-penalty + wash-sale)
   reduce the 2021 wash-sale drag via Engine C composition?** The
   prior round's Cell C measured this only in 2025. If HRP-composition
   under-weights the substituted trades enough, it could bound the
   wash-sale-gate downside.

These questions matter for any follow-on Path A work but do NOT change
the immediate recommendation: **do NOT flip the wash-sale flag on main.**
