# E-rebuild Phase-1 — Minimal HMM on Leading-Feature Subset

**Date:** 2026-05-07  
**Branch:** `e-rebuild-phase-1`  
**Dispatch:** `docs/Core/Ideas_Pipeline/dispatchable_prompts_2026_05_07.md`  
**Status:** CURRENT

## What was measured

Three minimal-HMM variants trained on a shared 15-month window
(2023-10-01 → 2024-12-31), validated on 16 months of out-of-sample data
(2025-01-01 → 2026-04-17, 323 trading days). Validation tests whether the
posterior `p(stressed_or_crisis) = 1 − p(benign)` predicts forward SPY
drawdowns ≤ −5% at 5-day, 20-day, and 60-day horizons.

| Variant | Features | n (train) |
|---|---|---|
| **A** | spy_vol_20d, yield_curve_spread, credit_spread_baa_aaa, dollar_ret_63d | 315 |
| **B** | A + hyg_ig_oas | 315 |
| **C** | B + copper_gold_ratio + xlp_xly_ratio | 315 |

## What was decided / learned

**Headline:** Variant C clears LEADING at 20d and 60d horizons. Variants A
and B are INDETERMINATE across all horizons. Wire-readiness is documented
below; **wiring into Engine B is deliberately deferred** to a propose-first
dispatch per CLAUDE.md.

### AUC table (variant × horizon)

| Variant | 5d | 20d | 60d |
|---|---|---|---|
| A | 0.514 | 0.513 | 0.500 |
| B | 0.274 | 0.375 | 0.486 |
| **C** | 0.481 | **0.594** | **0.636** |

### Coincident-vs-leading correlation flip ( |fwd_corr| vs |trail_corr| )

| Variant | 5d | 20d | 60d |
|---|---|---|---|
| A | C | L | (n/a — flat trail) |
| B | L | C | C |
| **C** | **L** | **L** | **L** |

L = `|fwd_corr| > |trail_corr|` (forward signal stronger than backward).  
C = `|fwd_corr| ≤ |trail_corr|` (signal is mostly explaining the past).

### Verdicts (AUC > 0.55 AND L → LEADING; AUC > 0.55 AND C → COINCIDENT; AUC ≤ 0.55 → INDETERMINATE)

| Variant | 5d | 20d | 60d |
|---|---|---|---|
| A | INDETERMINATE | INDETERMINATE | INDETERMINATE |
| B | INDETERMINATE | INDETERMINATE | INDETERMINATE |
| **C** | INDETERMINATE | **LEADING** | **LEADING** |

### Per-state forward-drawdown spread @ 60d (Variant C)

| State | n days | mean fwd 60d-dd | p10 fwd 60d-dd |
|---|---|---|---|
| crisis | 243 | −7.8% | −16.7% |
| benign | 20 | **−2.4%** | **−4.5%** |
| unconditional | 263 | −7.4% | −16.7% |

The 20 days flagged "benign" by Variant C show **3.3× lower mean forward
drawdown** and **3.7× shallower p10** than the unconditional baseline.
Variant C's regime classifier IS distinguishing risk-off days from risk-on
days within the 16-month OOS window.

## Why A and B fail

- **Variant A** (4 long-history FRED features alone): 261/263 OOS days
  (99.2%) labeled "crisis". The HMM trained on 2023-10 → 2024-12 had no
  precedent for the 2025 macro environment in those 4 features and
  collapsed to a single state on test data. AUC ≈ 0.500 means the posterior
  carries no within-window discrimination.

- **Variant B** (A + hyg_ig_oas): adding the credit-quality slope
  introduces enough variance that the HMM finds 13 OOS "benign" days, but
  those days have WORSE forward drawdowns (−9.1% vs −7.9% crisis-state
  mean). The state-labeling heuristic (label by ascending `spy_vol_20d`)
  inverts on this feature set, and AUC = 0.27–0.49 means the signal is
  reliably pointing the wrong direction at short horizons. Treat as
  contrarian/mean-reverting if used at all — not as a forward stress
  predictor in its current form.

## Why C works

The 63-day-log-changed copper-gold ratio and XLP/XLY ratio inject genuine
forward-looking economic information that the FRED-only features lack:

- `copper_gold_ratio` z-scores: crisis state = **−0.95** (industrial
  underperforms monetary by ~1σ); benign state = **+0.73** (industrial
  outperforms monetary).
- `xlp_xly_ratio` z-scores: crisis state = **−0.54** (cyclicals beating
  defensives); benign state = **+0.40** (defensive rotation in progress).

The HMM is using cross-asset rotation patterns over a 63-day window to
distinguish forward-risk regimes. AUC=0.594 at 20d and 0.636 at 60d are
both above the 0.55 LEADING threshold, with `|fwd_corr|` exceeding
`|trail_corr|` at every horizon (true leading flip).

## Hard caveats

1. **OOS window is 16 months, not multi-cycle.** Includes the early-April
   2025 -18.8% drawdown but no full bull-bear cycle. AUC of 0.594-0.636 is
   a "weak signal" not a strong one.

2. **HY-IG OAS data is only available from 2023-05-08 onward** — ICE BofA
   shortened the freely-available FRED series in mid-2023. The dispatch's
   "1989+ for FRED HY OAS series" assumption was incorrect; all
   ICE-BofA-licensed OAS series in FRED now have ~3-year rolling history.
   Pre-2023 history would require a paid CBOE/ICE subscription.

3. **Variant A's "crisis" state is mislabeled.** The state-labeling
   heuristic uses `spy_vol_20d` ascending, but Variant A's "crisis" state
   actually has the LOWEST credit spread and POSITIVE yield curve — the
   opposite of a typical crisis. Future state-labeling should use a
   composite stress score (multiple z-scored features) rather than vol alone.

4. **HMM EM did not converge on at least one variant** (warning during
   training). Re-fitting with more iterations or different seeds would be
   prudent before any production use.

5. **15-month training window is short.** Standard practice for 3-state
   HMMs is 5-10 years; we have 15 months. The constraint is the OAS data
   start date — extending Variant A only to a longer window would invert
   the apples-to-apples comparison.

6. **AUC at 60d is computed against 173/263 = 65.8% positive labels** —
   severe class imbalance from the bear-market regime that dominated the
   OOS window. AUC at 20d (42/263 = 16% positive) is a cleaner metric.

## Wire-readiness assessment

Variant C clears LEADING — wire-readiness is **DOCUMENTED, NOT EXECUTED**.

Per CLAUDE.md, Engine B / live_trader/ changes require explicit
propose-first approval. The path here would be:

1. **Engine E exposes Variant C HMM as an alternate classifier.** Add
   `MinimalHMMRegimeClassifier` (or extend `HMMRegimeClassifier` with a
   `model_variant` flag) that loads `models/hmm_minimal_C_v1.pkl` and
   exposes `predict_proba_sequence()` + `latest_state()`. Read-only on
   Engine E, no Engine B touch. ETA: ~2 hours.

2. **Engine B consumes the new posterior in its existing risk-advisory
   path.** Wire `p(stressed_or_crisis)` from the minimal HMM as an
   additional advisory feature in `engine_b_risk/risk_engine.py`. Sizing
   policy (multiplier, hard cap, etc.) requires deliberate config-driven
   choices — DO NOT directly substitute for the existing 7-feature HMM
   advisory until A/B testing on the production pipeline confirms it
   doesn't regress 2025 OOS Sharpe. ETA: ~1 day, full propose-first scope.

3. **Determinism harness** (`scripts/run_isolated.py --runs 3`) verifies
   no drift between the new advisory wire and the baseline. Bitwise canon
   md5 must match within reps; ablation A/B (variant on/off) must show a
   defensible Sharpe lift before default-on.

The 0.59-0.64 AUC range is real but modest. Wiring before broader
validation (longer OOS, multi-cycle backtest including 2018/2020) risks
shipping a weak signal as if it were a strong one. **The next data-acquisition
move should be paid CBOE/ICE OAS history** to extend Variants B/C's
training data through 2008-2020 cycles before any production wire.

## Reproduce

```bash
# Fetch new yfinance series (HG=F, GC=F, XLP, XLY)
python scripts/fetch_leading_indicators.py

# Train all 3 variants on shared window
python scripts/train_minimal_hmm.py --variant all --test-end 2026-04-17

# Validate
python scripts/validate_minimal_hmm.py --test-end 2026-04-17
```

## Files

- New: `scripts/fetch_leading_indicators.py`, `scripts/train_minimal_hmm.py`,
  `scripts/validate_minimal_hmm.py`
- Modified: `engines/engine_e_regime/macro_features.py` (added flags
  `include_hyg_ig`, `include_leading_rs`; added `HYG_IG_FEATURES`,
  `LEADING_RS_FEATURES` constants)
- Tests: `tests/test_macro_features_extended.py` (8 tests),
  `tests/test_minimal_hmm.py` (5 tests)
- Models: `engines/engine_e_regime/models/hmm_minimal_{A,B,C}_v1.pkl`
- States: `data/macro/minimal_hmm_states_{A,B,C}.parquet`
- Validation results: `data/research/hmm_minimal_validation_2026_05.json`

## Cross-references

- 2026-05-06 falsification: `project_regime_signal_falsified_2026_05_06.md`
  — the trigger for this whole arc; HMM AUC=0.49 baseline.
- 2026-05-06 cheap-validation Branch 3: VIX term DECISIVELY COINCIDENT.
- Slice 2 plan: `docs/Core/Ideas_Pipeline/regime_panel_slice_2_plan.md`
  (drafted; this dispatch operationalizes its core idea).
- 2026-05-07 R1 audit (`docs/Sessions/Other-dev-opinion/2-opinions+synthesis.md/code-access_audit.md` §4 item 2):
  flagged HYG-IG OAS as cached-but-unused.
