# Regime-Conditional Inter-Edge Correlation — 6 Active Edges

**Generated:** 2026-05-08
**Source:** trade-level realized PnL from 5 deterministic-harness multi-year runs (2021-2025), bucketed by regime_label (Engine E HMM).

## Bucketing

- **benign** = `robust_expansion ∪ emerging_expansion` (expansionary regimes)
- **adverse** = `cautious_decline ∪ market_turmoil ∪ transitional`
- **other** = unmapped or unknown

| bucket | trading days |
|---|---:|
| benign | 662 |
| adverse | 280 |
| other | 0 |

## Why this matters

An ensemble whose edges decorrelate ONLY in benign regimes is fake diversification. The crisis is exactly when correlations spike (everything sells off together) and you actually need uncorrelated bets. Splitting the inter-edge correlation matrix by regime tells us whether the 6-active set holds together when it matters.

## Unconditional (all-regime) correlation matrix — for reference

| edge | gap_fill_v1 | volume_anomaly_v1 | value_earnings_yield_v1 | value_book_to_market_v1 | accruals_inv_sloan_v1 | accruals_inv_asset_growth_v1 |
|---|---|---|---|---|---|---|
| `gap_fill_v1` | +1.000 | +0.156 | +0.168 | +0.066 | +0.072 | +0.185 |
| `volume_anomaly_v1` | +0.156 | +1.000 | +0.144 | +0.095 | +0.066 | +0.112 |
| `value_earnings_yield_v1` | +0.168 | +0.144 | +1.000 | +0.507 | +0.390 | +0.507 |
| `value_book_to_market_v1` | +0.066 | +0.095 | +0.507 | +1.000 | +0.399 | +0.358 |
| `accruals_inv_sloan_v1` | +0.072 | +0.066 | +0.390 | +0.399 | +1.000 | +0.297 |
| `accruals_inv_asset_growth_v1` | +0.185 | +0.112 | +0.507 | +0.358 | +0.297 | +1.000 |

## Benign-regime correlation matrix

| edge | gap_fill_v1 | volume_anomaly_v1 | value_earnings_yield_v1 | value_book_to_market_v1 | accruals_inv_sloan_v1 | accruals_inv_asset_growth_v1 |
|---|---|---|---|---|---|---|
| `gap_fill_v1` | +1.000 | -0.092 | +0.045 | -0.007 | -0.023 | +0.094 |
| `volume_anomaly_v1` | -0.092 | +1.000 | +0.186 | +0.092 | +0.089 | +0.111 |
| `value_earnings_yield_v1` | +0.045 | +0.186 | +1.000 | +0.337 | +0.320 | +0.400 |
| `value_book_to_market_v1` | -0.007 | +0.092 | +0.337 | +1.000 | +0.327 | +0.243 |
| `accruals_inv_sloan_v1` | -0.023 | +0.089 | +0.320 | +0.327 | +1.000 | +0.194 |
| `accruals_inv_asset_growth_v1` | +0.094 | +0.111 | +0.400 | +0.243 | +0.194 | +1.000 |

## Adverse-regime correlation matrix

| edge | gap_fill_v1 | volume_anomaly_v1 | value_earnings_yield_v1 | value_book_to_market_v1 | accruals_inv_sloan_v1 | accruals_inv_asset_growth_v1 |
|---|---|---|---|---|---|---|
| `gap_fill_v1` | +1.000 | +0.273 | +0.224 | +0.109 | +0.176 | +0.257 |
| `volume_anomaly_v1` | +0.273 | +1.000 | +0.117 | +0.101 | +0.049 | +0.116 |
| `value_earnings_yield_v1` | +0.224 | +0.117 | +1.000 | +0.642 | +0.534 | +0.611 |
| `value_book_to_market_v1` | +0.109 | +0.101 | +0.642 | +1.000 | +0.539 | +0.480 |
| `accruals_inv_sloan_v1` | +0.176 | +0.049 | +0.534 | +0.539 | +1.000 | +0.490 |
| `accruals_inv_asset_growth_v1` | +0.257 | +0.116 | +0.611 | +0.480 | +0.490 | +1.000 |

## Pairwise delta (adverse − benign)

Positive delta = correlation INCREASES under stress (bad — diversification disappears). Negative delta = correlation DROPS under stress (good — edges become more independent). Pairs are listed only when both buckets had enough data.

| pair | benign ρ | adverse ρ | Δ (adv−ben) |
|---|---:|---:|---:|
| `gap_fill_v1` × `volume_anomaly_v1` | -0.092 | +0.273 | +0.365 ↑ |
| `value_book_to_market_v1` × `value_earnings_yield_v1` | +0.337 | +0.642 | +0.305 ↑ |
| `accruals_inv_asset_growth_v1` × `accruals_inv_sloan_v1` | +0.194 | +0.490 | +0.296 ↑ |
| `accruals_inv_asset_growth_v1` × `value_book_to_market_v1` | +0.243 | +0.480 | +0.236 ↑ |
| `accruals_inv_sloan_v1` × `value_earnings_yield_v1` | +0.320 | +0.534 | +0.214 ↑ |
| `accruals_inv_sloan_v1` × `value_book_to_market_v1` | +0.327 | +0.539 | +0.213 ↑ |
| `accruals_inv_asset_growth_v1` × `value_earnings_yield_v1` | +0.400 | +0.611 | +0.211 ↑ |
| `accruals_inv_sloan_v1` × `gap_fill_v1` | -0.023 | +0.176 | +0.199 ↑ |
| `gap_fill_v1` × `value_earnings_yield_v1` | +0.045 | +0.224 | +0.180 ↑ |
| `accruals_inv_asset_growth_v1` × `gap_fill_v1` | +0.094 | +0.257 | +0.163 ↑ |
| `gap_fill_v1` × `value_book_to_market_v1` | -0.007 | +0.109 | +0.116 ↑ |
| `value_book_to_market_v1` × `volume_anomaly_v1` | +0.092 | +0.101 | +0.009 · |
| `accruals_inv_asset_growth_v1` × `volume_anomaly_v1` | +0.111 | +0.116 | +0.004 · |
| `accruals_inv_sloan_v1` × `volume_anomaly_v1` | +0.089 | +0.049 | -0.040 · |
| `value_earnings_yield_v1` × `volume_anomaly_v1` | +0.186 | +0.117 | -0.069 ↓ |

## Caveats

- Adverse-regime sample is small (Engine E's 5-state HMM rarely fires `market_turmoil`; per-day count is much smaller than benign). Per-pair correlation under adverse can be a 30-100 day estimate vs 600+ days for benign — wide CIs.
- The regime label is the LABEL AT ENTRY of the trade. PnL realizes later when the trade closes; if regime flipped between entry and exit, the per-day attribution may not perfectly match the regime that produced the day's actual mark-to-market.
- Daily realized PnL only — same caveat as the unconditional matrix. Intra-day signal correlation is not measured here.