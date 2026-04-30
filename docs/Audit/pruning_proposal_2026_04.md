# Attribution-Based Pruning Proposal — Phase 2.10d Task A

Generated: 2026-04-30. Author: Agent B.

This is a **proposal document only**. It does not modify
`data/governor/edges.yml`. Application is gated on user approval after
Phase 2.10d Task B (capital allocation diagnostic, Agent A) completes.

The data behind every decision below is `data/research/per_edge_per_year_2026_04.csv`
(produced by Phase 2.10c, branch `per-edge-per-year-attribution`,
merged to main as `0a7c3a4`-class state). The audit narrative is in
`docs/Audit/per_edge_per_year_attribution_2026_04.md`. The
ensemble-vs-standalone reconciliation is in memory file
`project_ensemble_alpha_paradox_2026_04_30.md`.

---

## 1. Per-edge keep / cut / review decision (all 22 registered active+paused)

`mean_5y_pct` is the mean per-year contribution as % of $100k starting
capital across 2021-2025 integration runs. `min_yr` / `max_yr` are the
range. `fills` = total entry count across the two source runs.
"Bucket" is from the Phase 2.10c classifier. **Decision** is the
proposal here.

### Decisions table

| edge_id | bucket | status | tier | fills | mean 5y | min yr | max yr | decision | one-line justification |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| `volume_anomaly_v1` | stable | active | alpha | 657 | **+3.21%** | +1.93% | +4.94% | **KEEP** | Top contributor, positive every year 2021-2025 incl. -0.049 OOS year. |
| `herding_v1` | stable | active | alpha | 241 | **+1.45%** | +0.55% | +2.43% | **KEEP** | #2 contributor, positive every year 2021-2025. |
| `gap_fill_v1` | weak-positive | active | feature | 421 | +0.44% | +0.17% | +0.87% | **KEEP** | Best diversifier — every year non-negative, smooth low-magnitude additive. |
| `macro_credit_spread_v1` | weak-positive | active | retire-eligible | 644 | +0.15% | +0.05% | +0.33% | **KEEP** | Never negative, 644 fills, fills the macro-signal slot cheaply. |
| `macro_dollar_regime_v1` | weak-positive | active | retire-eligible | 145 | +0.03% | -0.05% | +0.17% | **KEEP** | Marginal but stable; the worst year is -0.05% (rounding noise). |
| `pead_v1` | weak-positive | active | feature | 22 | +0.00% | +0.00% | +0.01% | **KEEP** | Earnings-drift slot — fires too rarely to drag, hold for optionality. |
| `pead_predrift_v1` | weak-positive | active | retire-eligible | 147 | +0.00% | -0.06% | +0.08% | **REVIEW** | Mixed years (3 zero, 1 small +, 1 small -); ambiguous, see §4. |
| `growth_sales_v1` | sparse | active | feature | 116 | +0.02% | 0.00% | +0.08% | **REVIEW** | Only fired in 2025 (+0.08%), too new to characterize. |
| `panic_v1` | noise | active | feature | 18 | -0.03% | -0.16% | 0.00% | **CUT** | 5-year mean negative, no year clearly positive. |
| `value_trap_v1` | noise | active | feature | 47 | -0.01% | -0.05% | +0.01% | **CUT** | 5-year mean negative, fires often enough to drag without contributing. |
| `value_deep_v1` | sparse | active | feature | 1 | +0.00% | 0.00% | 0.00% | **CUT** | Effectively dead — 1 fill in 5 years; not earning its registry slot. |
| `pead_short_v1` | sparse | active | feature | 0 | +0.00% | 0.00% | 0.00% | **CUT** | Zero fills in 5 years; gating broken or signal never triggers. |
| `rsi_bounce_v1` | zero-fill | active | feature | 0 | n/a | n/a | n/a | **CUT** | Registered active but produced 0 fills in either run; dead weight. |
| `bollinger_reversion_v1` | zero-fill | active | feature | 0 | n/a | n/a | n/a | **CUT** | Same as rsi_bounce — 0 fills, signal-gen never produces output. |
| `earnings_vol_v1` | zero-fill | active | feature | 0 | n/a | n/a | n/a | **CUT** | 0 fills; either gate is broken or no qualifying earnings events fired. |
| `insider_cluster_v1` | zero-fill | active | feature | 0 | n/a | n/a | n/a | **CUT** | 0 fills; was supposed to be the insider-buying small-cap slot, doesn't fire on the 109-ticker prod universe. |
| `macro_real_rate_v1` | zero-fill | active | feature | 0 | n/a | n/a | n/a | **CUT** | 0 fills; macro signal never crossed its threshold over 5 years. |
| `atr_breakout_v1` | regime-conditional | paused | retire-eligible | 4486 | -1.18% | -5.78% | +1.09% | **CUT** (retire) | Lifecycle pause vindicated; -5.78% in 2022 + -2.23% in 2025 is unsalvageable as constant-weight. |
| `momentum_edge_v1` | regime-conditional | paused | retire-eligible | 15526 | -1.47% | -9.17% | +3.08% | **CUT** (retire) | -9.17% in 2022 alone exceeds full-portfolio CAGR. Massive fill-share rivalry. |
| `low_vol_factor_v1` | noise | paused | retire-eligible | 1594 | -0.39% | -2.53% | +0.47% | **CUT** (retire) | Soft-pause leak: 1,594 fills despite paused, -2.53% in 2025. |
| `macro_yield_curve_v1` | weak-positive | paused | feature | 1 | +0.02% | 0.00% | +0.11% | **CUT** | Paused + 1 fill total + tiny mean — no value in keeping registered. |
| `macro_unemployment_momentum_v1` | zero-fill | paused | feature | 0 | n/a | n/a | n/a | **CUT** | Paused + 0 fills — purely vestigial registry entry. |

**Bucket totals:**
- KEEP: **6**
- REVIEW: **2**
- CUT: **14** (4 noise/sparse-fired, 5 zero-fill registered, 5 paused/regime-conditional)

---

## 2. Recommended target stack (6 active edges)

| edge_id | mean 5y % | role | rationale |
| --- | ---: | --- | --- |
| `volume_anomaly_v1` | **+3.21%** | core alpha | Stable contributor every year. |
| `herding_v1` | **+1.45%** | core alpha | Stable contributor every year. |
| `gap_fill_v1` | +0.44% | diversifier | Smooth additive every year non-negative. |
| `macro_credit_spread_v1` | +0.15% | macro slot | Never negative, fills macro slot cheaply. |
| `macro_dollar_regime_v1` | +0.03% | macro slot | Marginal, but stable across regimes. |
| `pead_v1` | +0.00% | earnings slot | Fires too rarely to drag — optionality. |

**Aggregate expected contribution: +5.28% per year** (sum of 5-year
means). For comparison, the full integration's 2021-2024 CAGR was
6.06%; this 6-edge subset captures ~87% of the gross return without
the **-3.07% combined drag** from the 14 proposed cuts in 2025
(`low_vol_factor_v1` -2.53% + `atr_breakout_v1` -2.23% + `momentum_edge_v1`
-0.88% + others). On 2025 specifically, the 6-edge proposed stack
contributed **+1.93% + +0.55% + +0.17% + +0.23% + -0.01% + +0.01% =
+2.88%** — vs the actual 2025 portfolio CAGR of -0.049%, i.e. the
proposal recovers roughly **+2.9 percentage points of CAGR** in 2025
through pruning alone, before any allocation fix.

### Dilution / impact-knee acknowledgment

Cutting from 17 firing edges to 6 increases the per-fill capital
share roughly **2.83×** (17/6). Almgren-Chriss impact scales as
**√(qty/ADV)**, so the per-trade impact-tax should rise by **√2.83 ≈
1.68×**. Estimated current per-fill impact at 17 active edges is in
the 3-7 bps range (sub-knee, see memory
`project_ensemble_alpha_paradox_2026_04_30.md`); pruned-stack per-fill
impact lands in the 5-12 bps range. **This is still well sub-knee.**
The standalone gauntlet's failure mode required a **17×** allocation
multiplier (full per-trade allocation rather than split); a 2.83×
multiplier sits in the linear regime where impact stays a single-digit
percentage of the per-fill alpha rather than eating it.

That said, two specific risks warrant attention from Agent A's task:

1. **`volume_anomaly_v1` is sensitive.** Its per-fill avg PnL in the
   shared stack is around +$10 (per Agent A's 2025 decomposition).
   If pruning increases its fill size 2.8× without an allocation
   floor, the +$10/fill could compress to ~+$7-8/fill due to extra
   impact tax. Net contribution still positive, but materially less
   than the 3.21% mean above suggests.
2. **The capital-allocation problem changes shape, not magnitude.**
   With 6 edges, rivalry between the 2 alphas and 4 diversifiers
   could still pin the alphas if a diversifier overfires. Agent A's
   per-edge participation floor is the right primitive regardless of
   stack size.

---

## 3. Cut rationale by drag class

**Drag class A — actively destructive** (consistently negative; cut
status = retire so they cannot reactivate):

- **`atr_breakout_v1`** (paused → retire). 4,486 fills at -1.18%
  mean/yr, with -5.78% in 2022 and -2.23% in 2025. The 2024 +1.09%
  is real, but two negative years that size mean it cannot deploy as
  constant-weight without burning more than a year's gains. Lifecycle
  pause was correct; conversion to retire is the next step.
- **`momentum_edge_v1`** (paused → retire). 15,526 fills — by far
  the biggest fill-share consumer, accounting for most of the capital
  rivalry pathology Agent A identified. Mean -1.47%/yr with -9.17%
  in 2022. Even on its best year (+3.08% in 2024) it underperforms
  `volume_anomaly_v1`'s worst year (+1.93%). Retire.
- **`low_vol_factor_v1`** (paused → retire). 1,594 fills *despite*
  being paused — the soft-pause weight leak documented in the health
  check. -2.53% in 2025 alone. Retire status removes its registry
  entry from `list_tradeable()` (which currently returns
  active+paused), eliminating the leak vector.

**Drag class B — net-zero or near-zero noise** (cut status = archive,
not retire — keep code for possible future revival or threshold
re-calibration):

- **`panic_v1`** (active → archive). 18 fills, -0.03% mean, peaked at
  -0.16% in 2025. Either the panic detector has its threshold
  miscalibrated for this universe or the panic regime didn't occur in
  the data window. Code worth keeping.
- **`value_trap_v1`** (active → archive). 47 fills, -0.01% mean, no
  year clearly positive. Same calibration question.
- **`value_deep_v1`** (active → archive). 1 fill in 5 years. The
  signal logic almost certainly never triggers on the prod universe —
  a threshold issue more than a signal-quality issue.
- **`pead_short_v1`** (active → archive). 0 fills. Probably the short-
  side counterpart to `pead_v1` and the threshold or regime-gate is
  wrong.

**Drag class C — zero-fill dead-registry** (cut status = archive):

- **`rsi_bounce_v1`**, **`bollinger_reversion_v1`**,
  **`earnings_vol_v1`**, **`insider_cluster_v1`**,
  **`macro_real_rate_v1`** — registered active but produced zero
  fills in either run. These are signaling that something in their
  `compute_signals` or upstream-feature pipeline is broken/unfit for
  the prod universe. Archive (don't delete code) so they can be
  re-engineered in a future session if the universe expands or
  features are added.

**Drag class D — paused vestiges** (cut status = archive):

- **`macro_yield_curve_v1`** — 1 fill, +0.02% mean. Already paused.
- **`macro_unemployment_momentum_v1`** — 0 fills. Already paused.

These are essentially registry hygiene; their continued presence
clutters lifecycle reporting without contributing to either gross
return or rivalry analysis.

The drag/noise distinction matters for `LifecycleManager` decisions:
**retire** flagged edges are excluded from any future revival path
(see `engines/engine_f_governance/lifecycle.py`); **archive** keeps the
code but removes the active-trading status. The proposal here uses
retire only for the three with quantified large-magnitude losses —
the rest archive so that a future calibration push could revive them
through Discovery's gauntlet.

---

## 4. Concerns and unknowns

**4.1 Regime-conditional edges might earn revival under a smarter
weighting policy.** `momentum_edge_v1` has a +3.08% year (2024) and a
-9.17% year (2022). The 5-year mean is dragged negative entirely by
2022. A regime-aware sizer (Agent A's task B item #3) that cuts these
edges to zero in 2022-class regimes would convert them from "retire"
candidates back into useful contributors. **Recommendation: retire
*as constant-weight active edges*, but tag the spec with a future
revival path** — i.e. they can come back through Discovery's gauntlet
when paired with a regime-conditional weight schedule. Don't delete the
edge code.

**4.2 `pead_predrift_v1` is genuinely ambiguous (REVIEW).** Year
breakdown: +0.08% (2021), 0.00% (2022), -0.06% (2023), 0.00% (2024),
-0.02% (2025). 147 fills total. The negative years are tiny. Could
just as well be coin-flip noise from the small fill count. Recommend:
**keep active for now, flag for re-evaluation after the 2025
re-test** — if it crosses into "noise" territory there, archive then.
Costs little to keep.

**4.3 `growth_sales_v1` only fired in 2025 (REVIEW).** 116 fills,
+0.08%, all in one year. Could be a new signal that just started
firing, or could be a regime artifact. Insufficient data to decide.
Recommend: **keep active for one more in-sample-spanning re-test**,
re-evaluate when there's at least 2 years of fills.

**4.4 Zero-fill edges may have broken signal generators.** The 5
zero-fill registered-active edges (`rsi_bounce_v1`, etc.) might have
hidden bugs that were masked by `compute_signals` returning empty
without warning. **Side recommendation for Engine A:** add a per-edge
quarterly fill-count assertion in `signal_processor` that emits a
warning if an edge has produced zero fills in N consecutive quarters.
This isn't part of the pruning proposal but should be a follow-up.

**4.5 Pruning alone may amplify volume_anomaly's per-fill cost.** Per
§2 dilution analysis, the proposed 6-edge stack increases per-fill
impact ~1.68×. The contributors most exposed are exactly the
high-conviction edges that fire small (volume_anomaly_v1 at 657 fills
across 5 yrs). Without Agent A's per-edge participation floor, a
post-prune over-firing of `gap_fill_v1` or `macro_credit_spread_v1`
could starve `volume_anomaly_v1` of slots even in a 6-edge stack —
just at smaller scale than the 17-edge case.

---

## 5. Implementation sketch — yaml diff (NOT applied)

The following is the proposed change to `data/governor/edges.yml`,
shown in unified-diff form. **DO NOT APPLY** until Agent A's task
finishes and the user approves the combined Phase 2.10d Task C plan.

```yaml
# Active list ends up at 6 edges (down from 17).
# Status conventions per current registry:
#   active → trades at full configured weight
#   paused → trades at soft-pause weight (0.25x in current code)
#   archived → does NOT appear in list_tradeable(), code retained
#   retired → does NOT appear, NOT a candidate for revival via Discovery
```

```diff
 edges:
   - edge_id: rsi_bounce_v1
-    status: active
+    status: archived  # 0 fills 2021-2025; signal-gen produces no output
     tier: feature

   - edge_id: value_trap_v1
-    status: active
+    status: archived  # noise: 47 fills, -0.01%/yr mean, no positive year
     tier: feature

   - edge_id: value_deep_v1
-    status: active
+    status: archived  # 1 fill in 5 years; signal threshold never triggers
     tier: feature

   - edge_id: growth_sales_v1
     status: active   # KEEP — REVIEW after next re-test (2025-only fills)
     tier: feature

   - edge_id: bollinger_reversion_v1
-    status: active
+    status: archived  # 0 fills 2021-2025
     tier: feature

   - edge_id: gap_fill_v1
     status: active   # KEEP — best diversifier, every year non-negative
     tier: feature

   - edge_id: volume_anomaly_v1
     status: active   # KEEP — top contributor, +3.21%/yr mean
     tier: alpha

   - edge_id: panic_v1
-    status: active
+    status: archived  # noise: -0.03% mean, peaked at -0.16% in 2025
     tier: feature

   - edge_id: herding_v1
     status: active   # KEEP — #2 contributor, +1.45%/yr mean
     tier: alpha

   - edge_id: earnings_vol_v1
-    status: active
+    status: archived  # 0 fills 2021-2025
     tier: feature

   - edge_id: pead_v1
     status: active   # KEEP — earnings slot, never drags
     tier: feature

   - edge_id: insider_cluster_v1
-    status: active
+    status: archived  # 0 fills 2021-2025; doesn't fire on prod universe
     tier: feature

   - edge_id: macro_credit_spread_v1
     status: active   # KEEP — never negative, 644 fills macro slot
     tier: retire-eligible  # consider promoting tier to "feature" — name is now wrong

   - edge_id: macro_real_rate_v1
-    status: active
+    status: archived  # 0 fills 2021-2025
     tier: feature

   - edge_id: macro_dollar_regime_v1
     status: active   # KEEP — marginal but stable across regimes
     tier: retire-eligible

   - edge_id: pead_short_v1
-    status: active
+    status: archived  # 0 fills 2021-2025
     tier: feature

   - edge_id: pead_predrift_v1
     status: active   # KEEP — REVIEW after next re-test (mixed years)
     tier: retire-eligible

   - edge_id: atr_breakout_v1
-    status: paused
+    status: retired  # -5.78% in 2022 + -2.23% in 2025 — pause vindicated
     tier: retire-eligible

   - edge_id: momentum_edge_v1
-    status: paused
+    status: retired  # -9.17% in 2022 alone; biggest fill-share rivalry source
     tier: retire-eligible

   - edge_id: macro_yield_curve_v1
-    status: paused
+    status: archived  # 1 fill in 5 years, vestigial
     tier: feature

   - edge_id: low_vol_factor_v1
-    status: paused
+    status: retired  # -2.53% in 2025 + soft-pause leak (1594 fills despite paused)
     tier: retire-eligible

   - edge_id: macro_unemployment_momentum_v1
-    status: paused
+    status: archived  # 0 fills, vestigial
     tier: feature
```

After applying, `list_tradeable()` returns:
`['volume_anomaly_v1', 'herding_v1', 'gap_fill_v1',
 'macro_credit_spread_v1', 'macro_dollar_regime_v1', 'pead_v1',
 'growth_sales_v1', 'pead_predrift_v1']` — 8 entries (6 confident KEEP
+ 2 REVIEW). The two REVIEW entries earn one more re-test cycle
before potentially being archived in a follow-on prune.

(Side issue surfaced by writing this diff: `tier: retire-eligible` on
KEEP entries `macro_credit_spread_v1` and `macro_dollar_regime_v1` is
now inconsistent — they're being kept, so "retire-eligible" is the
wrong tier. The TierClassifier should be re-run after pruning. Not
part of this proposal; flagging.)

---

## 6. Honest commentary — confidence in clearing the Phase 2.10d gate

**Confidence pruning alone clears the 2.10d gate (post-fix 2025 OOS
Sharpe > ~0.65): roughly 35-50%.** The arithmetic favors pruning: the
proposed cuts remove ~5.85 percentage points of 2025 drag (the bottom
3 alone — `low_vol_factor_v1`, `atr_breakout_v1`, `momentum_edge_v1`
— were -5.64% in 2025), which on a 5-7% vol denominator would lift
2025 Sharpe by roughly 0.7-1.1 absolute. That math suggests pruning
*could* be sufficient. But the math is also too optimistic: pruning
mechanically removes losers but doesn't fix the structural pathology
that allowed those losers to consume 83% of fill share in the first
place. With a 6-edge stack, the next biggest fill-share consumer
(probably `gap_fill_v1` or `macro_credit_spread_v1`) takes over the
rivalry role; if it overfires in a stressed regime, the same pattern
re-emerges at smaller scale. The dilution analysis in §2 specifically
flags that `volume_anomaly_v1`'s per-fill alpha of ~+$10 could
compress under the 1.68× impact tax increase from a smaller stack —
that compression eats some of the gain pruning is supposed to deliver.

**Agent A's capital allocation fix is essential to robustly clear the
gate.** The two work streams aren't redundant — they fix different
things. Pruning removes the worst offenders; the per-edge
participation floor + soft-pause leak fix + regime-aware slot
reduction primitive (B's three items) prevent any *future* edge —
including currently-good ones — from dominating fill share when
conditions shift. Without B, a year with elevated `volume_anomaly_v1`
firing could pin every diversifier to zero fills and create the
opposite-but-equivalent rivalry. **Net recommendation: ship the prune
AND ship Agent A's fixes; expect pruning alone to take 2025 OOS into
the 0.3-0.6 Sharpe range, and the combined intervention into the
0.7-1.0 range.** That's the wager Phase 2.10d gates on.

---

## 7. Provenance

- Source attribution data: `data/research/per_edge_per_year_2026_04.csv`
  (commit on main from `per-edge-per-year-attribution`)
- Source narrative: `docs/Audit/per_edge_per_year_attribution_2026_04.md`
- Source registry: `data/governor/edges.yml`
- Reconciliation memory: `project_ensemble_alpha_paradox_2026_04_30.md`
- Health check status: `docs/Audit/health_check.md` HIGH (2026-04-30)
- Forward plan: `docs/Core/forward_plan_2026_04_30.md` Phase 2.10d
- Branch: `pruning-proposal` off `main`
- Driver: none — this is a pure proposal document, no code or backtests
  were run.
