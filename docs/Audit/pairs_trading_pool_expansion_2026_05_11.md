---
task_id: T-2026-05-11-031
title: Pairs Trading Pool Expansion — Cointegration Screen
date: 2026-05-11
outcome: NO_SURVIVORS
---

# T-031 — Pairs Trading Pool Expansion

## Brief

T-017 surfaced MA/V as the only survivor of 12 candidate pairs. The
2026-05-11 threshold-calibration audit flagged `pairs_trading_MA_V_v1`
as the second-closest miss to t > 2 (α point +18%, t = 1.41 — limited
by n = 167 trades over 5 years). Brief asked for 6-10 new candidate
pairs screened through T-017's existing tooling. Survivors register as
new paused `pairs_trading_*_v1` edges, growing the pool's aggregate
trade count toward the n=300+ threshold where the factor decomp's
t-stat on MA/V's α might clear t > 2.

## Hard constraint observed

Brief: "DO NOT add new external dependencies." Of the 18 unique tickers
across the brief's 9 candidate pairs, only 7 had data in
`data/processed/`. The 11 missing tickers (XLF, KBE, XLE, XLY, XLP,
XLK, SOXX, XLV, IBB, XLI, XAR) are all sector ETFs that would have
required a fresh Alpaca/yfinance fetch. ETF data fetch is deferred to
a separate dispatch.

## Candidates screened

| Pair | Sector | Rationale |
|------|--------|-----------|
| CSCO / JNPR | Networking equipment | Same telco/enterprise demand cycle |
| AMAT / LRCX | Semi capital equipment | Same fab investment cycle |
| SPY / TLT   | Bond-equity divergence | Classic risk-on/risk-off pair |

## Thresholds (same as T-017)

- `coint_p ≤ 0.05` (Engle-Granger)
- `adf_p ≤ 0.05` (residual stationarity)
- `half_life ∈ [5, 30]` trading days
- β instability ≤ 30% (max/min |yearly β| - 1) × 100%
- In-sample window: 2021-01-01 → 2024-12-31

## Results

**0 / 3 survivors.**

### CSCO / JNPR — FAIL all gates

| Gate | Value | Threshold | Pass? |
|------|-------|-----------|-------|
| coint_p | 0.569 | ≤ 0.05 | ✗ |
| adf_p   | 0.322 | ≤ 0.05 | ✗ |
| half_life | 116.4d | ≤ 30d | ✗ |
| β instability | 400.3% | ≤ 30% | ✗ |

β path: [1.02, 0.75, -0.49, 0.22] — sign flip in 2023, meaning the
spread direction inverted mid-window. No structural relationship.

### AMAT / LRCX — FAIL by narrow margin

| Gate | Value | Threshold | Pass? |
|------|-------|-----------|-------|
| coint_p | 0.043 | ≤ 0.05 | ✓ |
| adf_p   | 0.011 | ≤ 0.05 | ✓ |
| half_life | 32.3d | ≤ 30d | ✗ (+7%) |
| β instability | 69.7% | ≤ 30% | ✗ |

Closest miss. Both p-value gates pass — there is a real cointegrating
relationship — but mean-reversion is slightly slower than the
liquidity-decay window allows, and β drifts more than 30% across
years. Spread persists but trades on a horizon that decays faster
than it reverts. Not deployable.

### SPY / TLT — FAIL all gates

| Gate | Value | Threshold | Pass? |
|------|-------|-----------|-------|
| coint_p | 0.705 | ≤ 0.05 | ✗ |
| adf_p   | 0.464 | ≤ 0.05 | ✗ |
| half_life | 165.9d | ≤ 30d | ✗ |
| β instability | 580.5% | ≤ 30% | ✗ |

β = -0.44 (negative, as expected for risk-on/risk-off) but the
relationship is unstable across the 2021-2024 regime sweep. The
brief noted "cointegration is regime-conditional and may fail
outside stress windows" — confirmed.

## Implications

1. **Pool stays at 1 active pair** (`pairs_trading_MA_V_v1`). The
   n=167 trade ceiling is unbroken. MA/V's α t-stat remains
   t = 1.41 < 2.0.

2. **Cointegration is rare.** This screen brings the project's
   cumulative tally to 1 survivor in 15 (~6.7%). T-017's 1/12 was
   not an undersample.

3. **ETF data gap is the binding constraint.** 6 of the brief's 9
   candidate pairs were unbuildable on disk. A separate dispatch
   to fetch sector ETFs (XLF, XLE, XLY, XLP, XLK, XLV, XLI plus
   sub-industry indices KBE, SOXX, IBB, XAR) would unlock the
   majority of the brief's hypothesis space.

4. **AMAT/LRCX is worth flagging.** Both p-values pass — a longer
   half-life threshold (40-60d) would admit it. Not recommended
   without separate measurement: a slower-reverting pair would
   need a wider z-score band to avoid whipsaw, which is a
   parameter change, not a pair add.

## Files

- `scripts/cointegration_pair_screen_t031.py` — screen wrapper
- `data/research/cointegrated_pairs_t031_2026_05_11.json` — full output
- Reuses `scripts.cointegration_pair_screen.screen_pair` from T-017

## Next steps

1. **No new edges registered** — nothing to ship.
2. ETF data fetch dispatched separately would unlock 6 more pairs.
3. The factor-decomp t-stat path on MA/V remains blocked at
   n = 167.
