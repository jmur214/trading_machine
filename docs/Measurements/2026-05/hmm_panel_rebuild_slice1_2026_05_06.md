# HMM Input-Panel Rebuild — Slice 1: VIX Term Structure

**Date:** 2026-05-06
**Branch:** `hmm-panel-vix-term-structure`
**Worktree:** `/Users/jacksonmurphy/Dev/trading_machine-2/.claude/worktrees/agent-af717ad4ff2895750`
**Prior baseline:** `regime_signal_validation_2026_05_06.{md,json}`
**Verdict:** **Branch 2 — partial improvement. VIX term structure is NOT leading on its own; pivot the next slice to IV skew + put-call ratios in the same dispatch.**

## What changed

Added three forward-looking-by-construction features to the HMM input panel:

| Feature | Construction | Economic meaning |
|---|---|---|
| `vix_term_spread` | `vix3m − vix` | Negative = backwardation = near-term fear concentrated. Matches `forward_stress_detector.py`. |
| `vix9d_over_vix_ratio_minus1` | `vix9d / vix − 1` | Positive = 9-day implied vol exceeds 30-day implied vol. Sharper near-term spike signal. |
| `vix_zscore_60d` | 60-trading-day z-score of VIX level | Decouples regime-current stress from absolute VIX level. |

Data source: `^VIX9D` / `^VIX` / `^VIX3M` from yfinance, cached to `data/macro/{VIX9D,VIX,VIX3M}.parquet` via `scripts/fetch_vix_term_structure.py`. 1339 rows, 2020-01-02 → 2025-04-30. All three series available daily across the validation window — no coverage gaps that affect the HMM.

A new model artifact `engines/engine_e_regime/models/hmm_3state_vix_term_v1.pkl` was trained on the extended 10-feature panel (original 7 + 3 VIX-term). Original 7-feature model (`hmm_3state_v1.pkl`) is untouched. K-state validation again landed on K=3 by best test log-likelihood per observation.

## Headline AUC table — slice 1 vs baseline

Target: `forward 20d SPY drawdown ≤ −5%`, base rate 0.212, N=1086 days.

| Signal | Baseline AUC | Slice 1 AUC | Δ |
|---|---:|---:|---:|
| `hmm_p_crisis` | 0.4919 | **0.5948** | **+0.103** |
| `hmm_p_stressed` | 0.6014 | 0.4066 | −0.195 |
| `hmm_p_stress_or_crisis` | 0.5965 | 0.5023 | −0.094 |
| `hmm_neg_p_benign` | 0.6146 | 0.4965 | −0.118 |

`hmm_p_crisis` crosses the 0.55 verdict threshold, but the other three forms degrade. **The signal didn't get more leading — the state space rotated.** In the baseline the lift came from "non-benign" (stressed or crisis); in slice 1 the lift concentrates in `crisis` only. Net portfolio-meaningful information content is similar to the baseline; concentrated differently.

## Standalone AUC of the new VIX features

| Feature | 20d 5% AUC | 20d 3% AUC | 5d 5% AUC | 60d 5% AUC |
|---|---:|---:|---:|---:|
| `vix_term_spread` | 0.6825 | 0.7306 | 0.3205 | 0.7595 |
| `vix9d_over_vix_ratio_minus1` | 0.3988 | 0.3188 | 0.7230 | 0.2672 |
| `vix_zscore_60d` | 0.2032 | 0.1858 | 0.5889 | 0.1714 |

These look like high AUC numbers — but read the directionality. `vix_term_spread` AUC = 0.68 means **higher contango spread predicts bigger forward drawdowns**, which is economically backwards. The interpretation is mean-reversion: when contango is wide (calm now), forward drawdowns over 60d are larger because crashes don't follow each other. `vix_zscore_60d` = 0.20 (1−AUC = 0.80 if flipped) is the same coincident pathology that killed the baseline — high VIX z-score predicts SMALLER forward drawdowns because we're already past the peak fear. The 9d/30d ratio AUC = 0.40 has the cleanest economic sign (high ratio predicts more 5d-fwd drawdown), but only at 5d horizon — at 20d/60d it inverts.

**The VIX term-structure features are coincident vol detectors with a slightly different waveform than the baseline panel. They are not leading.**

## Coincident-vs-leading test (the verdict criterion)

Pearson correlation against trailing-20d return vs forward-20d return. A leading signal has |forward| > |trailing|.

| Signal | Pearson(trailing 20d ret) | Pearson(forward 20d ret) | |fwd|/|trail| |
|---|---:|---:|---:|
| baseline `p_crisis` | −0.512 | −0.209 | 0.408 |
| slice-1 `p_crisis` | −0.288 | −0.094 | 0.327 |
| slice-1 `p_stress_or_crisis` | −0.207 | −0.114 | 0.552 |
| `vix_term_spread` (standalone) | +0.498 | −0.167 | 0.336 |
| `vix9d_over_vix_ratio_minus1` (standalone) | −0.423 | +0.107 | 0.253 |
| `vix_zscore_60d` (standalone) | −0.617 | +0.140 | 0.227 |

Every signal in the slice-1 panel — HMM probabilities AND standalone VIX features — shows trailing correlation ≥ 2x forward correlation in absolute value. **The coincident-leading flip the dispatch's Branch 1 criterion required did not happen.** Forward correlations are all in the noise; the standalone VIX features actually have **opposite signs** on trailing vs forward (e.g. vix_zscore: high now → big trailing drawdown; high now → small forward drawdown), the canonical mean-reverting coincident-detector signature.

## OOS narrative — the 2025 −18.76% drawdown

This is the most important data point of the analysis. SPY peak 2025-02-19 @ $604.17, trough 2025-04-08 @ $490.85, peak-to-trough −18.76%.

### When did each model first call stress?

| Model | First state ≠ benign before peak | Lead time |
|---|---|---:|
| Baseline 7-feature HMM | Never (`benign` from 2024-08 through 2025-02-19) | 0 days |
| Slice-1 10-feature HMM | `stressed` argmax flipped 2024-12-02 | **78 calendar days** |

Slice-1 wins the lead-time test convincingly. **But here is the punchline: the slice-1 lead-time is not coming from the VIX term-structure features.**

State means (z-scored) for the slice-1 HMM:
- **stressed**: `yield_curve_spread=+1.24`, `credit_spread_baa_aaa=−0.97`, `vix_term_spread=+0.71`, `spy_vol_20d=−0.42` — yield-curve / credit driven, low vol, **contango VIX**.
- **crisis**: `spy_vol_20d=+1.02`, `vix_level=+0.82`, `vix_term_spread=−0.48`, `vix9d_over_vix=+0.40`, `credit_spread=+0.61` — vol-and-VIX-backwardation driven.
- **benign**: `vix_level=−0.73`, `dollar_ret_63d=−0.50`, `yield_curve_spread=−0.86` — calm, weak dollar, inverted/flat curve.

At the 2024-12-02 stressed-flip date, the VIX-term features were:
- `vix_term_spread = +2.46` (contango, calm)
- `vix9d_over_vix_ratio_minus1 = −0.11` (calm)
- `vix_zscore_60d = −1.75` (well below average)

**All three VIX features were calling "calm" at the moment the HMM flipped to stressed.** The flip was driven by the yield-curve un-inversion + low-vol-with-credit-tightening pattern, both of which were already in the baseline panel. Adding VIX term features changed how the HMM partitioned its state space — and that re-partition happens to put the late-2024 / early-2025 environment in `stressed` rather than `benign` — but the VIX features themselves were calm during that 78-day window.

At the 2025-04-08 trough, the VIX features WERE on fire:
- `vix_term_spread = −10.83` (extreme backwardation)
- `vix9d_over_vix_ratio_minus1 = +0.29` (huge near-term spike)
- `vix_zscore_60d = +4.33`

This timing is the exact opposite of the dispatch's leading-feature requirement: **VIX term structure fires at the trough, not before the drawdown.**

## In-sample vs OOS AUC delta

| Metric | Baseline | Slice 1 | Δ |
|---|---:|---:|---:|
| IS `p_crisis` 5%-target | 0.5050 | 0.5996 | +0.095 |
| IS `p_stress_or_crisis` 5%-target | 0.5876 | 0.5090 | −0.079 |
| OOS `p_crisis` 3%-target | 0.3630 | 0.3243 | **−0.039** |
| OOS `p_stress_or_crisis` 3%-target | 0.3630 | **0.6537** | **+0.290** |
| OOS `neg_p_benign` 3%-target | 0.3630 | 0.6189 | +0.256 |

The OOS `p_stress_or_crisis` AUC jumps from 0.363 to 0.654 — a meaningful improvement, larger than any single change in the in-sample numbers. This is the slice-1 model's best result.

**But the source is the same as the lead-time finding:** the OOS window is dominated by the Feb-Apr drawdown, and slice-1 had `stressed` on through Dec 2024 → Feb 19, 2025, then `crisis` from Feb 21 onward. So `p_stress_or_crisis` was high through the entire decline. The AUC reflects that persistent labeling, which traces back to yield-curve / credit features rotating the state space. The standalone VIX features at OOS dates only fire at-or-after the trough.

OOS `p_crisis` actually got slightly *worse* (0.363 → 0.324), again confirming that the new VIX features only contribute when stress is already realized.

## Persistence

| Signal | n_runs | median run | max run | pct on |
|---|---:|---:|---:|---:|
| baseline `argmax_stressed_or_crisis` | 4 | 40.5 bars | 497 bars | 55.1% |
| slice-1 `argmax_stressed_or_crisis` | 4 | 109.5 bars | 497 bars | 66.8% |
| slice-1 `argmax_crisis` | 5 | 48 bars | 217 bars | 33.7% |

Slice-1 `stressed_or_crisis` is now on for 67% of the window vs 55% in the baseline. **A signal that's on 2/3 of the time is operationally weaker for risk-sizing decisions, not stronger.** Even though some metrics moved up, the system's ability to *time* a de-grossing event got worse, not better.

## Verdict

**Branch 2 — partial improvement. VIX term structure helps but isn't enough.**

Reading the criteria literally:
- AUC > 0.55 on 20d-fwd-drawdowns: ✅ for `hmm_p_crisis` (0.595), but other forms degraded
- Coincident-vs-leading correlation flips: ❌ — every signal still trailing-dominant
- 2025 OOS calls stress BEFORE drawdown: ⚠️ — slice-1 `stressed` flipped 78 days before the peak, but the lead came from yield-curve features in the existing panel, not from the new VIX term-structure features. The VIX features themselves fired AT the trough.

**The cleanest reading: VIX term-structure features change the HMM's state partition in a way that makes the existing yield-curve / credit features do useful work, but the VIX features themselves are coincident.**

That is a real improvement, just not the one the dispatch hypothesized. It is not enough to justify wiring this HMM into Engine B.

### Why not Branch 1

The honest answer is that "AUC > 0.55" was achievable through any feature change that perturbs the state-space partition. The dispatch's coincident-vs-leading test is the better discriminator and slice 1 fails it cleanly. The 0.5948 AUC for `p_crisis` is real but operationally weak — the lift is mostly in the second half of crisis episodes, not at the leading edge.

### Why not Branch 3

The 2024-12-02 → 2025-02-19 lead-time IS a real lead, even if its mechanism is panel-rotation rather than VIX term-structure. The yield-curve + credit features in the slice-1 stressed state ARE leading on this one OOS event, and that's worth exploring — see "Recommendations" below.

## Recommendations (in order)

1. **Pivot slice 2 to IV skew + put-call ratios** as the dispatch's contingency calls for. VIX term structure is empirically coincident in this window. IV skew is the next strongest theoretical leading-indicator candidate. Put-call ratio is the cheapest to fetch (CBOE publishes daily; some yfinance paths cover it).

2. **Investigate the yield-curve / credit subspace separately.** The slice-1 stressed state's 78-day OOS lead came from features already in the baseline panel. A targeted experiment: train a 4-feature HMM on `{spy_vol_20d, yield_curve_spread, credit_spread_baa_aaa, dollar_ret_63d}` and re-validate. If that minimal model also gets OOS `p_stress_or_crisis` AUC ≈ 0.65, the panel rebuild may be over-engineered relative to what's actually load-bearing.

3. **Do NOT swap `hmm_3state_v1.pkl` for `hmm_3state_vix_term_v1.pkl` in production yet.** The slice-1 model is recorded as a research artifact; promoting it would worsen `p_crisis` OOS AUC and add operational ambiguity (since `p_stress_or_crisis` is high two-thirds of the time, gating off it is a near-permanent risk-off bias).

4. **Engine B integration remains BLOCKED** under the same logic as the 2026-05-06 baseline finding. AUC threshold partially crossed; coincident-leading test failed; lead-time win is from non-VIX features. We cannot honestly tell Engine B's risk-sizing layer that the HMM is leading.

## Files

- `scripts/fetch_vix_term_structure.py` — yfinance ingestion for ^VIX9D/^VIX/^VIX3M
- `scripts/train_hmm_vix_term.py` — slice-1 trainer
- `scripts/validate_regime_signals_vix_term.py` — slice-1 validator
- `engines/engine_e_regime/macro_features.py` — extended panel via `include_vix_term=True`; `VIX_TERM_FEATURES` constant
- `engines/engine_e_regime/models/hmm_3state_vix_term_v1.pkl` — slice-1 model artifact
- `data/macro/{VIX9D,VIX,VIX3M}.parquet` — cached VIX-family closes
- `data/research/hmm_kstate_vix_term_validation_2026_05.json` — k-state training metrics
- `docs/Measurements/2026-05/regime_signal_validation_vix_term_2026_05_06.json` — full slice-1 validation metrics
