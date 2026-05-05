# Factor Decomposition Baseline

Generated: 2026-04-28T22:49:12
Trade log: `data/trade_logs/abf68c8e-1384-4db4-822c-d65894af70a1/trades.csv`
Factor model: FF5 (Mkt-RF, SMB, HML, RMW, CMA) + Momentum (Mom)
Edges analyzed: **9**

## What this measures

For each edge, regress its daily return stream on Fama-French 5
factors + momentum. The intercept (alpha) is the part not
explained by factor exposures. If intercept t-stat < 2 OR alpha
annualized < 2%, the edge is reproducible by holding cheap factor
ETFs (MTUM, IWM, VLUE, QUAL, USMV) and isn't real alpha.

**Phase 1 implication:** edges with significant intercept become
Tier-A standalone alphas; edges without become Tier-B features
(useful inputs to the meta-learner but not direct trade signals).

## Summary table (sorted by alpha t-stat, descending)

| Edge | N obs | Raw Sharpe | Alpha (annualized) | Alpha t-stat | R² | Verdict |
|------|-------|------------|--------------------|--------------|-----|---------|
| `herding_v1` | 116 | 7.10 | +10.1% | +4.49 | 0.10 | 🟢 alpha |
| `volume_anomaly_v1` | 248 | 5.46 | +6.1% | +4.36 | 0.01 | 🟢 alpha |
| `macro_credit_spread_v1` | 103 | 2.99 | +0.6% | +1.01 | 0.11 | 🟡 marginal |
| `gap_fill_v1` | 133 | 1.06 | +0.2% | +0.10 | 0.09 | 🔴 factor beta |
| `low_vol_factor_v1` | 96 | 2.68 | -0.7% | -0.78 | 0.07 | 🔴 factor beta |
| `pead_predrift_v1` | 85 | 0.84 | -0.5% | -1.33 | 0.08 | 🔴 factor beta |
| `atr_breakout_v1` | 501 | -1.25 | -3.8% | -3.28 | 0.06 | 🔴 factor beta |
| `macro_dollar_regime_v1` | 71 | 0.72 | -2.2% | -3.55 | 0.12 | 🔴 factor beta |
| `momentum_edge_v1` | 583 | -1.89 | -6.2% | -4.32 | 0.11 | 🔴 factor beta |

## Per-edge factor loadings

| Edge | MktRF | SMB | HML | RMW | CMA | Mom |
|------|----|----|----|----|----|----|
| `herding_v1` | -0.00 | -0.02 | +0.00 | -0.04 | +0.05 | -0.01 |
| `volume_anomaly_v1` | +0.00 | -0.01 | +0.00 | -0.01 | +0.01 | -0.00 |
| `macro_credit_spread_v1` | +0.00 | -0.00 | +0.00 | -0.00 | -0.00 | -0.01 |
| `gap_fill_v1` | +0.00 | -0.01 | +0.03 | -0.03 | -0.02 | -0.01 |
| `low_vol_factor_v1` | +0.01 | -0.00 | +0.01 | -0.00 | -0.01 | +0.00 |
| `pead_predrift_v1` | -0.00 | +0.00 | +0.00 | +0.00 | -0.00 | -0.00 |
| `atr_breakout_v1` | +0.02 | -0.02 | +0.00 | -0.00 | +0.03 | -0.00 |
| `macro_dollar_regime_v1` | -0.00 | -0.01 | +0.01 | -0.01 | -0.00 | -0.00 |
| `momentum_edge_v1` | +0.04 | -0.02 | +0.02 | -0.01 | +0.03 | -0.01 |

## Interpretation

- **2 edges produce real alpha** (t-stat > 2 AND alpha > 2% annualized).
- **1 edges are marginal** (1 < t-stat ≤ 2). Possibly real, possibly noise.
- **6 edges are factor beta in disguise** (t-stat ≤ 1). These can be
  reproduced by holding factor ETFs at lower cost.

**2 genuine alpha detected.** The Phase 1 meta-learner
has at least one real signal to work with, but the feature pool
is thin. Continue Phase 2 edge discovery in parallel with the
combiner build.

## Caveats

- Per-edge return stream is approximated by daily realized PnL /
  initial capital. Exits attributed via the post-fix `edge` field
  on each trade (not the legacy 'Unknown' bucket).
- Edges with fewer than 30 daily observations are excluded — the
  regression has too few degrees of freedom to be meaningful.
- This decomposition uses raw daily returns, not vol-adjusted or
  capital-efficiency-adjusted. An edge with low standalone alpha
  may still earn its spot in the portfolio for diversification or
  drawdown-control reasons that aren't captured here.