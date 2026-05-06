# Regime Panel Rebuild — Slice 2 Plan

**Status:** Drafted 2026-05-06 PM, post-A1 dispatch finding. Awaiting director sign-off before dispatch.

**Source:** the regime-signal validation 2026-05-06 (`docs/Measurements/2026-05/regime_signal_validation_2026_05_06.md`) plus the slice-1 audit (`docs/Measurements/2026-05/hmm_panel_rebuild_slice1_2026_05_06.md`) reframed slice 2 from "add IV skew + put-call" to "isolate the leading features ALREADY in the panel + drop or weight-down the noisy ones."

## What changed our thinking

Slice 1 added VIX9D / VIX3M / VIX term-spread features to the HMM input panel. Verdict was Branch 2 (partial) — `hmm_p_crisis` AUC moved 0.49 → 0.59, BUT:

- The new VIX features themselves were **coincident** (e.g. `vix_term_spread` AUC = 0.68 with the wrong sign — high contango "predicts" forward drawdowns = mean reversion, not leading)
- The 78-day stressed lead before the 2025 -18.8% drawdown came from `yield_curve_spread` and `credit_spread_baa_aaa` features — **already in the baseline panel** but masked by other features
- Coincident-vs-leading correlation test still failed across all signals

**Implication:** the existing panel has more leading signal than we realized; it's a feature-selection problem, not a feature-acquisition problem. Add features later; isolate the working ones first.

## Slice 2 goal

Identify which of the existing HMM panel features are leading (correlated with FORWARD drawdowns) vs coincident (correlated with TRAILING drawdowns) vs noise. Rebuild the panel keeping only the leading subset, then re-validate.

## Concrete deliverables

### 1. Per-feature leading-vs-coincident classification

For every feature currently in `engines/engine_e_regime/macro_features.py::MACRO_FEATURES` (plus the new VIX_TERM_FEATURES from slice 1), compute:

- Pearson correlation vs **trailing 20-day SPY return**
- Pearson correlation vs **forward 20-day SPY return**
- Ratio `|fwd_corr| / |trail_corr|` — > 1.0 means the feature carries more forward information than backward; < 0.5 is firmly coincident

Plus AUC vs 20d-fwd-drawdown ≤ -5% for each feature standalone.

Output a table classifying each feature as:
- **LEADING** — `|fwd_corr| / |trail_corr|` > 1.0 AND AUC > 0.55
- **COINCIDENT** — fwd/trail ratio < 0.5 (information is about the past, not the future)
- **NOISE** — AUC ≈ 0.5 regardless of correlation profile

### 2. Trained-HMM-with-leading-features-only

Train a fresh HMM on ONLY the LEADING-classified features. Compare to the slice-1 panel:
- AUC for `hmm_p_crisis` and `hmm_p_stress_or_crisis`
- Coincident-vs-leading correlation flip (does the rebuilt HMM's `p_crisis` correlate more with forward returns than trailing?)
- 2025 OOS event: how many days before the -18.8% drawdown peak does the leading-only HMM call stress?
- Time-on percentage for `argmax = stressed_or_crisis` — slice-1 was 67% (near-permanent risk-off); leading-only should be lower

### 3. Salvage report

For features classified as COINCIDENT or NOISE: are any worth keeping for ANY purpose (e.g., as a regime-state-classifier even though not predictive)? Or should they be dropped entirely from the panel?

For features classified as LEADING: are they robust across years, or year-specific (e.g., yield-curve only led in 2025 because of the specific bond-stress shape)?

### 4. Verdict on slice 3

- **Branch 1** — leading-only HMM clears AUC > 0.55 AND coincident-leading flip succeeds. Verdict: this is the new HMM panel; promote model to default; consider Engine B integration scoping.
- **Branch 2** — improvement but still partial. Verdict: slice 3 adds IV skew + put-call as the next feature family.
- **Branch 3** — no improvement. Verdict: existing panel features are not enough; slice 3 must acquire genuinely new feature data sources.

## Hard constraints (for the eventual dispatch)

- READ-ONLY analysis on existing panel + price data. No data acquisition needed (slice 3 is when we go get IV skew etc.).
- DO NOT promote any HMM model to production this dispatch — model selection is a separate decision after slice 3+ converges.
- DO NOT modify Engine B / live_trader/.
- Reuse `scripts/validate_regime_signals.py` and `scripts/train_hmm_vix_term.py` as starting points; they have the relevant scaffolding.
- Branch: `hmm-panel-feature-selection-slice2`
- Time budget: 2-3 hours

## Why this is the right next move (vs alternatives)

- vs **slice 3 (add IV skew + put-call)**: premature — we don't yet know which existing features are pulling weight. Adding more features without selection compounds the noise problem.
- vs **scoping Engine B integration**: blocked — the slice-1 finding showed signals are not net-leading; integration would wire noise to risk-sizing.
- vs **abandoning regime work**: VVIX-proxy AUC 0.64 and the 78-day lead from yield-curve / credit features both suggest there IS signal here. Wrong move would be giving up before isolating it.

## Background memories

- `project_regime_signal_falsified_2026_05_06.md` — the validation that triggered this whole arc
- `project_vix_term_structure_coincident_2026_05_06.md` — the slice-1 finding (agent-memory, regime-analyst's working memory)
- `project_path_c_deferred_2026_05_06.md` — Path C unblock chain depends on this work succeeding
