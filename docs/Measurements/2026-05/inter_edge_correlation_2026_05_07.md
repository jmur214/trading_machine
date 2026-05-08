# Inter-Edge Correlation Matrix — 6 Active Edges

**Generated:** 2026-05-07
**Source:** trade-level realized PnL aggregated daily across 2021-2025 from the most recent multi-year trade logs (5 single-year runs).
**Days with realized PnL:** 942
**Edges with realized PnL ≥1 day:** 6 of 6

## Why this matters
An ensemble of edges whose daily PnL is pairwise correlated >0.7 is one strategy with extra trades, not a diversified book. R1's audit-week-of punch-list flagged this as the cheapest sanity check on whether the 6 active edges are actually distinct, or are 6 names for the same exposure.

## Correlation matrix (Pearson, daily PnL, 2021-2025 union)

| edge | gap_fill_v1 | volume_anomaly_v1 | value_earnings_yield_v1 | value_book_to_market_v1 | accruals_inv_sloan_v1 | accruals_inv_asset_growth_v1 |
|---|---|---|---|---|---|---|
| `gap_fill_v1` | +1.000 | +0.156 | +0.168 | +0.066 | +0.072 | +0.185 |
| `volume_anomaly_v1` | +0.156 | +1.000 | +0.144 | +0.095 | +0.066 | +0.112 |
| `value_earnings_yield_v1` | +0.168 | +0.144 | +1.000 | +0.507 | +0.390 | +0.507 |
| `value_book_to_market_v1` | +0.066 | +0.095 | +0.507 | +1.000 | +0.399 | +0.358 |
| `accruals_inv_sloan_v1` | +0.072 | +0.066 | +0.390 | +0.399 | +1.000 | +0.297 |
| `accruals_inv_asset_growth_v1` | +0.185 | +0.112 | +0.507 | +0.358 | +0.297 | +1.000 |

## Interpretation

### HIGH (|ρ| ≥ 0.7) — none. Active set is not collinear at the daily level.

### MODERATE (0.4 ≤ |ρ| < 0.7) — overlap, but not collapse
- `value_earnings_yield_v1` vs `value_book_to_market_v1`: **+0.507**
- `value_earnings_yield_v1` vs `accruals_inv_asset_growth_v1`: **+0.507**

## Caveats

- Daily aggregation. Intra-day overlap (signal correlation) is not measured here; only realized PnL co-movement.
- Trade logs include paused-at-0.25× edges; this matrix filters to the 6 active edges only.
- Realized-only PnL means closed-trade days. Edges with very long hold horizons can show artificially low correlation if they exit on different cadences.
- 2021-2025 union; per-regime correlation may differ. Bear/bull regimes can converge or diverge correlations meaningfully.

## What's NOT here (yet)

- Signal-level correlation (raw edge scores per ticker per day) — would require re-running with edge-output capture; deferred.
- Regime-conditional correlation matrix — split by regime label in the trade log; future enhancement.