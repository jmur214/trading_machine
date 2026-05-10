# C-collapses-1.5 — Concentration-Equivalent Capital Test (T-2026-05-09-003)

Generated: 2026-05-10 (T-2026-05-09-003 dispatch)
Spec: `docs/Measurements/2026-05/spec_c_collapses_1_5_concentration_2026_05_08.md`
Source: T-002 Arm 1 trade logs (substrate-honest, HMM OFF, 6 actives)

## Method recap

Post-processing pass on T-002 Arm 1 trade logs — no new backtest. Two equal-weight sizing variants reconstruct hypothetical PnL per closed trade:

- **EW-1**: per-position target = 1/|H_t| at entry bar (H_t = concurrent open positions across all (ticker, edge_id) pairs, INCLUDING the entry being opened)
- **EW-2**: per-position target = 1/10 (constant; matches `max_positions=10` in `config/risk_settings.prod.json` which T-002 ran under)

Hypothetical quantity = (initial_capital × per-position-target) / entry_price. Hypothetical PnL = (exit_price − entry_price) × hypothetical_qty × side_sign. Daily returns = pct_change of cumulative-PnL equity curve.

Trade-log run_ids (rep 1 of each year — within-year reps are bitwise-identical per T-002, any rep suffices):
- 2021: `191c14ba-3e8d-4f7f-ae08-8b24bf54dec0`
- 2022: `85ae17d9-a7b9-473b-933a-94dc0c681fcc`
- 2023: `a23ce948-9fd0-43ef-84c6-dc6aaa7653ca`
- 2024: `a1591104-7c2b-428c-a02a-a1fa712fe569`
- 2025: `a3aac752-6daa-487a-a3e5-2f1e4d81d319`

## Verdict

**Primary:** SELECTION-DOMINANT (CI-overlap) — Arm 1 Sharpe CI [-1.253, +1.706] overlaps EW-1 CI [-0.993, +1.688]. Per-name signal is real and the conviction-weighting chain isn't load-bearing on this sample. Point-estimate delta Δ=+0.2422 is within the noise envelope of the 5-year window. Substrate-honest baseline reflects selection, not sizing accident.

**Secondary:** EW-2 ≥ EW-1 (Δ=+0.6269). CAVEAT: EW-2's 1/MAX_POSITIONS=10% per name × ~100+ empirical concurrent positions implies extreme leverage; EW-2 MDD often catastrophic. Apparent EW-2 Sharpe-superiority is a leverage artifact, not evidence that fixed-N uniform sizing is deployable. EW-2 is included for completeness per spec but shouldn't be read as a deployment recommendation.

Δ EW-1 vs Arm 1 actual: **+0.2422** (thresholds: ±0.05 band, −0.10 sizing-dominant cutoff, +0.10 mis-sized cutoff)
Δ EW-2 vs EW-1: **+0.6269**

## Cross-year headline metrics

| Metric | Arm 1 actual (reconstructed) | EW-1 | EW-2 | T-002 reported |
|---|---:|---:|---:|---:|
| Mean Sharpe | +0.4203 | +0.6626 | +1.2895 | +0.2702 |
| Mean Sortino | +0.6498 | +1.3537 | +1.9033 | +0.2800 |
| Mean MDD (%) | -4.17 | -9.97 | -83.52 | -4.10 |
| Mean Win-Rate (%) | 47.51 | 48.85 | 48.85 | 49.44 |

## Bootstrap 95% CI on cross-year concatenated returns

| Variant | N daily obs | Sharpe point | Sharpe 95% CI | Sortino 95% CI | P(Sharpe>0) |
|---|---:|---:|---|---|---:|
| Arm 1 actual | 1041 | +0.0766 | [-1.2533, +1.7062] | [-1.0630, +1.8298] | 0.509 |
| EW-1 | 1041 | +0.4366 | [-0.9931, +1.6876] | [-0.9211, +2.1553] | 0.691 |
| EW-2 | 1041 | +0.0021 | [-0.7775, +0.8779] | [-0.5662, +5.3593] | 0.488 |

## Per-year breakdown

| Year | Trades | Concurrent (med / max) | Sharpe actual | Sharpe EW-1 | Sharpe EW-2 | MDD actual | MDD EW-1 | WR actual | WR EW-1 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 2021 | 1307 | 101 / 248 | +3.3268 | +2.8953 | +3.1504 | -1.57 | -3.54 | 56.31 | 56.85 |
| 2022 | 1335 | 142 / 250 | -0.3951 | -1.8896 | -0.2311 | -6.68 | -22.81 | 41.20 | 43.37 |
| 2023 | 1733 | 141 / 258 | +1.6540 | +1.8902 | +1.7351 | -2.16 | -5.27 | 54.76 | 55.45 |
| 2024 | 1421 | 144 / 262 | -1.7371 | -0.5617 | +0.8044 | -5.19 | -8.77 | 37.86 | 40.82 |
| 2025 | 1603 | 167 / 286 | -0.7471 | +0.9786 | +0.9886 | -5.23 | -9.45 | 47.41 | 47.79 |

## Caveats (per spec)

1. **Counterfactual sizing only.** Real Engine B at uniform sizing may have produced DIFFERENT signal sets — advisory exposure cap, max-sector limits, and risk-scaler interactions all depend on current concentration. Post-processing assumes the same trade set under different sizing; that's a partial truth.
2. **No transaction-cost feedback.** Slippage in the trade log was incurred at original sizing. Re-applying realistic slippage at different position sizes would be more correct but harder. Bias is small for the EW-2 case where most positions held are smaller than original; bias is more variable for EW-1.
3. **MAX_POSITIONS=10 is the prod config but EMPIRICALLY NON-BINDING.** T-002 trade logs show 100+ concurrent positions per bar (per earlier T-004 inspection of `portfolio_snapshots.csv`). The max-positions Engine B gate (`risk_engine.py:647`) was not the binding constraint — sector caps and exposure caps were. EW-2 with 1/10 sizing is still the spec-defined comparison point but represents a much MORE concentrated counterfactual (10% per name) than the system actually held in practice.
4. **Within-year rep aggregation:** T-002 Arm 1 has 3 reps per year; all 3 reps' canon md5 are unique=1/3 (bitwise-identical trade logs). Used rep 1 of each year, NOT a 3x concatenation, to avoid triple-counting trades.
5. **Initial capital is $100,000 per year**, matching T-002's yearly-isolated harness (each year started at $100k via `isolated()` anchor restore). Cross-year aggregation concatenates yearly returns rather than compounding — same convention as T-002's audit doc.
