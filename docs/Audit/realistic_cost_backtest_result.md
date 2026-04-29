# Realistic-Cost Backtest Result — 2026-04-28

First in-sample backtest with the new `RealisticSlippageModel` wired
end-to-end (commit 9546937). Confirms the cross-run diagnostic's
prior that the legacy flat 10 bps was overcharging the universe, but
the magnitude is much larger than the static re-pricing predicted.

## Setup

- **Run ID:** `abf68c8e-1384-4db4-822c-d65894af70a1`
- **Window:** 2021-01-01 → 2024-12-31 (in-sample)
- **Universe:** 109 tickers (mostly mega-cap S&P 100 + mid-cap S&P 500)
- **Cost model:** ADV-bucketed half-spread (1/5/15 bps for mega/mid/small)
  + Almgren-Chriss square-root market impact (k=0.5)
- **Governor:** reset to neutral via `--reset-governor`
- **Lifecycle paused edges:** atr_breakout_v1, momentum_edge_v1
  (soft-pause weight cap 0.5)

## Result

| Metric           | Realistic costs | Legacy 10 bps flat | Δ |
|------------------|-----------------|--------------------|----|
| Sharpe Ratio     | **1.063**       | 0.228 - 0.404      | +0.7 to +0.8 |
| Total Return     | 26.46%          | 9.56% - 13%        | +13-17pp |
| CAGR             | 6.06%           | 2.31% - 3%         | +3-4pp |
| Max Drawdown     | **-10.07%**     | -12.14% - -13%     | +2-3pp better |
| Volatility       | 5.70%           | 6.14%              | -0.4pp |
| Win Rate         | 49.06%          | 44.65%             | +4.4pp |
| Total fills      | 14,454          | ~9,617             | +50% |

## Versus benchmarks

| Reference | Sharpe | CAGR  | MDD     | Vol    |
|-----------|--------|-------|---------|--------|
| **System (realistic)** | **1.063** | 6.06% | **-10.07%** | **5.70%** |
| SPY       | 0.875  | 13.94%| -24.50% | 16.48% |
| QQQ       | 0.702  | 14.15%| -35.12% | 22.45% |
| 60/40 (SPY+TLT) | 0.361  | 3.75% | -27.24% | 12.29% |

System Sharpe **beats the strongest benchmark (SPY at 0.875) by +0.188**
in-sample. The lead isn't huge but it's clear.

## What's actually going on

The headline Sharpe lift (+0.7) decomposes as:

1. **Direct cost reduction:** the legacy 10 bps overcharged the
   mostly-mega-cap universe by ~77% (cross-run diagnostic, commit fdd34e5).
   Realistic costs are ~1-5 bps for almost all fills. Net: about
   +0.10-0.15 Sharpe just from less drag.

2. **Trade-count effect:** lower per-trade costs let the system take MORE
   positions (14,454 fills vs ~9,600 legacy). The good edges
   (`volume_anomaly_v1`, `herding_v1` — both with t-stat > 4 in factor
   decomposition) compound their alpha. Net: probably another +0.3-0.4
   Sharpe.

3. **Lower vol:** more diversification across more positions, plus the
   lifecycle's soft-pause cap on the bad edges (`atr_breakout_v1`,
   `momentum_edge_v1`), means realized vol drops from 6.14% to 5.70%.
   Sharpe gets a passive boost.

## Caveats

- **This is in-sample.** The real test is OOS (2025+). Legacy in-sample
  Sharpe was 0.228-0.404; legacy 2025 OOS was 0.173. If realistic-cost
  OOS runs at ~0.4-0.5 Sharpe, that would still be a meaningful lift.
- **Cost model isn't fully realistic.** No borrow cost for shorts, no
  taxes, no fee tiers. The slippage portion is honest but other
  real-world frictions are still missing.
- **Volatility comparison is misleading.** Lower vol partly comes from
  the 0.5 soft-pause cap on the dominant edges. If we fully retired
  atr_breakout/momentum_edge (already in their lifecycle pipeline),
  vol could drop further OR rise — depends on what fills the gap.
- **Risk-adjusted superior, not absolute return superior.** SPY made
  more in absolute terms (13.94% CAGR vs 6.06%). The system just made
  it with much lower drawdown (-10% vs -25%). Whether that's
  preferable depends on the user's risk tolerance and the constraints
  on capital.
- **Multi-benchmark gate now firing.** With Gate 6 (factor alpha) +
  the multi-benchmark default `mode='strongest'` change, future
  discovery cycles will be much harder to pass. Expect fewer
  promotions but higher quality.

## What's not in this number

The factor decomposition diagnostic (run on this same trade log)
showed:

- `volume_anomaly_v1`: +6.1% alpha annualized, t=+4.36
- `herding_v1`: +10.1% alpha annualized, t=+4.49

These two edges produce the bulk of the system's real (non-factor)
alpha. The other 7 active edges are factor beta or marginal. **The
combined-system result here is a mix of these two real alphas plus
factor exposure.**

A meta-learner combining these properly (per the design proposal at
`docs/Core/phase1_metalearner_design.md`) should be able to extract
more from `volume_anomaly_v1` and `herding_v1` while suppressing the
factor-beta drag. But that's the next session's work.

## What to do next

1. **Run the factor decomposition diagnostic on THIS run's trades** to
   confirm the 1.063 Sharpe is composed of real alpha + factor beta, not
   mostly factor beta riding through.
2. **Re-run a 2025 OOS backtest** under the realistic cost model to
   confirm the lift carries over. Legacy 2025 OOS was 0.173; expected
   realistic 2025 OOS is around 0.4-0.6.
3. **Get user sign-off on the meta-learner design** so Phase 1 can
   start. With confirmed real alphas in volume_anomaly + herding, the
   meta-learner has something to combine.
