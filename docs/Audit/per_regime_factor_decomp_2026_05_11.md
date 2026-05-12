# Per-Regime Factor Decomp — Rescue vs Broken (T-2026-05-11-029)

Generated: 2026-05-11 (T-2026-05-11-029 dispatch)
Spec source: inbox brief T-2026-05-11-029
Method: T-004's FF5+Mom HAC OLS decomposition, partitioned by `regime_label` per closed trade
Source: T-002 Arm 1 (6 active edges) + T-020 per-edge isolation (5 paused edges) trade logs

## Decision-grade summary

| Verdict bucket | Count | Edges |
|---|---:|---|
| INSUFFICIENT DATA | 1 | pairs_trading_MA_V_v1 |
| UNIFORMLY NEGATIVE | 5 | value_book_to_market_v1, accruals_inv_sloan_v1, value_earnings_yield_v1, accruals_inv_asset_growth_v1, momentum_6_1_v1 |
| UNIFORMLY NOISY | 4 | volume_anomaly_v1, gap_fill_v1, momentum_12_1_v1, short_term_reversal_v1 |
| UNIFORMLY POSITIVE | 1 | dividend_initiation_drift_v1 |

**Of 11 edges: 0 are REGIME-MISTUNED (rescue via Engine E), 5 are UNIFORMLY NEGATIVE (confirmed retire), 1 are UNIFORMLY POSITIVE (strong promote), 4 are UNIFORMLY NOISY (keep paused), 1 are INSUFFICIENT DATA (need more samples).**

## Methodology

For each edge, the closed-trade `pnl` column is partitioned by the `regime_label` recorded on that trade row, then summed per (regime, date) to build a per-regime daily PnL stream. The stream is divided by `initial_capital=$100,000` to produce a daily-return series (matches T-004's tier_classifier convention).

For each (edge, regime) cell with n_obs ≥ 30, OLS regression of (edge_return − RF) on FF5+Mom factors with Newey-West HAC standard errors (Politis auto-lag = floor(4 × (n/100)^(2/9))) yields α annualized + HAC t-stat + R² + factor betas. A residual moving-block bootstrap (block=lag+1, 1000 iters, seed=0) produces a 95% CI on α.

Regime taxonomy in the trade logs is the project's `macro_regime` classification: `emerging_expansion` (early-bull / risk-on recovery), `robust_expansion` (strong bull / risk-on peak), `cautious_decline` (risk-off / bearish). Three regimes, not the bull/bear/chop framing in the brief — documented as Open Q1 below.

## Per-(edge, regime) decomp table

| Edge | Regime | n_obs | α_annual | α 95% CI (boot) | t-stat (HAC) | R² | Verdict band |
|---|---|---:|---:|---|---:|---:|---|
| `volume_anomaly_v1` | cautious_decline | 81 | +0.0078 | [-0.0233, +0.0380] | +0.462 | 0.127 | noise |
| `volume_anomaly_v1` | emerging_expansion | 85 | +0.0121 | [-0.0200, +0.0530] | +0.662 | 0.090 | noise |
| `volume_anomaly_v1` | market_turmoil | 10 | — | — | — | — | INSUFFICIENT (n<30) |
| `volume_anomaly_v1` | robust_expansion | 92 | -0.0038 | [-0.0307, +0.0282] | -0.265 | 0.042 | noise |
| `gap_fill_v1` | cautious_decline | 67 | +0.0426 | [-0.0083, +0.1005] | +1.438 | 0.113 | noise |
| `gap_fill_v1` | emerging_expansion | 82 | -0.0121 | [-0.0408, +0.0416] | -0.815 | 0.104 | noise |
| `gap_fill_v1` | market_turmoil | 19 | — | — | — | — | INSUFFICIENT (n<30) |
| `gap_fill_v1` | robust_expansion | 75 | -0.0226 | [-0.0454, +0.0025] | -1.912 | 0.082 | noise |
| `value_book_to_market_v1` | cautious_decline | 153 | -0.0424 | [-0.0730, -0.0146] | -2.940 | 0.423 | **-neg** |
| `value_book_to_market_v1` | emerging_expansion | 230 | -0.0188 | [-0.0408, +0.0064] | -1.775 | 0.099 | noise |
| `value_book_to_market_v1` | market_turmoil | 26 | — | — | — | — | INSUFFICIENT (n<30) |
| `value_book_to_market_v1` | robust_expansion | 239 | -0.0046 | [-0.0281, +0.0221] | -0.364 | 0.118 | noise |
| `accruals_inv_sloan_v1` | cautious_decline | 164 | -0.0589 | [-0.1021, -0.0185] | -2.738 | 0.292 | **-neg** |
| `accruals_inv_sloan_v1` | emerging_expansion | 250 | -0.0211 | [-0.0374, -0.0040] | -2.556 | 0.101 | **-neg** |
| `accruals_inv_sloan_v1` | market_turmoil | 24 | — | — | — | — | INSUFFICIENT (n<30) |
| `accruals_inv_sloan_v1` | robust_expansion | 237 | -0.0301 | [-0.0546, -0.0109] | -2.716 | 0.107 | **-neg** |
| `value_earnings_yield_v1` | cautious_decline | 168 | -0.0447 | [-0.0805, -0.0107] | -2.794 | 0.347 | **-neg** |
| `value_earnings_yield_v1` | emerging_expansion | 245 | -0.0378 | [-0.0536, -0.0210] | -4.525 | 0.196 | **-neg** |
| `value_earnings_yield_v1` | market_turmoil | 28 | — | — | — | — | INSUFFICIENT (n<30) |
| `value_earnings_yield_v1` | robust_expansion | 248 | -0.0325 | [-0.0504, -0.0163] | -3.879 | 0.142 | **-neg** |
| `accruals_inv_asset_growth_v1` | cautious_decline | 114 | -0.0544 | [-0.0889, -0.0133] | -2.602 | 0.337 | **-neg** |
| `accruals_inv_asset_growth_v1` | emerging_expansion | 169 | -0.0254 | [-0.0436, -0.0094] | -2.815 | 0.123 | **-neg** |
| `accruals_inv_asset_growth_v1` | market_turmoil | 20 | — | — | — | — | INSUFFICIENT (n<30) |
| `accruals_inv_asset_growth_v1` | robust_expansion | 169 | -0.0318 | [-0.0475, -0.0167] | -4.076 | 0.193 | **-neg** |
| `momentum_12_1_v1` | cautious_decline | 269 | -0.0538 | [-0.1407, +0.0187] | -1.331 | 0.173 | noise |
| `momentum_12_1_v1` | emerging_expansion | 370 | +0.0422 | [-0.0356, +0.1079] | +1.181 | 0.197 | noise |
| `momentum_12_1_v1` | market_turmoil | 50 | -0.0365 | [-0.1549, +0.0715] | -0.552 | 0.343 | noise |
| `momentum_12_1_v1` | robust_expansion | 352 | +0.0223 | [-0.0213, +0.0624] | +1.009 | 0.206 | noise |
| `momentum_6_1_v1` | cautious_decline | 275 | -0.0701 | [-0.1391, -0.0176] | -2.286 | 0.298 | **-neg** |
| `momentum_6_1_v1` | emerging_expansion | 384 | +0.0104 | [-0.0557, +0.0710] | +0.321 | 0.094 | noise |
| `momentum_6_1_v1` | market_turmoil | 46 | -0.0890 | [-0.2075, +0.0189] | -1.632 | 0.196 | noise |
| `momentum_6_1_v1` | robust_expansion | 349 | +0.0013 | [-0.0588, +0.0507] | +0.049 | 0.203 | noise |
| `short_term_reversal_v1` | cautious_decline | 278 | -0.0051 | [-0.0677, +0.0526] | -0.172 | 0.207 | noise |
| `short_term_reversal_v1` | emerging_expansion | 366 | +0.0306 | [-0.0287, +0.0906] | +0.883 | 0.128 | noise |
| `short_term_reversal_v1` | market_turmoil | 40 | +0.1248 | [+0.0041, +0.2642] | +1.714 | 0.231 | noise |
| `short_term_reversal_v1` | robust_expansion | 335 | +0.0502 | [-0.0108, +0.1040] | +1.761 | 0.159 | noise |
| `pairs_trading_MA_V_v1` | cautious_decline | 16 | — | — | — | — | INSUFFICIENT (n<30) |
| `pairs_trading_MA_V_v1` | emerging_expansion | 27 | — | — | — | — | INSUFFICIENT (n<30) |
| `pairs_trading_MA_V_v1` | market_turmoil | 3 | — | — | — | — | INSUFFICIENT (n<30) |
| `pairs_trading_MA_V_v1` | robust_expansion | 16 | — | — | — | — | INSUFFICIENT (n<30) |
| `dividend_initiation_drift_v1` | cautious_decline | 34 | -0.1387 | [-0.7740, +0.7687] | -0.426 | 0.427 | noise |
| `dividend_initiation_drift_v1` | emerging_expansion | 56 | -0.3331 | [-0.9545, +0.2743] | -1.027 | 0.174 | noise |
| `dividend_initiation_drift_v1` | market_turmoil | 3 | — | — | — | — | INSUFFICIENT (n<30) |
| `dividend_initiation_drift_v1` | robust_expansion | 65 | +0.7326 | [+0.2931, +1.1540] | +2.988 | 0.235 | **+pos** |

## Per-edge verdicts

- `volume_anomaly_v1` (T-004 aggregate α t-stat: +0.83) — **UNIFORMLY NOISY — |α t|<2 across all 3 sufficient-data regime(s); no detectable signal. Keep paused; no factor-adjusted alpha. (note: insufficient data in ['market_turmoil'])**
- `gap_fill_v1` (T-004 aggregate α t-stat: -0.04) — **UNIFORMLY NOISY — |α t|<2 across all 3 sufficient-data regime(s); no detectable signal. Keep paused; no factor-adjusted alpha. (note: insufficient data in ['market_turmoil'])**
- `value_book_to_market_v1` (T-004 aggregate α t-stat: -2.60) — **UNIFORMLY NEGATIVE — α (t<-2) in ['cautious_decline']; no significantly-positive regime. CONFIRMED RETIRE CANDIDATE (stronger than T-004's aggregate finding). (note: insufficient data in ['market_turmoil'])**
- `accruals_inv_sloan_v1` (T-004 aggregate α t-stat: -4.08) — **UNIFORMLY NEGATIVE — α (t<-2) in ['robust_expansion', 'emerging_expansion', 'cautious_decline']; no significantly-positive regime. CONFIRMED RETIRE CANDIDATE (stronger than T-004's aggregate finding). (note: insufficient data in ['market_turmoil'])**
- `value_earnings_yield_v1` (T-004 aggregate α t-stat: -5.69) — **UNIFORMLY NEGATIVE — α (t<-2) in ['robust_expansion', 'emerging_expansion', 'cautious_decline']; no significantly-positive regime. CONFIRMED RETIRE CANDIDATE (stronger than T-004's aggregate finding). (note: insufficient data in ['market_turmoil'])**
- `accruals_inv_asset_growth_v1` (T-004 aggregate α t-stat: -5.12) — **UNIFORMLY NEGATIVE — α (t<-2) in ['robust_expansion', 'emerging_expansion', 'cautious_decline']; no significantly-positive regime. CONFIRMED RETIRE CANDIDATE (stronger than T-004's aggregate finding). (note: insufficient data in ['market_turmoil'])**
- `momentum_12_1_v1` (T-004 aggregate α t-stat: +0.36) — **UNIFORMLY NOISY — |α t|<2 across all 4 sufficient-data regime(s); no detectable signal. Keep paused; no factor-adjusted alpha.**
- `momentum_6_1_v1` (T-004 aggregate α t-stat: -1.01) — **UNIFORMLY NEGATIVE — α (t<-2) in ['cautious_decline']; no significantly-positive regime. CONFIRMED RETIRE CANDIDATE (stronger than T-004's aggregate finding).**
- `short_term_reversal_v1` (T-004 aggregate α t-stat: +1.76) — **UNIFORMLY NOISY — |α t|<2 across all 4 sufficient-data regime(s); no detectable signal. Keep paused; no factor-adjusted alpha.**
- `pairs_trading_MA_V_v1` — **INSUFFICIENT DATA — n_obs<30 in ALL regimes ['robust_expansion', 'emerging_expansion', 'cautious_decline', 'market_turmoil']; cannot bucket without more samples.**
- `dividend_initiation_drift_v1` — **UNIFORMLY POSITIVE — α (t>+2) in ['robust_expansion']; no significantly-negative regime. STRONG PROMOTE CANDIDATE (active or Sortino-vehicle dispatch). (note: insufficient data in ['market_turmoil'])**

## Forward-looking note on regime-conditional integration

If REGIME-MISTUNED edges emerge, the wiring to Engine E's regime classifier would require: (a) Engine A's signal_processor reading the current macro_regime label per bar, (b) per-edge `enabled_regimes` config field (or equivalent in `edges.yml`), (c) zeroing the edge's signal contribution on bars where regime is outside its enabled set. Engine B's sizing chain consumes the result transparently — no Engine B changes. This is roughly the same shape as T-002 Arm 2's HMM Variant C wire (which modulated `risk_scalar` globally per regime); per-edge regime gating is a finer-grained version of that. A separate propose-first dispatch would scope the wiring; this dispatch produces only the decision-grade evidence.

## Open questions surfaced during analysis

1. **Regime label taxonomy mismatch.** Brief mentioned bull/bear/chop; trade logs use macro_regime labels (emerging_expansion, robust_expansion, cautious_decline). Used the actual labels. Mapping: emerging_expansion ≈ early-bull, robust_expansion ≈ strong-bull, cautious_decline ≈ bear/risk-off.

2. **Sample size per (edge, regime) cell.** n_obs ranges shown in the table; cells with n_obs < 30 are marked INSUFFICIENT. HAC t-stat reliability decreases as n shrinks; for cells with n in [30, 60], the t > 2 threshold is harder to clear than at the aggregate n ≈ 1041 level.

3. **Trade-log aggregation across reps.** T-002 Arm 1 has 3 reps × 5 years; used rep-1 per year (matches T-004's convention; within-year reps are bitwise identical per T-002's determinism PASS). T-020 has 1 isolated backtest per (edge, year); all 25 used.

4. **Regime transition handling.** Each trade row carries the regime label that was active at fill time. Per-trade attribution to a single regime is the natural choice given the data shape; no special transition-bar handling needed.

5. **What constitutes 'favorable regime' for borderline cases.** Used strict t > +2 / t < -2 per spec. Cells with 0 < t < 2 (weakly positive) are reported but NOT classified as 'favorable enough to wire'. Director can override at review.
