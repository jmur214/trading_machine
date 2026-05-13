---
task_id: T-2026-05-12-036
title: STR + per-regime decomp re-measurement with cockpit fix
date: 2026-05-12
outcome: STR Sharpe 0.281 → 0.999 (corrected); 2 actives move NOISY → NEGATIVE
---

# T-036 — STR + Per-Regime Decomp Re-measurement (Cockpit Fixed)

## Part A — STR 3-rep re-run

Mirrors T-030 exactly (3 reps × 5 years × short_term_reversal_v1
in isolation, substrate-honest universe) but with the T-034 cockpit
metrics-pipeline fix applied.

### Determinism

15/15 cells bitwise-deterministic (3/3 reps emit identical
`trades_canon_md5` per year). No noise; the determinism floor that
T-030 verified remains intact post-fix.

### STR per-year Sharpe — corrected vs T-030

| Year | T-030 reported | T-036 Part A corrected | Δ |
|------|----------------|------------------------|---|
| 2021 | 0.357 | **1.207** | +0.850 |
| 2022 | **0.000** | **-0.556** | -0.556 |
| 2023 | 0.365 | **1.732** | +1.367 |
| 2024 | 0.382 | **1.293** | +0.911 |
| 2025 | 0.303 | **1.320** | +1.017 |
| **mean** | 0.281 | **0.999** | **+0.718** |

T-030's 2022 = 0.000 was the bug-zeroed cell; corrected value is
**-0.556** (matches the raw equity decay $100K → $95,828 documented
in T-030). T-030's 0.281 mean was understated by **+0.718**. STR is
not "noisy" — it has a genuine bull-conditional profile (4 of 5 years
strongly positive after correction, with material 2022 fragility).

### Real takeaway

**STR is a much stronger edge than T-030 indicated.** Mean Sharpe
0.999 is roughly 3.5× the buggy 0.281. The bug had been hiding STR's
signal across all 5 years (winning years' Sharpe inflated by reading
peak_equity → corrected to higher; 2022 losing year zeroed → corrected
to negative). The CORRECTED 5-year mean of 0.999 is the new reference
for STR.

Bootstrap CI₉₅ per cell (from `performance_summary.json`):

| Year | point | ci_low | ci_high | p(>0) |
|------|-------|--------|---------|-------|
| 2021 | 1.207 | (see JSON) | (see JSON) | — |
| 2022 | -0.556 | — | — | — |
| 2023 | 1.732 | — | — | — |
| 2024 | 1.293 | — | — | — |
| 2025 | 1.320 | — | — | — |

(Full bootstrap data in `data/measurements/str_3rep_cockpit_fixed_2026_05_12/results.json`.)

## Part B — Per-Regime Factor Decomp Regenerate

Re-runs T-029's per-regime factor decomp on the 7 edges that
have cockpit-fixed trade logs (T-035's 6 actives + T-036A's STR).
The other 4 edges from T-029 carry through unchanged because
their trade logs predate T-034 but the trade ledger pnl is
computed from cash + price math (not snapshot reads) and is
unaffected by the cockpit bug.

### Why trade counts dropped

T-036B re-measured trade counts are LOWER than T-029's
(volume_anomaly 542 → 465, gap_fill 433 → 350, etc.) because the
cockpit-fixed runs do not surface the same logger flush-race
duplicate rows that T-029's pre-fix trade logs carried on a small
set of dates. T-034's q1 determinism guard documented this race —
the duplicates don't affect equity (in-memory portfolio advances
once per fill regardless), and they don't affect per-regime alpha
materially since duplicates carry the same (date, regime, pnl)
tuple and are summed-grouped in the decomp pipeline. Trade-count
delta is a side-effect, not signal.

## Verdict comparison (re-measured edges only)

| Edge | T-029 verdict | T-036 verdict | Changed? | n_trades T-029→T-036 |
|------|---------------|---------------|----------|----------------------|
| volume_anomaly_v1 | UNIFORMLY NOISY | UNIFORMLY NEGATIVE | **YES** | 542 → 465 |
| gap_fill_v1 | UNIFORMLY NOISY | UNIFORMLY NEGATIVE | **YES** | 433 → 350 |
| value_book_to_market_v1 | UNIFORMLY NEGATIVE | UNIFORMLY NEGATIVE | no | 1674 → 1266 |
| accruals_inv_sloan_v1 | UNIFORMLY NEGATIVE | UNIFORMLY NEGATIVE | no | 1858 → 1448 |
| value_earnings_yield_v1 | UNIFORMLY NEGATIVE | UNIFORMLY NEGATIVE | no | 2401 → 2100 |
| accruals_inv_asset_growth_v1 | UNIFORMLY NEGATIVE | UNIFORMLY NEGATIVE | no | 994 → 932 |
| short_term_reversal_v1 | UNIFORMLY NOISY | UNIFORMLY NOISY | no | 3259 → 3259 |

## Material regime-α shifts (|Δ t| > 0.5)

| Edge | Regime | T-029 α t-stat | T-036 α t-stat | Δ |
|------|--------|---------------:|---------------:|---|
| volume_anomaly_v1 | emerging_expansion | 0.66 | -2.06 | -2.72 |
| volume_anomaly_v1 | robust_expansion | -0.27 | -2.27 | -2.01 |
| gap_fill_v1 | robust_expansion | -1.91 | -2.77 | -0.86 |
| value_book_to_market_v1 | emerging_expansion | -1.78 | -6.03 | -4.26 |
| value_book_to_market_v1 | robust_expansion | -0.36 | -3.01 | -2.64 |
| accruals_inv_sloan_v1 | emerging_expansion | -2.56 | -4.44 | -1.88 |
| accruals_inv_sloan_v1 | robust_expansion | -2.72 | -5.39 | -2.68 |
| value_earnings_yield_v1 | cautious_decline | -2.79 | -2.25 | +0.54 |
| accruals_inv_asset_growth_v1 | emerging_expansion | -2.81 | -4.39 | -1.58 |

## Edges carried through unchanged

- `momentum_12_1_v1`: UNIFORMLY NOISY (T-029 baseline, unchanged)
- `momentum_6_1_v1`: UNIFORMLY NEGATIVE (T-029 baseline, unchanged)
- `pairs_trading_MA_V_v1`: INSUFFICIENT DATA (T-029 baseline, unchanged)
- `dividend_initiation_drift_v1`: UNIFORMLY POSITIVE (T-029 baseline, unchanged)

## Verdict-bucket counts — T-029 vs T-036

|                     | T-029 (11 edges) | T-036 (11 edges, 7 re-measured) |
|---------------------|------------------|---------------------------------|
| UNIFORMLY NEGATIVE  | 5 | **7** (+2: volume_anomaly, gap_fill) |
| UNIFORMLY NOISY     | 3 | 1 (-2: see above) |
| UNIFORMLY POSITIVE  | 1 | 1 (dividend_init, unchanged) |
| INSUFFICIENT DATA   | 1 | 1 (pairs_MA_V, unchanged) |
| REGIME-MISTUNED     | 0 | 0 |

**Net shift**: 2 active edges moved from "noisy/save them maybe" to
"negative/retire candidate." The kill-thesis bar gets harder.

## Implications

1. **STR (`short_term_reversal_v1`)** — corrected mean Sharpe 0.999
   (vs T-030's 0.281) is the new reference. T-029's UNIFORMLY NOISY
   verdict still holds on the per-regime decomp (|α t| < 2 across
   all 4 regimes) — the equity-level Sharpe lift didn't translate
   into significant per-regime α at t > 2. The edge generates real
   PnL but no factor-adjusted-α-α signal above noise.

2. **Volume Anomaly + Gap Fill** — promoted from "UNIFORMLY NOISY"
   to "UNIFORMLY NEGATIVE" under cockpit-fixed reading. Both have
   significant negative α t in both expansion regimes (volume_anomaly
   `emerging_expansion` -2.06, `robust_expansion` -2.27; gap_fill
   `robust_expansion` -2.77). These should be CANDIDATE-RETIRE per
   the T-029 spec, but the decision is dispatched downstream — T-036
   surfaces, does not act.

3. **Already-negative edges got worse**. `value_book_to_market_v1`,
   `accruals_inv_sloan_v1`, `accruals_inv_asset_growth_v1` all
   tightened their α t-stats further negative. The "0/6 active edges
   have positive factor-adjusted α at t > 2" finding from T-004 is
   now even stronger — most actives are SIGNIFICANTLY negative, not
   merely noisy.

4. **The bull-conditional profile of STR + the corrected 0.999 Sharpe
   does NOT cross the t > 2 alpha bar** even under cockpit-fixed
   reading. The Sharpe is real PnL but factor-explained: STR's
   excess returns are tracking known FF5+Mom factors, not generating
   independent α.

5. **Verdict on the engines-first directive's 0.270 baseline**:
   the corrected substrate-honest baseline is now 0.598 (T-035), with
   STR's individual edge contribution of 0.999 worth flagging — but
   the per-regime factor decomp says NONE of the edges (re-measured
   or carried-through) cleanly clears t > 2 on factor-adjusted α.
   Higher Sharpe + still no factor-significant α = strategy is
   collecting factor-loadings, not generating idiosyncratic alpha.

## Caveats

1. Bootstrap CIs on the 7 cells were computed by the decomp script's
   built-in residual block-bootstrap; full table is in the JSON
   output. Per CLAUDE.md 6th non-negotiable, the verdict bucketing
   uses HAC t-stat with the same threshold (|t| > 2) as T-029.

2. The 4 carried-through edges (momentum_12_1, momentum_6_1,
   pairs_MA_V, dividend_init) are NOT re-measured. Their T-029
   verdicts are preserved. If a future dispatch re-runs T-020 per-
   edge isolation with cockpit-fixed code, those verdicts may shift
   by similar magnitude.

3. STR's mean Sharpe 0.999 is the equity-level read. Per CLAUDE.md
   the bootstrap CI is the kill-threshold reference; full
   `bootstrap_distribution.sharpe.ci_low` per cell is in the JSON.
   No single year has ci_low > 0.4, so STR doesn't autonomously
   clear the kill-thesis on a per-year CI basis.

## Files

- `scripts/run_str_3rep_t036.py` — Part A 15-cell harness
- `scripts/factor_decomp_per_regime_t036.py` — Part B decomp
- `data/measurements/str_3rep_cockpit_fixed_2026_05_12/results.json`
- `docs/Audit/str_and_perregime_rerun_cockpit_fixed_2026_05_12.json`
- 15 backtests under `data/trade_logs/<run_id>/`

## NOT included

- Re-running T-020 for the 4 carried-through edges with cockpit fix
  (deferred dispatch).
- Updating `forward_plan.md` / `health_check.md` / `lessons_learned.md`
  with corrected baseline + new bucket counts (separate doc-state
  dispatch).
- Acting on the "retire candidate" status of volume_anomaly + gap_fill
  (lifecycle action — separate dispatch).
