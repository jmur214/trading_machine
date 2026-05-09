# Substrate-Honest Re-Measurement — 2026-05-08

Generated: 2026-05-09T05:38:48
Spec: `docs/Measurements/2026-05/spec_substrate_honest_remeasurement_2026_05_08.md`
Task: T-2026-05-08-002

Window 2021-2025, F6 historical S&P 500 universe with missing-CSV closure (d5af02e), 
3 reps × 5 yearly runs per arm, journal-mode (apply_journal_at_end=True), 
realistic costs ON, wash-sale OFF, lt-hold OFF.

Post-fix verification: earnings_vol tz regression closed (4b7a14e). 
yfinance tz audit (T-001) cleared the other 4 edges (no fixes needed).

## Verdict bucket

Arm 1 mean Sharpe 0.2702 → COLLAPSED (<0.5) — closure didn't recover prior universe-aware result. Arm 2 mean Sharpe 0.2940, Δ=+0.0238 → NEUTRAL (0<=Δ<+0.2) — pruning + HMM didn't materially help. Contingent 2x2 decomposition: do NOT fire.

## Cross-arm comparison

| Metric | Arm 1 (6 actives, HMM OFF) | Arm 2 (4 actives, HMM ON minimal_c) | Δ (A2 − A1) |
|---|---:|---:|---:|
| Mean Sharpe | +0.2702 | +0.2940 | +0.0238 |
| Mean Sortino | — | — | — |
| Mean MDD (%) | -4.10 | -5.86 | -1.7640 |
| Mean Win-Rate (%) | 49.44 | 49.25 | -0.1960 |
| Bootstrap Sharpe 95% CI | [-0.383, +0.771] | [-0.270, +0.761] | — |
| Bootstrap Sortino 95% CI | [-0.391, +0.852] | [-0.396, +1.125] | — |

## Arm 1 detail

### Per-year Sharpe

| Year | Reps | Sharpe (mean) | Sharpe range | Canon md5 unique | Determinism |
|---|---|---:|---:|---:|---|
| 2021 | 3 | 0.4130 | 0.0000 | 1/3 | PASS (bitwise) |
| 2022 | 3 | 0.1160 | 0.0000 | 1/3 | PASS (bitwise) |
| 2023 | 3 | 0.2610 | 0.0000 | 1/3 | PASS (bitwise) |
| 2024 | 3 | 0.2360 | 0.0000 | 1/3 | PASS (bitwise) |
| 2025 | 3 | 0.3250 | 0.0000 | 1/3 | PASS (bitwise) |

### Bootstrap distribution (1000 iters, block-bootstrap)

- N daily obs: 1250
- Sharpe point estimate: +0.2620; mean +0.1983; 95% CI [-0.3829, +0.7707]; P(Sharpe>0) 0.735
- Sortino point estimate: +0.2796; mean +0.2150; 95% CI [-0.3909, +0.8518]; P(Sortino>0) 0.735

### Per-edge realized PnL contribution (2021-2025)

| edge | total PnL ($) | trades | win rate |
|---|---:|---:|---:|
| `gap_fill_v1` | +3,409 | 433 | 69.28% |
| `volume_anomaly_v1` | +4,527 | 542 | 70.48% |
| `value_earnings_yield_v1` | -2,352 | 2401 | 45.02% |
| `value_book_to_market_v1` | +2,082 | 1674 | 49.88% |
| `accruals_inv_sloan_v1` | -1,623 | 1858 | 45.16% |
| `accruals_inv_asset_growth_v1` | -658 | 994 | 48.69% |

### Inter-edge correlation (Pearson, daily PnL)

| edge | gap_fill_v1 | volume_anomaly_v1 | value_earnings_yield_v1 | value_book_to_market_v1 | accruals_inv_sloan_v1 | accruals_inv_asset_growth_v1 |
|---|---|---|---|---|---|---|
| `gap_fill_v1` | +1.000 | +0.074 | +0.156 | +0.120 | +0.164 | +0.088 |
| `volume_anomaly_v1` | +0.074 | +1.000 | +0.232 | +0.225 | +0.263 | +0.171 |
| `value_earnings_yield_v1` | +0.156 | +0.232 | +1.000 | +0.602 | +0.673 | +0.661 |
| `value_book_to_market_v1` | +0.120 | +0.225 | +0.602 | +1.000 | +0.586 | +0.501 |
| `accruals_inv_sloan_v1` | +0.164 | +0.263 | +0.673 | +0.586 | +1.000 | +0.611 |
| `accruals_inv_asset_growth_v1` | +0.088 | +0.171 | +0.661 | +0.501 | +0.611 | +1.000 |

HIGH (|ρ|≥0.7): none.
MODERATE (0.4≤|ρ|<0.7):
- `value_earnings_yield_v1` vs `value_book_to_market_v1`: +0.602
- `value_earnings_yield_v1` vs `accruals_inv_sloan_v1`: +0.673
- `value_earnings_yield_v1` vs `accruals_inv_asset_growth_v1`: +0.661
- `value_book_to_market_v1` vs `accruals_inv_sloan_v1`: +0.586
- `value_book_to_market_v1` vs `accruals_inv_asset_growth_v1`: +0.501
- `accruals_inv_sloan_v1` vs `accruals_inv_asset_growth_v1`: +0.611

## Arm 2 detail

### Per-year Sharpe

| Year | Reps | Sharpe (mean) | Sharpe range | Canon md5 unique | Determinism |
|---|---|---:|---:|---:|---|
| 2021 | 3 | 0.4160 | 0.0000 | 1/3 | PASS (bitwise) |
| 2022 | 3 | 0.2820 | 0.0000 | 1/3 | PASS (bitwise) |
| 2023 | 3 | 0.3480 | 0.0000 | 1/3 | PASS (bitwise) |
| 2024 | 3 | 0.2150 | 0.0000 | 1/3 | PASS (bitwise) |
| 2025 | 3 | 0.2090 | 0.0000 | 1/3 | PASS (bitwise) |

### Bootstrap distribution (1000 iters, block-bootstrap)

- N daily obs: 1250
- Sharpe point estimate: +0.2996; mean +0.2387; 95% CI [-0.2700, +0.7614]; P(Sharpe>0) 0.788
- Sortino point estimate: +0.4418; mean +0.3531; 95% CI [-0.3956, +1.1247]; P(Sortino>0) 0.788

### Per-edge realized PnL contribution (2021-2025)

| edge | total PnL ($) | trades | win rate |
|---|---:|---:|---:|
| `gap_fill_v1` | +1,233 | 542 | 41.88% |
| `volume_anomaly_v1` | +6,350 | 497 | 62.37% |
| `value_book_to_market_v1` | +3,685 | 2675 | 49.57% |
| `accruals_inv_sloan_v1` | +2,563 | 2256 | 49.07% |

### Inter-edge correlation (Pearson, daily PnL)

| edge | gap_fill_v1 | volume_anomaly_v1 | value_book_to_market_v1 | accruals_inv_sloan_v1 |
|---|---|---|---|---|
| `gap_fill_v1` | +1.000 | +0.084 | +0.161 | +0.150 |
| `volume_anomaly_v1` | +0.084 | +1.000 | +0.247 | +0.142 |
| `value_book_to_market_v1` | +0.161 | +0.247 | +1.000 | +0.435 |
| `accruals_inv_sloan_v1` | +0.150 | +0.142 | +0.435 | +1.000 |

HIGH (|ρ|≥0.7): none.
MODERATE (0.4≤|ρ|<0.7):
- `value_book_to_market_v1` vs `accruals_inv_sloan_v1`: +0.435

## Run UUIDs (for downstream tasks)

**Arm 1**:
- year=2021 rep=1: `191c14ba-3e8d-4f7f-ae08-8b24bf54dec0`
- year=2021 rep=2: `776b05ce-02c3-4de8-829e-545084455c19`
- year=2021 rep=3: `36f8a4bd-8090-444a-9b49-5dde79cf94c1`
- year=2022 rep=1: `85ae17d9-a7b9-473b-933a-94dc0c681fcc`
- year=2022 rep=2: `0ae93b1a-62f4-49ed-9fb6-f5a6f20b858d`
- year=2022 rep=3: `46c62a9e-3180-4d60-a6e9-aeb9f810bb6d`
- year=2023 rep=1: `a23ce948-9fd0-43ef-84c6-dc6aaa7653ca`
- year=2023 rep=2: `0c4a5f98-b7fd-42f2-96a5-2c4424940fad`
- year=2023 rep=3: `0f9f2a60-9202-414a-943f-ac36749601b9`
- year=2024 rep=1: `a1591104-7c2b-428c-a02a-a1fa712fe569`
- year=2024 rep=2: `c2610dfc-4d35-494f-9dde-9e7b19737918`
- year=2024 rep=3: `6a2cdeb8-1952-49f2-ad7d-ab2105cc1de8`
- year=2025 rep=1: `a3aac752-6daa-487a-a3e5-2f1e4d81d319`
- year=2025 rep=2: `e6a99800-612a-4323-9684-dc9055c6f56d`
- year=2025 rep=3: `78054253-84a9-4d88-8b65-578e859a71c0`

**Arm 2**:
- year=2021 rep=1: `c5d6085c-7dbe-4503-b860-a14ba048aece`
- year=2021 rep=2: `a43eb10c-b312-49be-9820-e07639f69396`
- year=2021 rep=3: `1ec61075-367b-448e-92f8-d539c43982c4`
- year=2022 rep=1: `38c947fc-daa1-4bad-a73a-0223240dd46a`
- year=2022 rep=2: `fa74ba5c-a78c-4094-b78b-947e17dffe63`
- year=2022 rep=3: `8c076024-2f4a-4698-aae2-2816d869082e`
- year=2023 rep=1: `11cc07e1-bcb7-4993-b2dc-eb049ed45211`
- year=2023 rep=2: `d7986a1b-c31e-4d83-88f8-63279e44ba55`
- year=2023 rep=3: `16203090-95d8-4730-8946-a4ce0401bfe2`
- year=2024 rep=1: `922502fe-818f-4453-aab6-11dd814cdeec`
- year=2024 rep=2: `77eadbc6-3b64-4733-a1cb-eea61ae849a1`
- year=2024 rep=3: `2181ed04-d8c9-44fb-800a-253ff7ee6a83`
- year=2025 rep=1: `413ef97f-1d77-4c54-a740-a1a76399de5b`
- year=2025 rep=2: `25e84816-2bbc-4253-bb89-df9cf97bccfb`
- year=2025 rep=3: `629e408d-9cb8-4fc4-a0aa-988632a3516c`
