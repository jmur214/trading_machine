---
name: VIX term structure is coincident, not leading — slice 1 verdict Branch 2 (2026-05-06)
description: First slice of the HMM input-panel rebuild added vix_term_spread, vix9d/vix-1, vix_zscore_60d as features. AUC for hmm_p_crisis on 20d-fwd-drawdowns moved 0.49 → 0.59 (crossed the 0.55 threshold), but standalone VIX-term features have forward correlations near zero and trailing correlations 2-3x larger in absolute value. The HMM's 78-day OOS lead-time on the 2025 -18.76% drawdown traces to yield-curve / credit features rotating into the new "stressed" state, not to the VIX features themselves. VIX term structure features fire AT the trough (-10.83 spread on the trough day vs +2.66 calm contango at the peak). Verdict: Branch 2 (partial improvement). Pivot slice 2 to IV skew + put-call ratios, not more VIX-derived features.
type: project
---
## What was tested

Added three VIX-term-structure features to the HMM input panel as slice 1 of the regime-engine rebuild:
- `vix_term_spread = vix3m − vix` (negative = backwardation = near-term fear concentrated)
- `vix9d_over_vix_ratio_minus1 = vix9d/vix − 1` (positive = sharp near-term implied-vol spike)
- `vix_zscore_60d` (60-trading-day z-score of VIX level)

Data fetched from yfinance (^VIX9D, ^VIX, ^VIX3M), cached to `data/macro/{VIX9D,VIX,VIX3M}.parquet`. New 3-state HMM trained on the 10-feature panel and saved to `hmm_3state_vix_term_v1.pkl`. Validated via `scripts/validate_regime_signals_vix_term.py`.

## Headline numbers

20d-forward-drawdown ≤ −5%, base rate 0.212, N=1086:

| Signal | Baseline AUC | Slice 1 AUC |
|---|---:|---:|
| `hmm_p_crisis` | 0.4919 | **0.5948** |
| `hmm_p_stressed` | 0.6014 | 0.4066 |
| `hmm_p_stress_or_crisis` | 0.5965 | 0.5023 |
| `hmm_neg_p_benign` | 0.6146 | 0.4965 |

OOS (2025 Jan-Apr, 3% target): `p_stress_or_crisis` AUC 0.363 → 0.654.

`p_crisis` AUC crossed 0.55 (Branch 1's first criterion). But the redistribution across forms (other three got worse) shows the lift is state-rotation, not new leading information.

## Why I called Branch 2 not Branch 1

Coincident-vs-leading test:
- slice-1 `p_crisis`: trailing -0.288, forward -0.094, ratio 0.327
- slice-1 `p_stress_or_crisis`: trailing -0.207, forward -0.114, ratio 0.552
- standalone `vix_term_spread`: trailing +0.498, forward -0.167, ratio 0.336
- standalone `vix9d_over_vix_ratio_minus1`: trailing -0.423, forward +0.107, ratio 0.253
- standalone `vix_zscore_60d`: trailing -0.617, forward +0.140, ratio 0.227

Forward correlations are noise-level for every feature. Trailing correlations are 2-3x larger in absolute value. **Every standalone VIX term feature has opposite signs on trailing vs forward** — the canonical mean-reverting coincident-detector signature.

## The OOS narrative is the smoking gun

2025-02-19 SPY peak ($604.17), 2025-04-08 trough ($490.85), peak-to-trough −18.76%.

- Baseline 7-feature HMM: said `benign` (>0.99) through the entire run-up to the peak. Zero-day lead.
- Slice-1 10-feature HMM: `argmax = stressed` flipped 2024-12-02, **78 calendar days before the peak**.

But at the 2024-12-02 stressed flip:
- `vix_term_spread = +2.46` (contango, calm)
- `vix9d_over_vix_ratio_minus1 = −0.11` (calm)
- `vix_zscore_60d = −1.75` (well below average)

All three VIX features were calling "calm" at the moment the HMM flipped to stressed. The actual leading-feature mass came from yield_curve_spread + credit_spread_baa_aaa (already in the baseline panel) — the 10-feature HMM partitioned its state space differently and put the late-2024 yield-curve-uninversion / low-vol-with-credit-tightening regime into `stressed` rather than `benign`.

At the 2025-04-08 trough: `vix_term_spread = −10.83`, `vix9d_over_vix_ratio_minus1 = +0.29`, `vix_zscore_60d = +4.33`. All three VIX features fire at the trough. **VIX term-structure features are coincident vol detectors. They confirm the bottom; they do not anticipate the top.**

## Slice-1 stressed state is yield-curve-driven

The HMM's z-scored state means show what each state is summarizing:
- **stressed**: `yield_curve_spread=+1.24`, `credit_spread=−0.97`, `vix_term_spread=+0.71` (contango), `spy_vol_20d=−0.42` — late-cycle yield-curve / credit pattern, low vol, calm VIX
- **crisis**: `spy_vol_20d=+1.02`, `vix_term_spread=−0.48` (backwardation), `vix9d_over_vix=+0.40`, `credit_spread=+0.61` — vol-and-VIX-backwardation pattern
- **benign**: `vix_level=−0.73`, `dollar_ret_63d=−0.50`, `yield_curve_spread=−0.86` — calm, weak dollar, inverted/flat curve

Crisis state IS the VIX-term-fire state. Stressed state is the yield-curve-fire state. The HMM uses VIX features only to identify the TROUGH, not the top.

## What this means for next slice

**Pivot slice 2 to IV skew + put-call ratios** (the dispatch's Branch 3 contingency, applied here because Branch 2 is the verdict and Branch 2's recommendation echoes Branch 3's pivot).

Independent investigation worth doing in parallel: train a minimal 4-feature HMM on `{spy_vol_20d, yield_curve_spread, credit_spread_baa_aaa, dollar_ret_63d}` and re-validate. If that minimal panel reproduces the slice-1 OOS AUC, the panel-rebuild project is over-engineered relative to what's load-bearing.

## What NOT to do

- DO NOT promote `hmm_3state_vix_term_v1.pkl` to production. `p_crisis` AUC moved up but `p_crisis` 60d AUC dropped further (0.31→0.37 in baseline → 0.37 in slice-1, still below random) and `p_stress_or_crisis` is on 67% of the time — operationally near-permanent risk-off if you gate off it.
- DO NOT wire this slice into Engine B. Coincident-leading test failed; lead-time mechanism is not the new features.
- DO NOT add IV-skew or put-call to THIS panel/HMM. Build a fresh slice with those features in isolation. Mixing partially-validated layers compounds the diagnosis problem.

## Files

- `engines/engine_e_regime/macro_features.py` — `VIX_TERM_FEATURES` constant + `include_vix_term=True` arg on `build_feature_panel`
- `scripts/fetch_vix_term_structure.py`
- `scripts/train_hmm_vix_term.py`
- `scripts/validate_regime_signals_vix_term.py`
- `engines/engine_e_regime/models/hmm_3state_vix_term_v1.pkl`
- `data/macro/{VIX9D,VIX,VIX3M}.parquet`
- `docs/Measurements/2026-05/hmm_panel_rebuild_slice1_2026_05_06.md` — full audit doc
- `docs/Measurements/2026-05/regime_signal_validation_vix_term_2026_05_06.json` — raw slice-1 metrics
