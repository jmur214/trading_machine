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

## Three-layer architecture: existence vs tier vs allocation

The deepest decision in this design is the **separation of three orthogonal questions**, each answered at a different layer. Conflating them is how systems develop "the model thinks I should kill X but the portfolio still wants it" pathologies.

```
                   ┌───────────────────────────────────────┐
Layer 1: EXISTENCE │ Is this edge real or noise?           │ ← OBJECTIVE / universal
                   │ Decides: alive vs retired              │   Machine-decided
                   └───────────────────────────────────────┘
                                    ↓
                   ┌───────────────────────────────────────┐
Layer 2: TIER      │ How does the system use this edge?    │ ← OBJECTIVE / universal
                   │ Decides: alpha vs feature vs context  │   Machine-decided from factor-decomp
                   └───────────────────────────────────────┘
                                    ↓
                   ┌───────────────────────────────────────┐
Layer 3: ALLOCATION│ Does THIS profile want it, & how much? │ ← SUBJECTIVE / config
                   │ Decides: capital weight per edge      │   Fitness-metric driven
                   └───────────────────────────────────────┘
```

**Profile changes** (e.g. switching from a low-vol/retiree profile to a high-CAGR/growth profile) affect **only Layer 3**. The same edge pool stays alive; allocation re-weights. An edge gets retired only for objective reasons (Layer 1), never because the current profile happened to dislike it.

This is also how multi-strategy quant shops operate: the firm has N strategies; each product re-weights them differently, but a strategy doesn't get killed because one product zero-weighted it.

### Layer 1: Existence (alive vs retired) — objective

Lifecycle gates use **profile-independent** metrics only:

- Factor-decomp t-stat consistently < -2 → significantly destroying value → retire-eligible
- 90+ days paused with no recovery → retire (existing rule, commit `1dca4a5`)
- BH-FDR insignificant across multiple test windows → no real signal → retire-eligible
- Charter-broken (crashes, NaN, integration drift) → retire

These are objective: a system retiring an edge under *any* profile would retire it under *every* profile.

### Layer 2: Tier (alpha / feature / context) — objective, autonomous

Tier classification is **automatic and recurring** based on factor-decomposition diagnostics. The system runs the diagnostic on a schedule (weekly or post-backtest); a scheduler reads each edge's t-stat, alpha%, and regime correlation and assigns:

```
if factor_tstat > 2 AND alpha_annual > 2%:
    tier = "alpha"          # standalone — trades directly
elif 0 < factor_tstat <= 2:
    tier = "feature"        # informative but not standalone — feeds the meta-learner
elif factor_tstat <= 0 AND |regime_correlation| > 0.3:
    tier = "context"        # regime modifier — modifies other edges' weights
elif factor_tstat < -2 AND days_negative >= 90:
    tier = "retire-eligible"  # routes to Layer 1 (lifecycle pause→retire)
else:
    tier = "feature"        # default — keep as input until enough data accumulates
```

**This rule supersedes any hand-classified table.** Add `tier` to `EdgeSpec` with a default of `"feature"`. An auxiliary process (call it `TierClassifier`, a Phase 1 module) runs the rule and updates the registry.

```python
@dataclass
class EdgeSpec:
    edge_id: str
    ...
    tier: Literal["alpha", "feature", "context"] = "feature"
    tier_last_updated: Optional[str] = None
    combination_role: Literal["standalone", "input", "gate"] = "input"
```

**Day 1 bootstrap:** the very first run of `TierClassifier` produces a snapshot from the current factor-decomp report. From that point forward the system self-maintains without human edits to `tier`.

### Layer 3: Allocation (how much capital) — subjective, config-driven

The fitness function is a **named profile** — a weighted combination of the metrics we always measure. Multiple profiles can coexist; switching is a config flip.

```python
@dataclass(frozen=True)
class FitnessConfig:
    name: str                       # "retiree", "growth", "balanced", etc.
    weights: Dict[str, float]       # e.g. {"calmar": 0.6, "sortino": 0.3, "sharpe": 0.1}
    # Optional profile-specific portfolio constraints:
    target_vol: Optional[float] = None
    max_drawdown_tolerance: Optional[float] = None
```

```yaml
# config/fitness_profiles.yml
profiles:
  retiree:
    weights: {calmar: 0.6, sortino: 0.3, sharpe: 0.1}
    target_vol: 0.05
    max_drawdown_tolerance: 0.10
  balanced:
    weights: {sharpe: 0.5, calmar: 0.3, cagr: 0.2}
    target_vol: 0.10
  growth:
    weights: {cagr: 0.5, sharpe: 0.3, calmar: 0.2}
    target_vol: 0.20
```

- Backtests, the meta-learner training target, and the allocation engine all **read the active profile's fitness function** rather than hardcoding Sharpe.
- Each edge's metrics are computed *once* (Sharpe, Sortino, Calmar, CAGR, MDD, hit rate by regime) and stored. The fitness function combines them at allocation time.
- Switching profiles re-weights without re-measuring.

This is the most important architectural decision in this entire doc. **It directly addresses the user feedback that Sharpe-only optimization limits the system.**

## Architecture

The combiner runs at Layer 3 (allocation). The tier assignments come from Layer 2 (autonomous factor-decomp classifier). Layer 1 (lifecycle/retirement) is upstream — by the time signals reach the combiner, retired edges are already gone.

```
                 ┌── tier=alpha edges (machine-classified, t > 2) ──┐
                 │   Direct contribution to score                  │
                 │                                                  │
edge_scores ─────┤── tier=feature edges (informative, 0 < t ≤ 2) ──┤── meta-learner ──→ ticker score [-1, 1]
                 │   Input to the meta-learner                     │   (trained against the
                 │                                                  │   active profile's fitness)
                 └── tier=context edges (regime modifiers) ────────┤── modifies meta-learner output
                                                                    │   (regime weight) ─┘
                                                                    │
                                                                    └─→ aggregator ──→ final score
```

Concretely, in `signal_processor.process()`:

```python
def process(self, raw_scores, regime_meta):
    # Tier assignments come from EdgeSpec, populated by TierClassifier
    alphas, features, contexts = split_by_tier(raw_scores, registry)

    # 1. Tier-A direct contributions (legacy linear sum, but only over alphas)
    alpha_score = sum(s * w for s, w in alphas)

    # 2. Tier-B feature vector for the meta-learner
    feature_vec = build_feature_vector(features, regime_meta)
    if self.metalearner is not None and self.metalearner.is_trained():
        ml_score = self.metalearner.predict(feature_vec)
    else:
        ml_score = 0.0  # cold-start: no trained model yet → fall back to alpha_score only

    # 3. Tier-C context as a regime modifier
    regime_mod = compute_regime_modifier(contexts, regime_meta)

    # 4. Combine
    combined = (alpha_score + ml_score) * regime_mod
    return clamp(combined, -1, 1)
```

The meta-learner's training target is **the active profile's fitness function applied to forward returns** — not raw forward returns. This means the model learns to optimize what the current portfolio profile actually wants.

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
1. Walk-forward rolling folds (NOT fixed 252-day blocks)
   - At each anchor date t:
       Train on bars[t-252 : t]    (1 year trailing window)
       Predict next N=5 days
       Roll anchor forward by 5 days; repeat
   - Continuous validation: every 5-day prediction is scored against
     realized returns as soon as those returns are available
   - This gives us:
       statistical power of a 1-year training window
       iteration speed of "see results in 5-20 days"
       no 4-month wait on every model change

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

5. Target = profile-aware forward score
   - Forward N-day return per ticker (N=5 default)
   - Pass through the active FitnessConfig's weighted metric so the
     model learns to optimize what THIS profile values, not raw return
   - Concretely: target_t = fitness_weights · [forward_sharpe_5d,
     forward_calmar_5d, forward_sortino_5d, forward_return_5d]
     using the rolling-window estimates over recent bars

6. Train the model on (selected features, target) pairs
   - sklearn GradientBoostingRegressor with reasonable defaults
   - Output a serialized .joblib model in data/governor/metalearner_<profile>.pkl
     (one model per profile; switching profiles loads a different file)

7. Continuous validation
   - Track 5-day predictions vs realized profile-aware target
   - Promotion gates fire as the rolling window accumulates evidence:
       30-day rolling MSE
       30-day rolling correlation with target
       30-day rolling Sharpe of acting on the model's predictions

8. Promote OR retain old model
   - If new model beats prior version on the rolling window by a
     statistically-significant margin (e.g. paired t-test p < 0.05
     on 30-day prediction errors), promote
   - Otherwise keep prior (don't thrash)
   - 252-day full-window validation is run periodically (quarterly) as
     a final stamp, but it's not the gating bar for promotion
```

## Inference pipeline (online)

Cheap path — at each bar, the trained model just runs `predict()` on
the current feature vector. No retraining inline. Latency budget: <10
ms per bar on the 109-ticker universe.

## What ships in the first build (proposed scope)

The build is decomposed into three sessions, each with an explicit gate. The user signs off after each session before the next starts. **No session skips ahead — Layer 1 / Layer 2 / Layer 3 build in dependency order.**

**Session N — Foundation (Layers 1 + 2):**
1. Add `tier`, `tier_last_updated`, `combination_role` fields to `EdgeSpec` (default `tier="feature"`).
2. Build `engines/engine_a_alpha/tier_classifier.py`:
   - `TierClassifier` reads factor-decomp report + lifecycle status, applies the rule from "Layer 2: Tier" above, writes back to `edges.yml`.
   - Idempotent: re-running with the same inputs produces the same output.
   - Logs every reclassification with the t-stat / alpha that triggered it.
3. Day-1 bootstrap: run `TierClassifier` once. The output snapshot becomes the system's tier state. From here on the system self-maintains.
4. Add `FitnessConfig` dataclass + `config/fitness_profiles.yml` with three named profiles (retiree / balanced / growth). Default profile = `balanced`.
5. Refactor `MetricsEngine.calculate_all` to also return Calmar, Sortino, and a `compute_fitness(profile)` helper that applies a `FitnessConfig`'s weights.
6. Tests: tier classifier rule correctness; fitness function weighting math; profile-flip leaves edge pool unchanged.

**Gate after Session N:** all 14 edges have machine-assigned tiers; switching the active profile changes allocation outputs but not which edges are alive.

**Session N+1 — Meta-learner (Layer 3 build):**
7. Build `engines/engine_a_alpha/metalearner.py`:
   - `MetaLearner(profile_name)` class with `fit(X, y)`, `predict(X)`, `save()`, `load()`
   - sklearn `GradientBoostingRegressor` backend
   - Trained on profile-aware forward target (per the training pipeline above)
   - Cold-start fallback (`predict` returns 0.0 when not trained)
8. Build `scripts/train_metalearner.py`:
   - Reads tier=feature edge scores from backtest snapshots
   - Builds X, y where y = active profile's fitness applied to forward returns
   - Walk-forward rolling folds with continuous validation
   - Saves model to `data/governor/metalearner_<profile>.pkl` + report to `docs/Audit/metalearner_validation_<profile>.md`
9. Adversarial-features audit (Boruta-style with permuted twins)
10. Tests for fit/predict, cold-start, feature alignment, profile-aware target.

**Gate after Session N+1:** trained meta-learner outperforms linear baseline on rolling-window evidence under the default profile.

**Session N+2 — Integration (Layer 3 wiring):**
11. Wire `MetaLearner` into `signal_processor.process()` per the architecture diagram.
12. New `metalearner_enabled: bool = False` config flag — opt-in for now.
13. Integration test: full backtest with meta-learner active under each of the 3 profiles.
14. Comparison report: meta-learner Sharpe vs linear baseline, all 3 profiles, all metrics.

**Gate after Session N+2:** under the `balanced` profile, meta-learner-active backtest produces strictly better fitness score than meta-learner-disabled. Under each other profile, the result reflects the profile's preferences (e.g. `growth` should produce higher CAGR but possibly lower Sharpe — that's success for that profile).

**Session N+3 (optional follow-on):**
15. SHAP-based per-trade attribution log
16. Migrate to xgboost or lightgbm if speed/expressivity becomes binding
17. Bayesian model averaging over multiple meta-learners (v2 "Level 4")

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

## Decisions — approved 2026-04-28

The original four questions and their resolved answers:

1. **sklearn first vs xgboost first?** ✅ **sklearn first.** No new
   dependency; architecture matters more than library; switching to
   xgboost later is ~5 lines once the design is proven.

2. **Forward-return horizon for the target?** ✅ **N=5 (one trading
   week).** Defer multi-horizon ensembling to Session N+3. Standard
   choice in the academic factor literature.

3. **Tier classifications?** ✅ **Made autonomous, not hand-set.** The
   user's principle "no manual edge tuning" applies. `TierClassifier`
   computes tiers from factor-decomp t-stats on a recurring schedule.
   The "day 1 snapshot" produced by the first run replaces what would
   have been hand-classifications. See "Layer 2: Tier" above for the rule.

4. **Held-out fold size?** ✅ **Walk-forward rolling folds, not fixed
   blocks.** 1-year trailing training window, predict next 5-20 days,
   roll forward. Continuous validation as the rolling window
   accumulates evidence. 252-day full validation is a quarterly stamp,
   not the gating bar — promotion happens on rolling evidence so we
   never wait 4 months on a model change.

A fifth decision surfaced in the conversation:

5. **Fitness metric — Sharpe-only or multi-metric?** ✅ **Multi-metric
   with config-driven profile selection.** All metrics measured on
   every edge always (Sharpe, Calmar, Sortino, CAGR, MDD, etc.). The
   active `FitnessConfig` profile (retiree / balanced / growth)
   determines how those metrics are weighted into a single fitness
   score for allocation. Layer 1 (lifecycle) uses objective metrics
   only; Layer 3 (allocation) uses the profile's fitness. **Switching
   profiles changes allocation, not which edges are alive.**

These five together fully specify the build. Sessions N → N+1 → N+2 can
proceed sequentially with explicit per-session gates as listed above.
