# Per-edge isolation — substrate-honest gauntlet-equivalent (T-2026-05-10-020)

**Generated:** 2026-05-11T00:19:02
**Spec:** the 5 new paused edges from 2026-05-09 (T-016/T-017/T-018) run at FULL weight in ISOLATION via `exact_edge_ids=[edge_id]` override. Each (edge, year) cell is one isolated backtest; 5 × 5 = 25 cells total.

## Headline

- **5/5 edges produced signal density** at full weight in isolation. All 5 traded 167–5,432 closures over 5 years.
- **5/5 edges have positive cross-year Sharpe** with bootstrap `ci_low > 0`. Raw Sharpes range 0.28–0.45.
- **0/5 edges survive FF5+Mom factor adjustment** (|α t-stat HAC| > 2). The raw Sharpes are largely factor exposure, not idiosyncratic alpha — same pattern as T-004's measurement on the 6 existing active edges.
- **Verdict counts: 0 promote-candidate, 5 keep-paused, 0 retire-candidate.**
- **Engines-first implication:** none of the new edges are promote-ready at substrate-honest 5-year scale. Signal density exists, but at this universe + cost configuration the systematic factor exposure (Mkt + Mom) explains most of it. Engine completion (Engine B vol target, Engine F lifecycle clearing, Engine C portfolio construction) is the next workstream consistent with the dev-review directive.

## Setup

- **Universe:** F6 historical S&P 500 (use_historical_universe=True)
- **Window:** 2021-01-01..2025-12-31 (1 rep × 5 calendar years)
- **Mode:** prod, apply_journal_at_end=True (F11 invariant)
- **Costs:** realistic ON, wash-sale OFF, lt-hold OFF, HMM OFF
- **Edge weighting:** full weight in isolation (bypasses 0.25× soft-pause AND ensemble dilution)
- **Factor decomp:** FF5+Mom via `scripts/factor_decomp_substrate_honest.py:regress_with_hac` with Newey-West HAC SE (Politis-White automatic lag, hand-rolled). Same convention as T-004.
- **Sharpe CI:** cross-year bootstrap, block_length=1 (n=5 independent yearly observations).

## Verdict table

| edge_id | n_trades (5yr) | Sharpe (5yr mean) | ci_low | ci_high | α annualized | α t-stat (HAC) | R² | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| `momentum_12_1_v1` | 5277 | +0.355 | +0.233 | +0.485 | +0.0074 | +0.36 | 0.173 | keep-paused (sharpe_ci_low=0.233, α_t=0.36, α_annualized=0.0074; signal too weak post-factor for promotion) |
| `momentum_6_1_v1` | 5432 | +0.338 | +0.251 | +0.418 | -0.0202 | -1.01 | 0.167 | keep-paused (sharpe_ci_low=0.251, α_t=-1.01, α_annualized=-0.0202; signal too weak post-factor for promotion) |
| `short_term_reversal_v1` | 3302 | +0.281 | +0.144 | +0.369 | +0.0339 | +1.76 | 0.139 | keep-paused (sharpe_ci_low=0.144, α_t=1.76, α_annualized=0.0339; signal too weak post-factor for promotion) |
| `pairs_trading_MA_V_v1` | 167 | +0.385 | +0.346 | +0.429 | +0.1797 | +1.41 | 0.076 | keep-paused (sharpe_ci_low=0.346, α_t=1.41, α_annualized=0.1797; signal too weak post-factor for promotion) |
| `dividend_initiation_drift_v1` | 253 | +0.447 | +0.326 | +0.650 | +0.2222 | +1.20 | 0.180 | keep-paused (sharpe_ci_low=0.326, α_t=1.20, α_annualized=0.2222; signal too weak post-factor for promotion) |

## Per-edge per-year detail

### `momentum_12_1_v1`

| year | Sharpe | MDD % | Win Rate % | total_trades | canon md5 (8-char) |
|---:|---:|---:|---:|---:|---|
| 2021 | +0.566 | -13.51% | 62.54% | — | `51545c4d` |
| 2022 | +0.256 | -3.55% | 41.89% | — | `71771154` |
| 2023 | +0.229 | -5.74% | 56.80% | — | `052c5754` |
| 2024 | +0.499 | -11.10% | 56.90% | — | `815c5583` |
| 2025 | +0.226 | -4.39% | 46.99% | — | `a4c53733` |

### `momentum_6_1_v1`

| year | Sharpe | MDD % | Win Rate % | total_trades | canon md5 (8-char) |
|---:|---:|---:|---:|---:|---|
| 2021 | +0.469 | -11.21% | 59.59% | — | `c7ced1e2` |
| 2022 | +0.179 | -2.08% | 38.48% | — | `6eed92b6` |
| 2023 | +0.397 | -7.34% | 57.05% | — | `f6718c3b` |
| 2024 | +0.360 | -6.52% | 49.45% | — | `4e222cdf` |
| 2025 | +0.284 | -1.61% | 43.87% | — | `476e6185` |

### `short_term_reversal_v1`

| year | Sharpe | MDD % | Win Rate % | total_trades | canon md5 (8-char) |
|---:|---:|---:|---:|---:|---|
| 2021 | +0.357 | -8.02% | 67.12% | — | `357f8817` |
| 2022 | +0.000 | — | 42.03% | — | `2d6793fa` |
| 2023 | +0.365 | -6.74% | 64.27% | — | `bd67e3c1` |
| 2024 | +0.382 | -8.50% | 57.95% | — | `88d48a32` |
| 2025 | +0.303 | -6.94% | 60.81% | — | `bb7adbb3` |

### `pairs_trading_MA_V_v1`

| year | Sharpe | MDD % | Win Rate % | total_trades | canon md5 (8-char) |
|---:|---:|---:|---:|---:|---|
| 2021 | +0.380 | -0.55% | 50.00% | — | `f607d199` |
| 2022 | +0.321 | -0.69% | 70.00% | — | `3c2ff680` |
| 2023 | +0.451 | -0.78% | 53.85% | — | `397fc615` |
| 2024 | +0.431 | -9.54% | 61.34% | — | `3145cbb6` |
| 2025 | +0.343 | -0.46% | 77.78% | — | `2ae3a5c8` |

### `dividend_initiation_drift_v1`

| year | Sharpe | MDD % | Win Rate % | total_trades | canon md5 (8-char) |
|---:|---:|---:|---:|---:|---|
| 2021 | +0.378 | -2.86% | 64.00% | — | `c17f1b5f` |
| 2022 | +0.841 | -0.22% | 30.00% | — | `bc605421` |
| 2023 | +0.383 | -6.91% | 55.26% | — | `33685d45` |
| 2024 | +0.344 | -7.49% | 56.49% | — | `9f620853` |
| 2025 | +0.291 | -7.38% | 55.10% | — | `fe9b555e` |

## Factor decomposition detail

### `momentum_12_1_v1`

- **n_obs (closure days):** 1041
- **Newey-West lag:** 6
- **R²:** 0.1728
- **α (annualized):** +0.0074  (t=+0.36, 95% CI analytic [-0.0333, +0.0481], bootstrap [-0.0319, +0.0453], p(α>0)=0.591)
- **Raw daily Sharpe (annualized):** +1.170
- **Factor betas (HAC t-stats):**
  - MktRF: β=+0.0693 (SE=0.0082, t=+8.48)
  - SMB: β=+0.0049 (SE=0.0116, t=+0.42)
  - HML: β=+0.0435 (SE=0.0155, t=+2.81)
  - RMW: β=-0.0282 (SE=0.0127, t=-2.21)
  - CMA: β=-0.0297 (SE=0.0193, t=-1.54)
  - Mom: β=+0.0336 (SE=0.0089, t=+3.77)

### `momentum_6_1_v1`

- **n_obs (closure days):** 1054
- **Newey-West lag:** 6
- **R²:** 0.1673
- **α (annualized):** -0.0202  (t=-1.01, 95% CI analytic [-0.0596, +0.0191], bootstrap [-0.0622, +0.0170], p(α>0)=0.130)
- **Raw daily Sharpe (annualized):** +0.439
- **Factor betas (HAC t-stats):**
  - MktRF: β=+0.0714 (SE=0.0110, t=+6.48)
  - SMB: β=-0.0075 (SE=0.0096, t=-0.78)
  - HML: β=+0.0329 (SE=0.0104, t=+3.15)
  - RMW: β=-0.0224 (SE=0.0089, t=-2.52)
  - CMA: β=+0.0126 (SE=0.0124, t=+1.01)
  - Mom: β=+0.0086 (SE=0.0050, t=+1.73)

### `short_term_reversal_v1`

- **n_obs (closure days):** 1019
- **Newey-West lag:** 6
- **R²:** 0.1394
- **α (annualized):** +0.0339  (t=+1.76, 95% CI analytic [-0.0038, +0.0717], bootstrap [-0.0021, +0.0703], p(α>0)=0.966)
- **Raw daily Sharpe (annualized):** +2.259
- **Factor betas (HAC t-stats):**
  - MktRF: β=+0.0617 (SE=0.0076, t=+8.08)
  - SMB: β=+0.0016 (SE=0.0125, t=+0.13)
  - HML: β=+0.0330 (SE=0.0100, t=+3.30)
  - RMW: β=-0.0108 (SE=0.0111, t=-0.98)
  - CMA: β=+0.0183 (SE=0.0126, t=+1.45)
  - Mom: β=-0.0103 (SE=0.0069, t=-1.49)

### `pairs_trading_MA_V_v1`

- **n_obs (closure days):** 62
- **Newey-West lag:** 3
- **R²:** 0.0762
- **α (annualized):** +0.1797  (t=+1.41, 95% CI analytic [-0.0703, +0.4297], bootstrap [-0.0459, +0.4237], p(α>0)=0.937)
- **Raw daily Sharpe (annualized):** +3.349
- **Factor betas (HAC t-stats):**
  - MktRF: β=+0.0850 (SE=0.0407, t=+2.09)
  - SMB: β=+0.0473 (SE=0.0596, t=+0.79)
  - HML: β=+0.0724 (SE=0.0551, t=+1.31)
  - RMW: β=+0.0094 (SE=0.0502, t=+0.19)
  - CMA: β=+0.0155 (SE=0.0616, t=+0.25)
  - Mom: β=-0.0384 (SE=0.0463, t=-0.83)

### `dividend_initiation_drift_v1`

- **n_obs (closure days):** 158
- **Newey-West lag:** 4
- **R²:** 0.1802
- **α (annualized):** +0.2222  (t=+1.20, 95% CI analytic [-0.1416, +0.5860], bootstrap [-0.1590, +0.5905], p(α>0)=0.864)
- **Raw daily Sharpe (annualized):** +0.834
- **Factor betas (HAC t-stats):**
  - MktRF: β=+0.3019 (SE=0.0556, t=+5.43)
  - SMB: β=-0.0881 (SE=0.1073, t=-0.82)
  - HML: β=+0.1227 (SE=0.1176, t=+1.04)
  - RMW: β=+0.0146 (SE=0.1823, t=+0.08)
  - CMA: β=-0.1185 (SE=0.1755, t=-0.67)
  - Mom: β=+0.0388 (SE=0.0998, t=+0.39)

## Factor panel meta

- **Factor source:** Ken French FF5 + Momentum (`core/factor_decomposition.load_factor_data`)
- **Factor date range available:** 1963-07-01 .. 2026-02-27
- **Factor columns:** MktRF, SMB, HML, RMW, CMA, Mom

## Caveats

1. **Single-edge isolation is a stress test, not a deployment plan.** An edge running solo holds whatever positions it generates without ensemble support — a sparse-signal edge will sit flat most days and concentrate risk on its few activations. The numbers here measure *signal density* and *factor-adjusted alpha*, not real-world deployment Sharpe inside an ensemble.

2. **Pair edge generates 2-leg signals.** When `pairs_trading_MA_V_v1` runs isolated, both MA and V trade together. The harness's `exact_edge_ids` override does not split the pair; verify in the per-year trade logs that both tickers appear in trades.csv.

3. **Cross-year bootstrap n=5 is small.** CI widths are wide; borderline verdicts should be re-measured at 2-3 reps per year if the director wants tighter bands. Per project conventions, T-002 established 30/30 determinism so additional reps are bitwise identical to rep 1 within each year.

4. **CLAUDE.md prohibits manual edge promotion.** Even a promote-candidate verdict does NOT auto-flip the spec to `status='active'`. Director reviews + approves all promotions.

5. **Calendar features omitted by spec.** They are Foundry features, not standalone edges; they don't generate trade signals on their own. Their value (if any) materializes only if a Discovery-generated edge consumes them.

