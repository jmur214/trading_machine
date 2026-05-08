# Per-Edge Contribution — 6 Active Edges (2021-2025)

**Generated:** 2026-05-08
**Source:** trade-level realized PnL from the 5 deterministic-harness yearly runs.

## Why this matters

Inter-edge correlation tells us whether edges move together. This script tells us whether each edge is actually contributing to the bottom line — distinct from co-movement. An edge that's well-decorrelated from the rest but produces zero or negative PnL is pure noise; an edge that's correlated with the others but carries most of the realized PnL is the load-bearing alpha.

## Headline: total realized PnL by edge, 2021-2025

| edge | total PnL ($) | share of ensemble | trades | win rate |
|---|---:|---:|---:|---:|
| `volume_anomaly_v1` | +3,002 | +93.8% | 620 | 69.35% |
| `gap_fill_v1` | +1,065 | +33.3% | 402 | 61.94% |
| `accruals_inv_sloan_v1` | +377 | +11.8% | 760 | 42.89% |
| `value_book_to_market_v1` | +60 | +1.9% | 1259 | 47.34% |
| `accruals_inv_asset_growth_v1` | -111 | -3.5% | 518 | 47.49% |
| `value_earnings_yield_v1` | -1,192 | -37.2% | 1659 | 42.31% |
| **ensemble total** | +3,202 | 100.0% | — | — |

## Per-year PnL by edge

| edge | 2021 | 2022 | 2023 | 2024 | 2025 | total |
|---|---:|---:|---:|---:|---:|---:|
| `gap_fill_v1` | +136 | +187 | +127 | +434 | +182 | **+1,065** |
| `volume_anomaly_v1` | +454 | +860 | +75 | +858 | +756 | **+3,002** |
| `value_earnings_yield_v1` | -396 | -1,106 | +683 | -479 | +108 | **-1,192** |
| `value_book_to_market_v1` | +457 | -412 | +222 | -155 | -52 | **+60** |
| `accruals_inv_sloan_v1` | +379 | -596 | +350 | +228 | +17 | **+377** |
| `accruals_inv_asset_growth_v1` | -81 | -77 | +139 | +52 | -144 | **-111** |

## Per-year ensemble totals (across 6 active edges only)

| year | ensemble PnL ($) | n trades |
|---|---:|---:|
| 2021 | +947 | 928 |
| 2022 | -1,144 | 906 |
| 2023 | +1,596 | 1215 |
| 2024 | +937 | 1158 |
| 2025 | +866 | 1011 |

## Trade quality per edge (lifetime 2021-2025)

| edge | trades | win rate | avg winner ($) | avg loser ($) | best ($) | worst ($) |
|---|---:|---:|---:|---:|---:|---:|
| `gap_fill_v1` | 402 | 61.94% | +8.73 | -7.25 | +72.21 | -90.32 |
| `volume_anomaly_v1` | 620 | 69.35% | +10.34 | -7.60 | +96.85 | -114.57 |
| `value_earnings_yield_v1` | 1659 | 42.31% | +8.29 | -7.34 | +84.17 | -60.66 |
| `value_book_to_market_v1` | 1259 | 47.34% | +7.16 | -6.36 | +42.78 | -51.43 |
| `accruals_inv_sloan_v1` | 760 | 42.89% | +13.35 | -9.18 | +139.01 | -82.35 |
| `accruals_inv_asset_growth_v1` | 518 | 47.49% | +9.37 | -8.88 | +69.78 | -46.85 |

## Honest interpretation

- **Top contributor:** `volume_anomaly_v1` with +3,002 (+93.8% of ensemble).
- **Second:** `gap_fill_v1` with +1,065 (+33.3%).
- **Negative contributors:** 2 edge(s) — net DRAG on ensemble:
  - `accruals_inv_asset_growth_v1`: -111
  - `value_earnings_yield_v1`: -1,192
  - Investigate via the lifecycle gauntlet — these are candidates for pause/retire if the negative contribution is consistent across years.

## Caveats

- Contribution is realized $ PnL, not Sharpe. An edge with a small but consistently positive contribution may have a higher per-trade Sharpe than a high-PnL edge that takes on more variance to get there. Both views matter; this script is the $-attribution view.
- The 5 yearly runs were separate backtests with their own governor-state. Cross-year comparison is direction-correct but absolute numbers between years embed config + universe drift.
- Assumes the 6 ACTIVE_EDGES list is current. If edges have been retired or activated since this run, regenerate.