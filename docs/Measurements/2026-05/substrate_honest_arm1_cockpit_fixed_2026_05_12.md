---
task_id: T-2026-05-12-035
title: Substrate-honest Arm 1 re-measurement with cockpit fix
date: 2026-05-12
outcome: 0.270 BASELINE LIFTED TO 0.598 — director's prediction REFUTED
---

# T-035 — Substrate-honest Arm 1, cockpit-fixed

## Brief

With T-034's cockpit metrics-pipeline fix landed, the canonical
substrate-honest baseline needs re-measurement. Director's prediction
in the inbox brief: "T-002 Arm 1's per-year cells had small MDDs so
the bug barely fires for those — expected shift ~0.02-0.05."

This dispatch re-runs T-002's Arm 1 grid (single-arm, no Arm 2 since
the question is the corrected baseline, not Arm-vs-Arm comparison)
and compares cell-by-cell against T-002.

## Setup

- Arm 1 edges (6): `gap_fill_v1`, `volume_anomaly_v1`,
  `value_earnings_yield_v1`, `value_book_to_market_v1`,
  `accruals_inv_sloan_v1`, `accruals_inv_asset_growth_v1`
- Universe: F6 historical S&P 500 union (substrate-honest,
  post-missing-CSV closure)
- Window: 2021-2025, 3 reps per year = 15 backtests
- Mode: journal-mode (`apply_journal_at_end=True`),
  `reset_governor=True`, `discover=False`, full 6-edge active set
  inside `isolated()` context
- HMM Variant C: OFF
- Realistic costs ON, wash-sale OFF, lt-hold OFF (identical to T-002)
- Wall time: 4h 28m (avg 18 min/cell)

## Headline

**Corrected mean Arm 1 Sharpe = 0.598** (vs T-002 reported 0.270;
**Δ = +0.328**). The director's "barely fires" prediction is
**REFUTED** — the bug had material impact on Arm 1's per-year cells
across both winning and losing years.

## Per-year comparison vs T-002

| Year | T-002 reported | T-035 corrected | Δ | CI₉₅ (T-035) | p(Sharpe>0) |
|------|----------------|-----------------|---|--------------|-------------|
| 2021 | 0.413 | **1.791** | +1.378 | [0.014, 3.345] | 0.97 |
| 2022 | 0.116 | **0.294** | +0.178 | [-2.220, 2.193] | 0.60 |
| 2023 | 0.261 | **1.221** | +0.960 | [-0.788, 2.956] | 0.90 |
| 2024 | 0.236 | **-0.613** | -0.849 | [-2.437, 1.653] | 0.31 |
| 2025 | 0.325 | **0.297** | -0.028 | [-1.323, 3.037] | 0.65 |
| mean | 0.270 | **0.598** | +0.328 | — | — |

CIs are 95% block-bootstrap (Künsch 1989, Politis-White block length)
from `MetricsEngine.bootstrap_distribution`, per CLAUDE.md
non-negotiable.

## Determinism

| Year | Reps | Unique `trades_canon_md5` |
|------|------|----------------------------|
| 2021 | 3 | **2** (reps 1+2 vs rep 3) |
| 2022 | 3 | 1 |
| 2023 | 3 | 1 |
| 2024 | 3 | 1 |
| 2025 | 3 | 1 |

14/15 cells perfectly deterministic; 2021 rep 3 carries the same
pre-existing logger flush race surfaced in T-034 (Sharpe is identical
to 3 decimals across reps; the trade ledger differs in row-count by
the same race-induced duplicates documented in T-034). Resolving the
race is dispatched separately.

## Mechanism — why winning years also shifted

In T-034 I claimed winning years happen to be correct by coincidence
because peak_equity ≈ equity when the strategy advances. **That was
wrong.** peak_equity is monotone non-decreasing; equity fluctuates.
During intra-year drawdowns — even within a net-winning year —
real equity dips below peak_equity. The pre-T-034 metrics pipeline
was reading peak_equity (which has lower variance because it never
falls), inflating Sharpe in winning years systematically.

Worked example, 2021:
- T-002 read peak_equity series — Sharpe 0.413
- T-035 reads real equity series — Sharpe 1.791
- The underlying portfolio behavior is unchanged; only the metric
  read differs

2024 inverts: a net-losing year (-2.68% CAGR) where peak_equity
read masked the loss → T-002 reported 0.236; T-035 corrected to
-0.613. Same direction as the STR 2022 finding in T-030.

## Implications

1. **The 0.598 number is the new canonical baseline**, not 0.270.
   Forward planning / kill-thesis decisions should reference this.

2. **The bug's contamination was system-wide and bi-directional**:
   - Winning years: inflated (reading lower-variance peak series
     instead of fluctuating real equity)
   - Losing years: zeroed-out or muted (peak_equity stays at $100K
     while real equity falls below)
   Director's prediction "barely fires in small-MDD cells" was
   informed by my earlier T-034 audit's "winning years correct by
   coincidence" claim, which T-035 refutes.

3. **The 0.598 includes the CI floor caveat**. Mean of the 5
   per-year CI₉₅ lower bounds = -1.351, which is the relevant kill
   threshold check. **No single year has `ci_low > 0`** — even the
   1.791 year has ci_low = 0.014 (barely positive). The mean Sharpe
   is positive but the system is far from clearing CLAUDE.md's "Sharpe
   < 0.4 net of all costs" kill thesis on a single-year-CI basis.
   For mean-of-means, pooling the 5 years into one 1260-day series
   would give a tighter mean-CI; that pooled computation is out of
   T-035 scope and dispatched separately.

4. **Sharpe contributions are split across regimes**: 2021 (strong
   bull) and 2023 (recovery) dominate. 2024's -0.613 reveals real
   regime-conditional fragility that the buggy 0.236 had masked.
   Strategy is bull-conditional, with material 2024-style risk.

5. **Going forward** — every prior Sharpe-bearing audit should be
   re-measured. T-002 Arm 2, T-019 paused-tier-inert, T-029 per-regime
   decomp, T-020 per-edge isolation, F6 multi-year — all suspect.
   T-036 takes the highest-priority of those (STR + T-029 per-regime
   adverse cells); the rest can be dispatched in a follow-on round.

## Files

- `scripts/run_substrate_arm1_t035.py` — wrapper around T-002's
  `run_substrate_arms._execute_grid`
- `data/measurements/substrate_arm1_cockpit_fixed_2026_05_12/arm1_results.json`
- `docs/Measurements/2026-05/substrate_honest_arm1_cockpit_fixed_2026_05_12.json`
- 15 backtests under `data/trade_logs/<run_id>/`

## NOT included

- Arm 2 re-measurement (single-arm scope per brief).
- Pooled 5-year mean-of-means CI (separate dispatch).
- Per-edge attribution under cockpit-fixed (T-036 handles STR;
  remaining 5 active edges deferred).
- 2021 rep 3 md5 divergence root-cause (pre-existing logger race,
  separate dispatch).
