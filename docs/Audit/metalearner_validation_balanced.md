# MetaLearner Validation Report — profile=`balanced`

Generated: 2026-04-29T00:40:59
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

- Train samples (full data): **787**
- Features: **13**
- Train R²: 0.556
- Target range: [-15.2807, 28.1800]
- Predictions clipped to: ±28.1800

## Walk-forward folds

Total folds: **106**
Folds with positive OOS correlation: **53/106** (50%)
Mean OOS correlation: **+0.038**
Median OOS correlation: **+0.038**

| Anchor | n_train | n_val | OOS corr | y_val mean | preds mean |
|--------|---------|-------|----------|------------|------------|
| 2022-04-21 | 252 | 5 | -0.388 | -2.8307 | +0.8977 |
| 2022-04-28 | 252 | 5 | +0.655 | -1.0690 | +5.1873 |
| 2022-05-05 | 252 | 5 | -0.021 | +4.4186 | -1.7820 |
| 2022-05-16 | 252 | 5 | -0.220 | +2.6003 | +6.6421 |
| 2022-05-23 | 252 | 5 | +0.950 | +2.3914 | -0.0514 |
| 2022-06-01 | 252 | 5 | -0.790 | -2.4857 | +0.6748 |
| 2022-06-08 | 252 | 5 | +0.259 | -6.0891 | +0.9541 |
| 2022-06-15 | 252 | 5 | +0.373 | -0.6719 | +4.2181 |
| 2022-06-23 | 252 | 5 | -0.724 | -0.5863 | -1.1426 |
| 2022-06-30 | 252 | 5 | -0.496 | -0.1367 | +1.1568 |
| 2022-07-08 | 252 | 5 | +0.818 | -3.0355 | -2.2149 |
| 2022-07-15 | 252 | 5 | +0.754 | +1.1010 | -1.4476 |
| 2022-07-22 | 252 | 5 | +0.139 | +0.2287 | +0.7732 |
| 2022-07-29 | 252 | 5 | +0.480 | +1.4161 | -0.9840 |
| 2022-08-05 | 252 | 5 | +0.399 | +2.3981 | -3.3513 |
| 2022-08-12 | 252 | 5 | +0.469 | -2.6909 | +2.8852 |
| 2022-08-19 | 252 | 5 | +0.589 | -2.0854 | -0.9188 |
| 2022-08-29 | 252 | 5 | +0.889 | -1.4873 | -2.1493 |
| 2022-09-07 | 252 | 5 | -0.588 | -1.8579 | +1.5278 |
| 2022-09-14 | 252 | 5 | +0.735 | -8.4792 | +0.9102 |
| 2022-09-21 | 252 | 5 | -0.851 | +0.0263 | -1.1233 |
| 2022-09-28 | 252 | 5 | +0.263 | +1.9056 | -0.0246 |
| 2022-10-06 | 252 | 5 | -0.138 | -0.8853 | -0.0652 |
| 2022-10-13 | 252 | 5 | +0.453 | +1.3939 | -1.5950 |
| 2022-10-20 | 252 | 5 | -0.051 | +8.2970 | -1.8644 |
| 2022-10-27 | 252 | 5 | -0.813 | +1.7212 | +3.1923 |
| 2022-11-03 | 252 | 5 | -0.436 | +0.2574 | +2.5092 |
| 2022-11-10 | 252 | 5 | +0.081 | -3.0143 | +0.6862 |
| 2022-11-17 | 252 | 5 | +0.342 | +2.5430 | -1.0642 |
| 2022-12-02 | 252 | 5 | -0.283 | +0.3116 | -0.8989 |
| 2022-12-14 | 252 | 5 | +0.584 | -1.3508 | +3.4770 |
| 2022-12-22 | 252 | 5 | -0.235 | -0.9566 | -0.6761 |
| 2023-01-04 | 252 | 5 | -0.235 | +1.9580 | +9.0017 |
| 2023-01-17 | 252 | 5 | -0.757 | +1.8119 | -0.4818 |
| 2023-01-24 | 252 | 5 | +0.770 | +1.7979 | +3.2651 |
| 2023-02-02 | 252 | 5 | -0.497 | -0.5680 | +1.5273 |
| 2023-02-09 | 252 | 5 | -0.380 | -1.7532 | -0.8843 |
| 2023-02-22 | 252 | 5 | +0.656 | +2.8466 | +0.7762 |
| 2023-03-01 | 252 | 5 | -0.003 | +0.5750 | +2.3134 |
| 2023-03-09 | 252 | 5 | +0.863 | +0.2202 | +3.6469 |
| 2023-03-16 | 252 | 5 | +0.610 | -0.1418 | -0.3506 |
| 2023-03-23 | 252 | 5 | -0.151 | +1.8547 | -0.1415 |
| 2023-04-11 | 252 | 5 | +0.718 | -1.4178 | -0.0784 |
| 2023-04-24 | 252 | 5 | +0.605 | +1.0282 | -1.9015 |
| 2023-05-01 | 252 | 5 | +0.133 | -0.1912 | -1.1485 |
| 2023-05-11 | 252 | 5 | +0.247 | +2.5253 | -0.8276 |
| 2023-05-18 | 252 | 5 | -0.626 | -0.7138 | -0.3012 |
| 2023-05-26 | 252 | 5 | -0.056 | +1.1320 | -1.4567 |
| 2023-06-05 | 252 | 5 | +0.825 | +4.2665 | +3.0966 |
| 2023-06-12 | 252 | 5 | +0.117 | -1.1086 | +0.8424 |
| ... | ... | ... | ... | ... | ... |
| (total 106 folds, showing first 50) | | | | | |

## Promotion verdict

**🔴 DOES NOT PASS promotion gate.** Mean OOS corr +0.038, 50% of folds positive. Either model has no signal vs the profile target, or training data is too noisy. Investigate before wiring into signal_processor.

## Top 15 features by importance

| Feature | Importance |
|---------|------------|
| `atr_breakout_v1` | 0.3121 |
| `momentum_edge_v1` | 0.3065 |
| `pead_v1` | 0.1088 |
| `pead_predrift_v1` | 0.1021 |
| `panic_v1` | 0.0380 |
| `pead_short_v1` | 0.0325 |
| `macro_credit_spread_v1` | 0.0229 |
| `macro_dollar_regime_v1` | 0.0194 |
| `low_vol_factor_v1` | 0.0192 |
| `volume_anomaly_v1` | 0.0157 |
| `herding_v1` | 0.0128 |
| `gap_fill_v1` | 0.0072 |
| `value_trap_v1` | 0.0029 |

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