---
title: Dead-letter pattern audit — hunting for siblings of the T-054 production hunt() wiring bug
date: 2026-05-12
author: director (post-T-054 discovery, "bones must be PERFECT" directive)
status: director-side analysis (no agent dispatch); CLEAN result with one MEDIUM follow-up
---

# Dead-letter pattern audit — siblings of the T-054 wiring bug

## TL;DR — codebase is mostly clean; T-054 is contained, not a broader pattern

After Agent B surfaced the production `hunt()` ticker= wiring bug (T-054), the user's "bones must be PERFECT" directive demanded a broader audit: are there OTHER "registered but unreachable" code paths producing degenerate behavior in production?

**Audit result: largely clean.** The T-054 bug is contained — it's not the surface of a deeper systemic pattern. All checked engines (A, D, F partially) have callers that pass the necessary context to callees.

## What was checked

### Hunt 1 — Other `compute_all_features` call sites in Engine D ✅ CLEAN

Production call site grep:
```
engines/engine_d_discovery/discovery.py:130: ONE production site (the T-054 bug location)
engines/engine_d_discovery/feature_engineering.py:716: example/test in __main__ block
tests/*: 6 sites, all pass ticker= correctly
```

**Verdict**: The bug is genuinely a single-call-site fix per B's prediction. No sibling Engine D wiring gaps.

### Hunt 2 — Engine A `_metalearner_contribution` ticker= passing ✅ CLEAN

`engines/engine_a_alpha/signal_processor.py:540` correctly calls:
```python
ml_contribution = self._metalearner_contribution(edge_map, ticker=ticker)
```

The function signature at line 254 takes `ticker: Optional[str] = None` — same optional-pattern shape as the T-054 bug — but the production caller passes it explicitly. **No bug.**

### Hunt 3 — Active edge module-path resolution ✅ CLEAN

All 6 active edges in `data/governor/edges.yml` resolve to existing module files:
- gap_fill_v1 → engines/engine_a_alpha/edges/gap_edge.py ✓
- volume_anomaly_v1 → engines/engine_a_alpha/edges/volume_anomaly_edge.py ✓
- value_earnings_yield_v1 → engines/engine_a_alpha/edges/value_earnings_yield_edge.py ✓
- value_book_to_market_v1 → engines/engine_a_alpha/edges/value_book_to_market_edge.py ✓
- accruals_inv_sloan_v1 → engines/engine_a_alpha/edges/accruals_inv_sloan_edge.py ✓
- accruals_inv_asset_growth_v1 → engines/engine_a_alpha/edges/accruals_inv_asset_growth_edge.py ✓

**No missing-module dead-letter on actives.**

### Hunt 4 — `enabled: bool = False` config flags ✅ INTENTIONAL, not dead-letter

Twelve flags found across engines that default disabled. All are **intentional defense-first defaults**, not dead-letter:
- `engine_a_alpha/signal_processor.py:98` ml_settings.enabled (meta-learner intentionally off post-2026-05-01 falsification)
- `engine_f_governance/lifecycle_manager.py:88` cfg.enabled (lifecycle defense-first; flipped True for factor-α 2026-05-12 per T-043 ship)
- `engine_e_regime/regime_config.py:121` hmm_enabled (intentional post-T-015 WASH; jump-model is the future replacement per regime dive)
- `engine_e_regime/regime_config.py:171` multires_enabled (gated to multires HMM weekly/monthly models — Workstream B; deferred feature, gating code path exists at `regime_detector.py:_init_multires`)
- `engine_e_regime/regime_config.py:193` transition_warning_enabled (Workstream C slice 2; surfaces `regime_transition_warning` field; deferred feature, gating code at `regime_detector.py:_init_transition_warning`)
- `engine_b_risk/wash_sale_avoidance.py:37` enabled (intentional per 2026-05-02 multi-year falsification: Cell B destroyed 0.966 Sharpe in 2021)
- `engine_b_risk/risk_engine.py:83` drawdown_kill_switch_enabled (defense-first; T-012 narrow-except landed but flag stays off)
- `engine_b_risk/lt_hold_preference.py:52` enabled (intentional default-off)

**None of these are "registered but invocation-broken" — they're "deliberately off pending data/decision." Different category.**

### Hunt 5 — `'error'` and `'failed'` status edges in edges.yml — RESIDUE, not bug

20 'error' + 146 'failed' edges. Almost entirely Discovery-generated mutations (`_mut_XXXX` suffixed). These are the dead candidates from prior Discovery cycles — exactly what the failed-validation lifecycle is supposed to accumulate. Not bugs.

CAVEAT: per the T-054 bug discovery, those 146 "failed" mutations may have been GIVEN the wrong test (foundry_feature columns absent → trivial Gate 1 kill). Post-T-054, those failures should be re-evaluated to determine whether they failed for legitimate reasons. **Worth a one-time post-T-054 sweep**: take the 146 failed `_mut_` candidates, re-run their Gate 1 evaluation with foundry_feature columns now populated, see how many actually fail vs how many trivially-failed-due-to-bug. **Probably 100+ of them are bug-failed, not signal-failed.**

## ONE MEDIUM follow-up surfaced

### Engine E unbuilt-feature gates: legitimate "deferred work" or actual dead code?

Two Engine E config flags gate code paths whose existence I confirmed (`_init_multires`, `_init_transition_warning`) but whose downstream production VALUE is unclear:

- **multires_enabled**: Workstream B; weekly + monthly HMM models trained by `scripts/train_multires_hmm.py`. Per the 2026-05-06 memory entry: HMM is "coincident not predictive" — multi-resolution HMM may share the same fate. Worth verifying whether the models even exist on disk.

- **transition_warning_enabled**: Workstream C slice 2; produces `regime_transition_warning` field. Per the 2026-05-06 memory entry on WS-C: "WS-C is observability-only — flag enabled does NOT affect trades." If true for transition-warning too, this is observability-only and arguably dead in the trading decision path.

Neither is the T-054 bug shape (they're flag-gated, not silently broken). But both deserve a brief check: are the models present? Are the outputs consumed downstream?

**Filed as MEDIUM in health_check.md** rather than dispatched — the value of investigating is low until the user decides whether Engine E HMM work resumes (currently parked per "HMM is coincident, panel rebuild required" memory).

## What this audit DID NOT exhaustively cover

For completeness, things deferred to future audits:

1. **Engine C portfolio composer**: not checked. Per the 2026-05-07 memory entry, F4 charter inversion closed (HRP/Turnover relocated to engine_c). Worth a focused audit when Engine C work resumes.
2. **Engine B risk pipeline beyond the named flags**: not exhaustively walked. The killswitch-defeat bug from 2026-05-08 (TypeError silently swallowed) was the same bug-shape — silent degradation under specific input patterns. T-005 + T-011 + T-012 fixed the known bare-except sites but other silent-degradation paths may exist.
3. **Engine F lifecycle code paths beyond the factor-α gate**: not checked. The asymmetric-gauntlet bug (entry vs retirement) was caught by T-043; other asymmetries may exist.
4. **CLI scripts vs library imports**: not audited. A function imported from a library by a CLI may have a different default than the library expects.

## Recommendation

- **Single follow-up dispatch** post-T-054: re-evaluate the 146 'failed' `_mut_` candidates with foundry_feature columns now populated. Cheap (cached signal-collector replay per T-023 makes this fast). Tells us how many were bug-failed vs legitimately-failed. ~2-3 hr.
- **Defer broader audits** (Engine C, deeper Engine B, Engine F other paths) until those engines become next-touch work.
- The "bones must be PERFECT" directive is well-served by the T-054 fix landing soon (next ~2-4 hr) + the lifecycle factor-α gate ship + the Engine B vol-targeting ship. Those three together are the load-bearing bone-perfection moves in flight.

## Files

- This audit: `docs/Audit/dead_letter_pattern_audit_2026_05_12.md`
- Companion: `docs/Audit/pairwise_signal_correlation_phase0_2026_05_12.md` (Phase 0 signal-diversity)
- Companion: `docs/Audit/honest_n_mbl_computation_2026_05_12.md` (MBL data-window math)
