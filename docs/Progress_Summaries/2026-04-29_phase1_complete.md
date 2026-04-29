# Session Summary: Phase 1 Sessions N + N+1 + N+2 (2026-04-28 to 2026-04-29)

End-of-Phase-1 milestone. The three-layer architecture from
`docs/Core/phase1_metalearner_design.md` is now fully wired in code,
default-OFF and tested. Build sequence completed in three commits:

  Session N    foundation        commit 55d1ec6
  Session N+1  meta-learner      commit 82becfd
  Session N+2  integration       commit 0cd7960

## What was worked on

- **Session N — Foundation.** Added `tier`, `tier_last_updated`, and
  `combination_role` fields to `EdgeSpec` with write-protection in
  `EdgeRegistry.ensure()`. Built `core/fitness.py` with the
  `FitnessConfig` dataclass + 3 named profiles in
  `config/fitness_profiles.yml` (retiree/balanced/growth). Built
  `engines/engine_a_alpha/tier_classifier.py` — autonomous machine-
  classification of every edge's tier from factor-decomp t-stats. Day-1
  bootstrap on the realistic-cost backtest (run abf68c8e) tagged 2 edges
  as `alpha` (volume_anomaly_v1, herding_v1), 6 as `retire-eligible`
  (atr_breakout_v1, momentum_edge_v1, low_vol_factor_v1,
  macro_credit_spread_v1, macro_dollar_regime_v1, pead_predrift_v1),
  269 default-feature.

- **Session N+1 — Meta-learner.** Built
  `engines/engine_a_alpha/metalearner.py` (sklearn
  GradientBoostingRegressor backend, cold-start safe, feature
  alignment, target clipping, joblib serialization). Built
  `scripts/train_metalearner.py` (walk-forward rolling folds, profile-
  aware target). First training on the realistic-cost run produced
  Sharpe 0.671 train R², 51% positive OOS folds, +0.056 mean OOS
  correlation — weak portfolio-level signal.

- **Session N+2 — Integration.** Wired the `MetaLearner` into
  `SignalProcessor.process()` with a default-OFF flag and full
  cold-start / predict-failure fallbacks. Added `MetaLearnerSettings`
  dataclass, threaded the config through `alpha_engine.AlphaEngine`,
  and added an `edge_tiers` lookup so only `tier=feature` edges feed
  the model. Integration tests verify the layer-routing rule, schema
  stability, and graceful failure.

## What was decided

- **Default OFF until further validation.** Per the Phase 1 gate
  ("meta-learner-active backtest strictly better fitness than
  disabled"), the Session N+1 model trained on PnL-summary features
  doesn't compose with inference-time raw scores. Until Session N+1.5
  retrains on score-based features, the safe production state is
  `metalearner.enabled: false` in config. Cold-start safety means the
  flag can be flipped on at any time without code changes.

- **Layer 2 (tier) operates autonomously, not via hand-classification.**
  The user's "no manual edge tuning" principle dictates the
  classifier's reclassifications drive themselves from factor-decomp
  diagnostics on a recurring schedule. The day-1 snapshot is the only
  human-aligned step in the lifecycle.

- **Layer 1 (lifecycle) is profile-INDEPENDENT.** Edges retire only
  for objective reasons (factor t < -2, lifecycle 90-day-paused, etc.).
  Switching the active fitness profile changes allocation, not which
  edges are alive. Locked in by `test_classifier_does_not_import_fitness_module`
  — the AST-level test prevents future drift.

- **Three named profiles ship as the canonical set.** retiree
  (Calmar/Sortino-weighted), balanced (default — Sharpe/Calmar/CAGR),
  growth (CAGR-dominant). Custom profiles are loadable from any YAML
  via `load_profiles(path)`.

## What was learned

- **Portfolio-level features carry weak signal on this universe.** The
  Session N+1 trainer's mean OOS correlation of +0.056 is just above
  coin flip. This validates the design doc's prediction that
  "per-ticker training is the real lift" — at portfolio level, the
  meta-learner has too little information to rank profiles meaningfully.
  Per-ticker training (Session N+1.5) requires logging per-bar
  per-ticker edge scores during the backtest, which the current
  backtester doesn't capture.

- **Trainer-inference feature-shape drift is a real architectural
  concern.** The N+1 trainer used backward-looking PnL summaries
  (rolling-window means + active-day counts). At inference time
  (`SignalProcessor.process`), only the current bar's raw edge scores
  are available. These don't match. The cold-start + predict-failure
  fallbacks make this safe — the system silently falls back to legacy
  behavior — but the architectural fix is to retrain on
  inference-available features. Documented in the Session N+2 commit
  message and in the meta-learner design doc.

- **Three-layer separation cleanly resolves the user's profile-flip
  concern.** The architectural property "switching profiles re-weights,
  doesn't kill edges" is now enforced by:
    Layer 1 (objective) — lifecycle retires only on objective metrics
    Layer 2 (objective, autonomous) — tier classification reads
      factor-decomp, never reads FitnessConfig (AST-test enforced)
    Layer 3 (subjective, config) — only the meta-learner's training
      target and the allocation engine read the active profile
  The user's intuition about "different profiles needing different
  metrics" is correct and the architecture supports it cleanly without
  edges getting deprioritized into retirement.

## Pick up next time

- **Session N+1.5 — feature-shape fix.** Build a second trainer that
  uses inference-available features (raw current edge scores per bar).
  Either:
    (a) Modify alpha_engine to log per-bar per-ticker edge scores
        during backtests (data architecture change), then train
        per-ticker, OR
    (b) Train at portfolio level using current-bar raw scores
        aggregated per edge (less informative but immediately
        compatible with the inference path)
  Option (b) is the cheaper bootstrap; (a) is the long-term right move.
  Decision needed before starting.

- **Wire factor-decomp diagnostic into the discovery loop.** Gate 6
  already runs per-candidate; the day-1 TierClassifier bootstrap should
  be triggered automatically as a post-backtest hook. Currently it's a
  manual one-shot (`PYTHONPATH=. python -c "from
  engines.engine_a_alpha.tier_classifier import TierClassifier; ..."`).

- **A/B comparison once N+1.5 ships.** Run the same backtest under each
  of the three profiles with `metalearner.enabled: true`. Compare
  fitness scores. Confirm: retiree-profile model produces lowest-vol
  output, growth-profile model produces highest-CAGR output, all from
  the same edge pool.

- **Persist day-1 tier snapshot to git.** The current `edges.yml` has
  the post-bootstrap tiers but is gitignored
  (`data/governor/edges.yml`). Consider snapshotting it to
  `docs/Audit/edges_tier_snapshot_<date>.md` for history.

## Files touched

```
config/fitness_profiles.yml                          (NEW — 3 named profiles)
core/fitness.py                                      (NEW — Layer 3 helper)
engines/engine_a_alpha/edge_registry.py              (tier fields + write-protection)
engines/engine_a_alpha/tier_classifier.py            (NEW — Layer 2 autonomous)
engines/engine_a_alpha/metalearner.py                (NEW — Layer 3 meta-learner)
engines/engine_a_alpha/signal_processor.py           (MetaLearnerSettings + integration)
engines/engine_a_alpha/alpha_engine.py               (config wire-through)
scripts/train_metalearner.py                         (NEW — offline trainer)
docs/Audit/metalearner_validation_balanced.md        (validation report)
data/governor/edges.yml                              (post-bootstrap tier state)
data/governor/metalearner_balanced.pkl               (trained model)

tests/test_fitness.py                                (NEW — 22 tests)
tests/test_tier_classifier.py                        (NEW — 16 tests)
tests/test_metalearner.py                            (NEW — 20 tests)
tests/test_signal_processor_metalearner.py           (NEW — 11 tests)
```

Total new test coverage: 69 tests across the three sessions. Full
suite runs at 637 passing, 3 skipped, 6 pre-existing failures (no new
regressions).

## Subagents invoked

None. Phase 1 was a focused architectural build; the Phase 0 work
earlier this week used edge-analyst, engine-auditor, and code-health
subagents extensively. Their memory files remain in
`.claude/agent-memory/` for future sessions.
