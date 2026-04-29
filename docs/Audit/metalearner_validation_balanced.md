# MetaLearner Validation Report — profile=`balanced`

Generated: 2026-04-29T00:09:52
Source run: `data/trade_logs/abf68c8e-1384-4db4-822c-d65894af70a1`
Final model: `data/governor/metalearner_balanced.pkl`

## What this measures

Walk-forward rolling folds: at each anchor date, the model trains on
the trailing 1-year window, predicts the next 5-day forward target,
and rolls forward. Each fold's OOS correlation between predictions
and realized profile-aware fitness is the validation signal.

**Promotion gate** (Session N+2 wiring):
- Mean OOS correlation > 0 across all folds (model adds signal)
- ≥60% of folds with positive OOS correlation (consistent, not lucky)

## Final model

- Train samples (full data): **975**
- Features: **42**
- Train R²: 0.671
- Target range: [-15.2807, 28.1800]
- Predictions clipped to: ±28.1800

## Walk-forward folds

Total folds: **144**
Folds with positive OOS correlation: **74/144** (51%)
Mean OOS correlation: **+0.056**
Median OOS correlation: **+0.037**

| Anchor | n_train | n_val | OOS corr | y_val mean | preds mean |
|--------|---------|-------|----------|------------|------------|
| 2022-01-21 | 252 | 5 | -0.582 | +2.7187 | +0.9196 |
| 2022-01-28 | 252 | 5 | +0.000 | +0.0000 | +6.6116 |
| 2022-02-07 | 252 | 5 | -0.066 | +0.8299 | +0.8124 |
| 2022-02-14 | 252 | 5 | +0.540 | -4.2727 | -0.0205 |
| 2022-02-22 | 252 | 5 | +0.663 | -0.8974 | +4.8959 |
| 2022-03-01 | 252 | 5 | -0.429 | -1.3744 | +1.8745 |
| 2022-03-08 | 252 | 5 | -0.324 | -0.1256 | +3.2487 |
| 2022-03-15 | 252 | 5 | +0.000 | +0.0000 | -0.0646 |
| 2022-03-22 | 252 | 5 | +0.101 | +2.8813 | -2.0337 |
| 2022-03-29 | 252 | 5 | -0.290 | -0.2305 | -0.0943 |
| 2022-04-05 | 252 | 5 | -0.427 | -0.0882 | -1.1008 |
| 2022-04-12 | 252 | 5 | -0.465 | -0.1128 | -0.6904 |
| 2022-04-20 | 252 | 5 | +0.744 | -3.2437 | +0.6013 |
| 2022-04-27 | 252 | 5 | +0.563 | -1.2468 | -1.5901 |
| 2022-05-04 | 252 | 5 | -0.598 | -1.3713 | +1.4054 |
| 2022-05-11 | 252 | 5 | -0.275 | +4.8974 | +0.8020 |
| 2022-05-18 | 252 | 5 | +0.398 | +6.1033 | +1.5376 |
| 2022-05-25 | 252 | 5 | +0.234 | -0.3802 | +4.7345 |
| 2022-06-03 | 252 | 5 | +0.518 | -6.1287 | +0.2472 |
| 2022-06-10 | 252 | 5 | +0.963 | -3.3941 | -3.5465 |
| 2022-06-17 | 252 | 5 | -0.058 | -0.4114 | +2.1670 |
| 2022-06-27 | 252 | 5 | -0.679 | +1.1086 | +2.1165 |
| 2022-07-05 | 252 | 5 | -0.113 | -3.0726 | +1.9434 |
| 2022-07-12 | 252 | 5 | +0.030 | -0.7017 | -1.3229 |
| 2022-07-19 | 252 | 5 | -0.467 | +0.6847 | -1.3723 |
| 2022-07-26 | 252 | 5 | -0.880 | +0.5303 | -0.1421 |
| 2022-08-02 | 252 | 5 | -0.810 | +1.8129 | +1.5311 |
| 2022-08-09 | 252 | 5 | +0.573 | +1.4856 | -1.9491 |
| 2022-08-16 | 252 | 5 | -0.870 | -2.6840 | -1.8641 |
| 2022-08-23 | 252 | 5 | -0.041 | -4.7151 | -1.0507 |
| 2022-08-30 | 252 | 5 | +0.785 | -0.5175 | -2.3351 |
| 2022-09-07 | 252 | 5 | -0.394 | -1.8579 | -0.2283 |
| 2022-09-14 | 252 | 5 | +0.315 | -8.4792 | -1.7549 |
| 2022-09-21 | 252 | 5 | +0.919 | +0.0263 | -9.6369 |
| 2022-09-28 | 252 | 5 | +0.043 | +2.6140 | +1.7167 |
| 2022-10-05 | 252 | 5 | +0.973 | -2.8502 | +0.4194 |
| 2022-10-12 | 252 | 5 | +0.376 | +1.9850 | -2.0252 |
| 2022-10-19 | 252 | 5 | +0.215 | +8.2970 | -1.1290 |
| 2022-10-26 | 252 | 5 | -0.723 | +1.7212 | +8.7913 |
| 2022-11-02 | 252 | 5 | -0.753 | +0.3256 | +2.4935 |
| 2022-11-09 | 252 | 5 | +0.784 | -3.5971 | -1.4389 |
| 2022-11-16 | 252 | 5 | -0.785 | +2.6528 | -2.6690 |
| 2022-11-25 | 252 | 5 | -0.739 | +0.8957 | +0.4905 |
| 2022-12-02 | 252 | 5 | +0.587 | +0.3275 | -0.0225 |
| 2022-12-09 | 252 | 5 | -0.468 | -1.8774 | -1.6092 |
| 2022-12-16 | 252 | 5 | +0.299 | +0.6575 | -0.1647 |
| 2022-12-23 | 252 | 5 | +0.297 | -0.5742 | +1.2879 |
| 2023-01-03 | 252 | 5 | +0.395 | +1.4930 | -0.5078 |
| 2023-01-10 | 252 | 5 | +0.838 | -2.5652 | -0.1159 |
| 2023-01-18 | 252 | 5 | +0.555 | +2.7372 | +4.4786 |
| ... | ... | ... | ... | ... | ... |
| (total 144 folds, showing first 50) | | | | | |

## Promotion verdict

**🔴 DOES NOT PASS promotion gate.** Mean OOS corr +0.056, 51% of folds positive. Either model has no signal vs the profile target, or training data is too noisy. Investigate before wiring into signal_processor.

## Top 15 features by importance

| Feature | Importance |
|---------|------------|
| `momentum_edge_v1_ret_avg20` | 0.0957 |
| `momentum_edge_v1_ret_avg5` | 0.0797 |
| `atr_breakout_v1_ret_avg5` | 0.0775 |
| `volume_anomaly_v1_ret_avg20` | 0.0751 |
| `atr_breakout_v1_ret_avg20` | 0.0678 |
| `low_vol_factor_v1_ret_avg20` | 0.0530 |
| `herding_v1_ret_avg5` | 0.0499 |
| `momentum_edge_v1_active5` | 0.0439 |
| `volume_anomaly_v1_ret_avg5` | 0.0412 |
| `macro_dollar_regime_v1_ret_avg20` | 0.0395 |
| `macro_dollar_regime_v1_ret_avg5` | 0.0389 |
| `gap_fill_v1_ret_avg20` | 0.0338 |
| `value_trap_v1_ret_avg5` | 0.0329 |
| `gap_fill_v1_ret_avg5` | 0.0303 |
| `macro_credit_spread_v1_ret_avg20` | 0.0255 |

## Caveats

- This is a **portfolio-level** meta-learner for the first build. Per-ticker
  scoring requires logging per-bar per-ticker edge scores during the backtest
  (Session N+1.5 follow-up).
- Training data is from a single backtest run. Production deployment should
  retrain on every new backtest to keep the rolling window fresh.
- The profile-aware target uses 5-day forward windows. Multi-horizon training
  + ensembling is deferred to Session N+3.
- No adversarial-features audit yet (Boruta-style). Session N+1's scope was
  the architecture; feature-selection refinement comes next.