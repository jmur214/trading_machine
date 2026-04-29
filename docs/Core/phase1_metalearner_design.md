# Phase 1 Meta-Learner — Design Proposal

> **Status:** design draft for user approval before build.
> **Scope:** the largest single change in `forward_plan_2026_04_28.md` —
> per v2, "the highest-leverage one-week project remaining." Worth doing
> deliberately rather than rushed.

## What's already shipped (sets the ground)

This session shipped 4 of the 5 deferred items:

| Item | Status | Notes |
|------|--------|-------|
| 1. Wire RealisticSlippageModel | ✅ | qty plumbed end-to-end, default = realistic |
| 2. Run backtest under realistic costs | 🟡 in flight | running ~75% of the way through |
| 3. Multi-benchmark (SPY+QQQ+60/40) | ✅ | strongest-of-three is the new default gate |
| 4. Factor decomposition diagnostic | ✅ | reveals 2 real alphas, 5 factor-beta, 2 negative-alpha |
| 5. Phase 1 meta-learner | 🟡 partial | **Gate 6 (factor-alpha) shipped** as Phase 1 sub-item; combiner build is this doc |

The factor diagnostic produced a sharp signal:
- **2 real alphas** — `volume_anomaly_v1` (+6.1% alpha, t=+4.36), `herding_v1` (+10.1%, t=+4.49)
- **2 marginal** — `low_vol_factor_v1`, `macro_credit_spread_v1` (t≈+1)
- **2 significantly destroying value** — `atr_breakout_v1` (-3.8%, t=-3.28), `momentum_edge_v1` (-6.2%, t=-4.32). These are already paused; the t-stats *quantitatively validate* the lifecycle pause.
- **3 factor-beta** (t≤+1) — `pead_predrift_v1`, `gap_fill_v1`, `macro_dollar_regime_v1`

This means the meta-learner has a real signal mix to combine, not just factor exposure. **Phase 1 is justified.**

---

## Goal of the meta-learner

Replace `signal_processor.weighted_sum` (linear) with a non-linear
combiner that can capture interactions between edges and context. The
v2 doc's framing:

> The system isn't a few clever strategies. It's a factory that produces
> validated edges and a combination engine that figures out which mixtures
> of them work in which regimes.

A linear sum can't express "edge X is good only when regime is bull AND
edge Y disagrees." A gradient-boosted tree can.

## Three-tier edge taxonomy (prerequisite to combiner)

The combiner needs to know which edges are *alphas* (trade directly), which are *features* (input to the model), and which are *context* (regime modifiers). Add to `EdgeSpec`:

```python
@dataclass
class EdgeSpec:
    edge_id: str
    ...
    tier: Literal["alpha", "feature", "context"] = "alpha"
    combination_role: Literal["standalone", "input", "gate"] = "standalone"
```

Initial classification, based on factor-decomp results:

| Edge | Current | Proposed tier | Rationale |
|------|---------|--------------|-----------|
| `volume_anomaly_v1` | active | **alpha** | t=+4.36, real alpha |
| `herding_v1` | active | **alpha** | t=+4.49, real alpha |
| `low_vol_factor_v1` | paused | **feature** | marginal alpha; useful regime signal |
| `macro_credit_spread_v1` | active | **context** | regime modifier, low standalone alpha |
| `macro_real_rate_v1` | active | **context** | regime modifier |
| `macro_dollar_regime_v1` | active | **context** | t<0 standalone — clearly a modifier, not an alpha |
| `macro_unemployment_momentum_v1` | paused | **context** | regime modifier |
| `macro_yield_curve_v1` | paused | **context** | regime modifier |
| `pead_v1`, `pead_short_v1`, `pead_predrift_v1` | active | **feature** | event signals; small standalone alpha but information |
| `insider_cluster_v1` | active | **feature** | event signal |
| `gap_fill_v1` | active | **feature** | factor-beta-only |
| `rsi_bounce_v1`, `bollinger_reversion_v1` | active | **feature** | mean-reversion signals |
| `panic_v1`, `earnings_vol_v1` | active | **feature** | conditional signals |
| `atr_breakout_v1`, `momentum_edge_v1` | paused | **paused→retire** | -t > 2 confirms they should retire (already lifecycle-flagged) |

This is a **schema migration** — every edge in `data/governor/edges.yml`
gets a tier. Existing tier="alpha" default keeps current behavior; the
combiner only kicks in when at least one tier="feature" is in scope.

## Architecture

```
                 ┌── tier=alpha edges (2-5 of them) ──┐
                 │   Direct contribution to score     │
                 │                                    │
edge_scores ─────┤── tier=feature edges (~10-30) ─────┤── meta-learner ──→ ticker score [-1, 1]
                 │   Input to the meta-learner        │
                 │                                    │
                 └── tier=context edges (~5-10) ──────┤── modifies meta-learner output
                                                       │   (regime weight) ─┘
                                                       │
                                                       └─→ aggregator ──→ final score
```

Concretely, in `signal_processor.process()`:

```python
def process(self, raw_scores, regime_meta):
    # 1. Tier-A direct contributions (legacy linear sum, but only over alphas)
    alpha_score = sum(s * w for s, w in alphas_with_weights)

    # 2. Tier-B feature vector for the meta-learner
    feature_vec = build_feature_vector(raw_scores, regime_meta)
    if self.metalearner is not None and self.metalearner.is_trained():
        ml_score = self.metalearner.predict(feature_vec)
    else:
        ml_score = 0.0  # cold-start: no trained model yet

    # 3. Tier-C context as a regime modifier
    regime_mod = compute_regime_modifier(raw_scores, regime_meta)

    # 4. Combine
    combined = (alpha_score + ml_score) * regime_mod
    return clamp(combined, -1, 1)
```

## Choice of meta-learner library

| Option | Pros | Cons | Recommendation |
|--------|------|------|----------------|
| **scikit-learn** `GradientBoostingRegressor` | Already installed; no new dep | 5-10× slower than xgboost; less expressive | **First choice** — get the architecture in first, optimize later |
| **xgboost** | Industry standard for tabular; fast; good interpretability via SHAP | New dependency; some platforms have install friction | Migrate to this in a follow-up once architecture is validated |
| **lightgbm** | Fast; good with categorical features (regime labels) | New dependency | Strong second choice |

**Proposal:** ship with sklearn first. The training set is small
(~1000 days × ~15 features = 15K data points) so sklearn's speed is
fine. Switching to xgboost/lightgbm later is a one-line change in the
trainer if the architecture is right.

## Training pipeline (offline)

```
1. Walk-forward fold structure
   - Train: bars[0 : t]
   - Validate: bars[t : t + 60]   (held-out, never seen during training)
   - Refresh annually

2. Feature engineering
   - tier=feature edge scores at each bar (per ticker)
   - tier=context edge scores (regime indicators)
   - Optional: 1-day, 5-day, 20-day lags of each
   - Optional: cross-edge ratios

3. Adversarial features (Boruta-style)
   - For each real feature, generate a permuted twin
   - Real features must rank above their shuffled twins in importance

4. Feature selection
   - Lasso with cross-validation OR mutual information filter
   - Reduce ~30 features → ~10-15 useful inputs

5. Target = next-N-day forward return for the ticker
   (try N=1, N=5, N=20 in separate models — start with N=5)

6. Train the model on (selected features, target) pairs
   - sklearn GradientBoostingRegressor with reasonable defaults
   - Output a serialized .joblib model in data/governor/metalearner.pkl

7. Validate on held-out fold
   - Compute combined-model OOS Sharpe
   - Compare to the best single benchmark over the same window
   - Pass condition: OOS Sharpe > best_benchmark - margin AND t-stat > 2

8. Promote OR retain old model
   - If new model beats prior version on the held-out fold by a
     statistically-significant margin, promote
   - Otherwise keep prior (don't thrash)
```

## Inference pipeline (online)

Cheap path — at each bar, the trained model just runs `predict()` on
the current feature vector. No retraining inline. Latency budget: <10
ms per bar on the 109-ticker universe.

## What ships in the first build (proposed scope)

**Session N (this design's followup, ~1 day):**
1. Add `tier` and `combination_role` fields to `EdgeSpec`
2. Migration: classify all 14 active+paused edges per the table above; `data/governor/edges.yml` gets `tier:` populated
3. Build `engines/engine_a_alpha/metalearner.py`:
   - `MetaLearner` class with `fit(X, y)`, `predict(X)`, `save()`, `load()`
   - sklearn `GradientBoostingRegressor` backend
   - Cold-start fallback (returns 0.0 when not trained)
4. Build `scripts/train_metalearner.py`:
   - Reads tier=feature edge scores from a backtest's snapshots
   - Builds X, y from features + N-day forward returns
   - Walk-forward train/validate split
   - Saves model + validation report to `docs/Audit/metalearner_validation.md`
5. Tests for fit/predict, cold-start, and feature alignment

**Session N+1 (~1 day):**
6. Wire MetaLearner into `signal_processor.process()` per the architecture above
7. Held-out fold infrastructure (annual refresh)
8. Adversarial-features audit
9. Integration test: full backtest with the meta-learner active
10. Compare combined-model Sharpe vs the linear baseline

**Session N+2 (optional, ~1 day):**
11. SHAP-based per-trade attribution log (which features drove this trade?)
12. Migrate to xgboost or lightgbm if speed/expressivity becomes binding
13. Bayesian model averaging over multiple meta-learners (the v2 "Level 4" path)

## Risk and rollback

- **Default OFF on day 1.** New `signal_processor` config flag
  `metalearner_enabled: bool = False`. The combiner is opt-in.
- **A/B comparable.** With the flag off, behavior is identical to today.
  Easy to bisect any regression.
- **Cold-start safe.** If the model isn't trained yet, the meta-learner
  emits 0.0 and the system falls back to the linear sum over tier=alpha
  edges. No exception path that could mask a real bug.
- **Thrash-protected.** Promotion only when the new model beats prior
  by a statistically-significant margin on the held-out fold.

## Decisions needed from the user before build starts

1. **sklearn first vs xgboost first?** Recommend sklearn (no new dep,
   architecture in faster). Migrate to xgboost as follow-up.
2. **Forward-return horizon for the target?** N=5 as default; we can
   train multiple horizons and ensemble.
3. **Tier classifications above** — anything you'd reclassify? Especially
   the `paused→retire` recommendation for `atr_breakout_v1` /
   `momentum_edge_v1` (the lifecycle has 90-day-paused → retire path
   already; this just makes the retirement happen via the discovery
   gauntlet instead of waiting for elapsed-days).
4. **Held-out fold size?** Default 60 days, refresh annually. 252
   (full year) gives more validation but slower iteration.

Once you sign off on these four, the build can begin. Until then this
doc is the single source of truth for what the meta-learner is
supposed to do.
