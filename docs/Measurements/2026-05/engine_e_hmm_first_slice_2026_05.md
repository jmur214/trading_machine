# Engine E HMM Regime Detection — First Slice (2026-05-02)

> **Status:** Workstream C of the 2026-05-02 forward plan, first dispatched
> slice. Branch `engine-e-hmm-regime`. Builds on the existing 5-axis
> threshold detector additively — no existing logic removed.
> **Trade-offs noted; this is a foundation, not a finished engine.**

---

## What changed (architectural)

Three additions, one reclassification.

1. **HMM 3-state regime classifier**
   `engines/engine_e_regime/hmm_classifier.py` — `HMMRegimeClassifier`,
   wrapping `hmmlearn.hmm.GaussianHMM`. Trained offline on 2021-2024 daily
   features; pickled at `engines/engine_e_regime/models/hmm_3state_v1.pkl`.
   Inference at backtest time runs a **filtered** posterior over a
   trailing 60-day window (no look-ahead).

2. **Macro feature builder**
   `engines/engine_e_regime/macro_features.py` — single source of truth
   for the 7 canonical regime-input features (SPY 5d return, SPY 20d
   realized vol, TLT 20d return, VIX level, T10Y2Y, BAA-AAA credit
   spread, DTWEXBGS 63d return) plus 4 auxiliaries (real-rate level,
   unemployment 3m momentum, credit-spread 5y z-score, raw log returns).

3. **Confidence-modulated `risk_scalar`**
   `engines/engine_e_regime/advisory.py` — when the HMM posterior is
   spread out (uniform → high entropy), `advisory.risk_scalar` is
   multiplied by a confidence factor `min_floor + (1-min_floor)*conf`
   (default `min_floor=0.6`). Engine B's existing read of
   `advisory.risk_scalar` (`risk_engine.py:639`) absorbs this with **zero
   Engine B code change**. The new `regime_confidence` field is also
   surfaced for diagnostics.

4. **Macro reclassification**
   Four edges flipped to `status: retired` and tagged
   `reclassified_to: regime_input` in `data/governor/edges.yml`. Their
   FRED-derived signal computations now live in `macro_features.py`
   feeding the HMM, no longer producing per-ticker tilts. Auto-register
   blocks in the four edge files write `status="retired"` instead of
   `"active"` so a fresh clone does not promote them back to alpha.

---

## HMM design choices

### Feature vector (7 features)

| Feature | Source | Purpose |
|---|---|---|
| `spy_ret_5d` | data/processed/SPY_1d.csv | Short-term equity momentum |
| `spy_vol_20d` | data/processed/SPY_1d.csv | Realized volatility regime proxy |
| `tlt_ret_20d` | data/processed/TLT_1d.csv | Rates / safe-haven rotation |
| `vix_level` | FRED VIXCLS | Implied vol |
| `yield_curve_spread` | FRED T10Y2Y | Recession-leading slope |
| `credit_spread_baa_aaa` | FRED BAA10Y - AAA10Y | Credit-quality stress |
| `dollar_ret_63d` | FRED DTWEXBGS | Dollar-trend regime |

All FRED series come from the existing `MacroDataManager` parquet cache
under `data/macro/`. SPY/TLT prices come from `data/processed/*_1d.csv`.

### Why GaussianHMM over k-means or Bayesian model

Real markets have temporal structure (today's regime depends on
yesterday's). HMM parametrizes both the emission distributions per
state AND the transition matrix between states, so posterior
probabilities are filtered through that temporal prior. K-means is
i.i.d. by construction — no temporal smoothing.

We did not pursue Bayesian (`pymc`/`stan`) for this slice because the
gains over MLE-fit GaussianHMM are marginal at 1000-row data scale and
inference latency would explode. Possible upgrade in a later slice.

### State-label assignment

The HMM does not return labeled states. We sort the discovered states
by the mean of `spy_vol_20d` (in z-score space) and assign:
- lowest-vol state → `benign`
- middle state → `stressed`
- highest-vol state → `crisis`

This mapping is locked in at training time and persisted in the
artifact, so inference is deterministic.

---

## HMM K-state validation

**Run**: `python scripts/train_hmm_regime.py`
**Train**: 2021-01-01 → 2024-12-31, 1005 daily observations
**Test**: 2025-01-01 → 2025-12-31, 250 daily observations
**Output**: `data/research/hmm_kstate_validation_2026_05.json`

| K | Train LL | Train LL/obs | Test LL | **Test LL/obs** | BIC (train) |
|---|---:|---:|---:|---:|---:|
| 2 | -6,768.59 | -6.735 | -3,114.13 | **-12.457** | 14,034.90 |
| 3 | -6,048.17 | -6.018 | -2,947.64 | **-11.791** ✓ | 12,863.65 |
| 4 | -5,219.06 | -5.193 | -3,611.15 | **-14.445** | 11,488.86 |

**K=3 wins on out-of-sample log-likelihood per observation** — the
relevant criterion for "does this generalize?". K=4 has the lowest
train BIC but the worst test LL (overfits). K=2 underfits.

State distribution on the training set: `{benign: 455, stressed: 319,
crisis: 231}`. On the 2025 test holdout: `{benign: 141, crisis: 109}`
— bimodal because 2025's April market_turmoil event was a sharp
crisis bracketed by extended benign periods, with little time spent
in the transitional stressed state.

---

## Per-bar HMM behavior on 2025 timeline

Smoke-test reading at five 2025 dates (HMM enabled, full 5-axis context):

| Date | HMM argmax | HMM conf | 5-axis macro | risk_scalar |
|---|---|---:|---|---:|
| 2025-01-15 | benign (1.00) | 1.00 | cautious_decline | 0.709 |
| 2025-04-04 | crisis (1.00) | 1.00 | market_turmoil | 0.604 |
| 2025-04-15 | crisis (1.00) | 1.00 | market_turmoil | 0.604 |
| 2025-05-15 | crisis (0.92) / benign (0.08) | **0.747** | emerging_expansion | **0.847** |
| 2025-09-15 | benign (1.00) | 1.00 | robust_expansion | 1.166 |

The May 15 row demonstrates the new architectural property: HMM is
recovering from crisis, 5-axis says expansion, but the HMM posterior
is still spread (0.747 confidence). The advisory's confidence
modulation pulls `risk_scalar` from 1.166-equivalent down to 0.847 —
sizing is reduced during the transition. This is the feature.

---

## Engine B integration — read-only consumer

**No Engine B code changed.** The new `regime_confidence` is folded
into `advisory.risk_scalar` inside `AdvisoryEngine.generate`, which
Engine B's `risk_engine.py:639` already reads. The same chain that
applies `governor_weight`, `gate_confidence`, and existing risk
brakes now naturally absorbs HMM-derived confidence.

This is the correct architectural shape: Engine B reads the
already-computed scalar; Engine E owns the scalar's composition.
Future regime-confidence consumers (e.g., Engine C portfolio
construction) can read the same `regime_confidence` field for their
own purposes without coupling to HMM internals.

---

## Macro reclassification log

| Edge ID | Prior status | New status | New role | FRED series |
|---|---|---|---|---|
| `macro_credit_spread_v1` | retired (already) | retired | regime_input | BAA10Y - AAA10Y |
| `macro_real_rate_v1` | **paused → retired** | retired | regime_input | DFII10 |
| `macro_dollar_regime_v1` | retired (already) | retired | regime_input | DTWEXBGS |
| `macro_unemployment_momentum_v1` | retired (already) | retired | regime_input | UNRATE |

`macro_yield_curve_v1` was retired in a prior cycle and is not part of
this reclassification batch — its T10Y2Y feed already reaches Engine E
through `forward_stress_detector` and `macro_features.yield_curve_spread`.

Three of four were already retired by prior cycles. The reclassification
intent lives in two places:

1. **Source-controlled record** at
   `engines/engine_e_regime/reclassified_macros.yml`. This is the
   durable, committed log — `data/governor/edges.yml` is gitignored
   (regenerable engine state) so any tags I add there don't survive
   a fresh clone. The reclassification record is the single source of
   truth.

2. **Auto-register at import time**: each of the four macro edge files
   now passes `status="retired"` to `EdgeRegistry.ensure(...)` instead
   of `"active"`. Because `EdgeRegistry.ensure()` write-protects
   `status` post-2026-04-25 (the registry-stomp fix), this only matters
   for fresh clones where edges.yml has no existing record — but it
   ensures those clones do not re-promote the macros to alpha.

The registry was also extended with an `extra` field that round-trips
unmodeled tags (e.g. anyone who manually adds `reclassified_to` to
edges.yml will see it preserved across registry rewrites). Useful for
local debugging, but NOT load-bearing for this slice — the
source-controlled YAML at (1) is the contract.

---

## A/B harness backtest — 2025 OOS prod-109

**Procedure** (`scripts/run_isolated.py` — restores
`data/governor/_isolated_anchor` between runs to eliminate drift):

```
python -m scripts.run_isolated --save-anchor
PYTHONHASHSEED=0 python -m scripts.run_isolated --runs 1 --task q1   # baseline
# flip config/regime_settings.json hmm.hmm_enabled=true
PYTHONHASHSEED=0 python -m scripts.run_isolated --runs 1 --task q1   # B
```

| Run | HMM | Sharpe | CAGR % | trades_canon_md5 |
|---|---|---:|---:|---|
| A — baseline | disabled | **0.984** | 4.57 | `0d552dd166bc2d8f897c23a0f82d429b` |
| B — HMM-on   | enabled  | **0.985** | 4.57 | `c3240ed5bee743226235234ac85a3368` |

**Δ Sharpe = +0.001.** Pass criterion (-0.05 floor) cleared by a wide
margin. The trade canon md5 differs between A and B — proof that the
HMM-confidence damping is actually producing different sizing on
transition bars, not no-op'ing. Aggregate effect on full-year 2025 OOS
is in the noise band (∆ < +0.05 stretch).

**Interpretation:** The first slice is *architecturally working* — HMM
posterior modulates `risk_scalar`, Engine B reads it, sizing changes
on uncertainty. But the magnitude of the effect on 2025 OOS Sharpe is
small because:
- The existing 5-axis detector already brakes hard on
  `market_turmoil`, leaving little marginal headroom for the HMM to
  add value during April 2025 turmoil.
- The HMM's confidence is highly concentrated for most bars in 2025
  (bimodal benign/crisis distribution from the K-state validation),
  so the entropy-based damping rarely fires.
- Confidence floor of 0.6 means even uniform posterior only reduces
  `risk_scalar` to 60% — a soft brake, not a hard veto.

This is the right shape for a first slice. Future work (multi-resolution,
transition-warning detector, cross-asset confirmation) should produce
larger Sharpe deltas.

---

## Tests

`tests/test_hmm_classifier.py` (8 tests):
- HMM train/predict round-trip with persist/reload
- State labels ordered by realized vol (benign=lowest, crisis=highest)
- 3-state ≥ 2-state log-likelihood on synthetic 3-regime data
- NaN feature row → uniform posterior (graceful degrade)
- Entropy-based confidence (uniform=0, concentrated=1, mid=mid)
- `predict_proba_sequence` schema (index/cols match input)
- Windowed predict accepts history_panel
- `macro_features.build_feature_panel` schema smoke test

`tests/test_macro_reclassification.py` (5 tests):
- All 4 macros are `status: retired` in edges.yml
- All 4 carry `reclassified_to: regime_input` + `reclassified_on` + note
- All 4 macro edge files have `status="retired"` in auto-register block
- `macro_features` exposes feature columns matching all 4 reclassified macros
- `AdvisoryEngine.generate` consumes `hmm_proba` and modulates
  `risk_scalar` only when the posterior is spread

All 13 new tests pass; 5 unrelated pre-existing failures on `main`
(verified by stash+test+pop) are not regressions of this change.

---

## Follow-up work flagged

1. **Multi-resolution regime detection** — daily-only today. Reviewer
   doc calls for daily/weekly/monthly running in parallel. Weekly
   resampling of the same 7-feature panel is straightforward; monthly
   needs longer training horizons.
2. **Cross-asset confirmation hierarchy** — equity regime should be
   formally cross-checked against the rates regime (yield curve slope
   already in features, but no explicit confirmation logic) and credit
   regime (HYG/IEF data not in `data/processed`; need to add).
3. **Transition-warning detector** — fire alerts when regime is
   *changing* (HMM transition matrix predicted next-state probability
   exceeds threshold). Reviewer's acceptance criterion: ≥48 hours
   ahead in ≥80% of historical regime changes (March 2020, October
   2022). Not built this slice.
4. **DFII10 stale cache** — last ~100 trading days are NaN in the
   panel. Real-rate auxiliary feature is therefore NaN-tail. Refresh
   FRED cache before any production deployment.
5. **HMM retraining cadence** — model frozen at 2021-2024 weights.
   No retraining schedule. Decision deferred: retrain quarterly?
   Annually? Once regime regime drift is detected?
6. **Symlink to `data/macro`** — the worktree setup script does not
   symlink `data/macro/` (only `data/processed`, `data/trade_logs`,
   `data/research`, `data/earnings`). I added the symlink manually for
   this branch. The symlink should be added to
   `scripts/setup_agent_worktree.sh`.
7. **K=4 BIC vs OOS LL conflict** — K=4 wins on train BIC but loses
   badly on test LL. This is classic train-test divergence. The
   forward plan's "K-state validated via likelihood-ratio test"
   implies a more rigorous cross-validation; the current
   train/test split is a one-shot.

---

## Files changed (branch `engine-e-hmm-regime`)

```
NEW   engines/engine_e_regime/hmm_classifier.py
NEW   engines/engine_e_regime/macro_features.py
NEW   engines/engine_e_regime/models/hmm_3state_v1.pkl
NEW   engines/engine_e_regime/reclassified_macros.yml
NEW   scripts/train_hmm_regime.py
NEW   tests/test_hmm_classifier.py
NEW   tests/test_macro_reclassification.py
NEW   docs/Audit/engine_e_hmm_first_slice_2026_05.md   (this doc)
NEW (gitignored — regenerated by training script):
      data/research/hmm_kstate_validation_2026_05.json

MODIFIED  engines/engine_e_regime/regime_config.py
MODIFIED  engines/engine_e_regime/regime_detector.py
MODIFIED  engines/engine_e_regime/advisory.py
MODIFIED  engines/engine_a_alpha/edge_registry.py        (extra-field round-trip)
MODIFIED  engines/engine_a_alpha/edges/macro_credit_spread_edge.py
MODIFIED  engines/engine_a_alpha/edges/macro_real_rate_edge.py
MODIFIED  engines/engine_a_alpha/edges/macro_dollar_regime_edge.py
MODIFIED  engines/engine_a_alpha/edges/macro_unemployment_momentum_edge.py
MODIFIED  data/governor/edges.yml                       (4 macro tags)
MODIFIED  requirements.txt                              (hmmlearn>=0.3.0)
```

**Engine B unchanged.** Only Engine E and Engine A's macro-edge code
surface were touched. Engine A change is restricted to the 4 reclassified
macros' auto-register status string and `EdgeRegistry`'s extra-field
round-trip plumbing.
