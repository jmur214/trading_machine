# C-collapses-1.25 — Factor Decomp Verdict (T-2026-05-08-004)

Generated: 2026-05-09T06:15:40
Spec: `docs/Measurements/2026-05/spec_c_collapses_1_25_factor_decomp_2026_05_08.md`
Source: T-002 Arm 1 trade logs (substrate-honest, HMM OFF, 6 actives)

## Inputs + method

Trade-log run_ids used (rep 1 of each year — reps 2/3 are bitwise-identical):
- 2021: `191c14ba-3e8d-4f7f-ae08-8b24bf54dec0`
- 2022: `85ae17d9-a7b9-473b-933a-94dc0c681fcc`
- 2023: `a23ce948-9fd0-43ef-84c6-dc6aaa7653ca`
- 2024: `a1591104-7c2b-428c-a02a-a1fa712fe569`
- 2025: `a3aac752-6daa-487a-a3e5-2f1e4d81d319`

- Per-edge **closure-day count** (matches `tier_classifier.py`'s `_compute_decomps_from_trades`):
  - `volume_anomaly_v1`: 268 closure-days
  - `gap_fill_v1`: 243 closure-days
  - `value_book_to_market_v1`: 648 closure-days
  - `accruals_inv_sloan_v1`: 675 closure-days
  - `value_earnings_yield_v1`: 689 closure-days
  - `accruals_inv_asset_growth_v1`: 472 closure-days

- **Per-edge attribution convention** (matches `engines/engine_a_alpha/tier_classifier.py`): closed-trade `pnl` summed by `edge_id` per closure-date, divided by `initial_capital = $100,000` (constant — NOT prior-day equity). Days **without** a closure for a given edge are EXCLUDED from that edge's regression (sparse-event series, not zero-filled). This is the project's standard tier-classification methodology.
- Regression: OLS of (edge_return − RF) on FF5+Mom factors, with **Newey-West HAC** standard errors (hand-rolled; `statsmodels` not available and the spec forbids fetching fresh deps).
- Newey-West lag (Politis auto, per-edge): floor(4 × (T/100)^(2/9)) where T = that edge's closure-day count.
- α CI (annualized): both **analytic** (z=1.96 × HAC SE × 252) and **bootstrap** (residual moving-block bootstrap, block = lag+1, 1000 iters, seed=0).

## Verdict (primary question — `volume_anomaly_v1`)

GENUINELY NOISY (|t|≤2 and R²<0.3). Alpha not detectable on substrate-honest universe; statistical power not there. Don't flip flags from substrate measurement.

## Per-edge factor decomp

| Edge | Annualized α | α 95% CI (HAC) | α 95% CI (bootstrap) | t-stat (α, HAC) | R² | Raw Sharpe | t > 2 ? | Notes |
|---|---:|---|---|---:|---:|---:|---|---|
| `volume_anomaly_v1` | +0.0080 | [-0.0110, +0.0271] | [-0.0126, +0.0289] | +0.827 | 0.040 | +5.256 | no | **Primary** — load-bearing edge |
| `gap_fill_v1` | -0.0005 | [-0.0244, +0.0233] | [-0.0230, +0.0258] | -0.042 | 0.089 | +3.000 | no |  |
| `value_book_to_market_v1` | -0.0220 | [-0.0385, -0.0054] | [-0.0398, -0.0051] | -2.603 | 0.163 | +0.767 | **YES** |  |
| `accruals_inv_sloan_v1` | -0.0354 | [-0.0524, -0.0184] | [-0.0551, -0.0206] | -4.077 | 0.128 | -0.536 | **YES** |  |
| `value_earnings_yield_v1` | -0.0397 | [-0.0533, -0.0260] | [-0.0547, -0.0270] | -5.689 | 0.196 | -0.847 | **YES** | Net-drag edge per per_edge_contribution |
| `accruals_inv_asset_growth_v1` | -0.0374 | [-0.0517, -0.0231] | [-0.0536, -0.0233] | -5.120 | 0.168 | -0.390 | **YES** | Net-drag edge per per_edge_contribution |

## Factor exposures (β + HAC t-stat per factor)

| Edge | MktRF β | MktRF t | SMB β | SMB t | HML β | HML t | RMW β | RMW t | CMA β | CMA t | Mom β | Mom t |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `volume_anomaly_v1` | +0.008 | +2.53 | -0.003 | -0.60 | +0.003 | +0.86 | -0.001 | -0.17 | +0.007 | +1.32 | -0.003 | -1.05 |
| `gap_fill_v1` | -0.010 | -0.81 | +0.004 | +0.43 | +0.020 | +2.00 | -0.017 | -1.57 | -0.005 | -0.29 | -0.004 | -0.55 |
| `value_book_to_market_v1` | +0.020 | +4.13 | -0.005 | -1.09 | +0.018 | +3.79 | -0.008 | -1.42 | +0.011 | +1.55 | -0.006 | -1.92 |
| `accruals_inv_sloan_v1` | +0.019 | +3.94 | -0.002 | -0.32 | +0.010 | +1.82 | -0.013 | -2.19 | +0.000 | +0.00 | -0.003 | -0.86 |
| `value_earnings_yield_v1` | +0.022 | +4.59 | -0.000 | -0.10 | +0.020 | +4.75 | -0.005 | -0.94 | +0.002 | +0.43 | -0.006 | -2.13 |
| `accruals_inv_asset_growth_v1` | +0.015 | +3.77 | -0.004 | -0.86 | +0.016 | +2.80 | -0.018 | -2.81 | +0.005 | +0.72 | -0.004 | -1.44 |

## Survival summary

- Edges with |t(α)| > 2 (HAC): **4 of 6**
- t > 2, α < 0 (anti-factor):
  - `value_book_to_market_v1` (α annual -2.198%, t=-2.60)
  - `accruals_inv_sloan_v1` (α annual -3.536%, t=-4.08)
  - `value_earnings_yield_v1` (α annual -3.966%, t=-5.69)
  - `accruals_inv_asset_growth_v1` (α annual -3.741%, t=-5.12)

## Caveats

- **Per-edge attribution is ~10–15% noisy.** Trades are tagged with the dominant edge_id at entry per `signal_processor`, but real ensemble interactions are ignored. A trade entered on multi-edge consensus with all-credit assigned to one edge double-counts in this attribution.
- **5-year sample is short for HAC inference.** Politis auto-lag is the project default but residual structure may not be stable across regime shifts.
- **`accruals_inv_sloan_v1` is in the active 6 but was a $-PnL drag in T-002 Arm 1** (-$1,623; spec listed only the larger 2 drags). Whether it's factor-adjusted-real or factor-disguised here is a fresh data point relative to the spec drop-list.
