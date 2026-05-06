# Cross-Asset Confirmation Gate — Archived 2026-05-06

Branch: `f1-lite-cac-archive`
Author: autonomous cycle (audit F1-lite)
Anchor commit: bp3-cac-archive worktree from main

## What moved

| Path (before) | Path (after) | Reason |
|---|---|---|
| `engines/engine_e_regime/cross_asset_confirm.py` | `Archive/engine_e_regime/cross_asset_confirm.py` | Falsified gate — TPR=0% on -5% drawdowns over 1086 days; default-off; never wired to Engine B |
| `scripts/run_ws_c_smoke.py` | `Archive/engine_e_regime/run_ws_c_smoke.py` | Smoke harness whose only job was flipping the now-archived `cross_asset_confirm_enabled` flag |

## What stayed

The three Foundry features that fed the gate are independent and remain
in production:

- `core/feature_foundry/features/hyg_lqd_spread.py`
- `core/feature_foundry/features/dxy_change_20d.py`
- `core/feature_foundry/features/vvix_or_proxy.py`

VVIX-proxy was the lone salvageable signal (AUC 0.64 in its valid window)
per `docs/Measurements/2026-05/regime_signal_validation_2026_05_06.md`,
and the other two are still cheap to compute and may yet be useful in a
re-scoped predictive panel. The 17 feature-level tests in
`tests/test_ws_c_cross_asset.py` continue to pass.

## Code changes

1. `engines/engine_e_regime/regime_detector.py`
   - Removed `_evaluate_cross_asset_confirm` helper (~80 lines).
   - Removed the call site inside `detect_regime` and the
     `_prev_hmm_state` tracker that only existed to feed the gate.
   - Removed the constructor block that initialised that tracker.

2. `engines/engine_e_regime/regime_config.py`
   - Removed the `CrossAssetConfirmConfig` dataclass.
   - Removed the `cross_asset_confirm` field on `RegimeConfig` and
     its hookup in `from_json`.

3. `tests/test_ws_c_cross_asset.py`
   - Truncated to the 17 feature tests (lines 1–393 of the old file).
   - Dropped 12 tests that exercised `confirm_regime_transition`
     directly (~240 lines). Those tests live with the archived module.
   - Updated module docstring to note the gate's archival and why the
     feature tests still belong here.

## Verification

- `pytest tests/test_ws_c_cross_asset.py` — 17 passed.
- `pytest tests/test_regime_detectors.py tests/test_regime_coordinator.py
  tests/test_advisory_regime_floor.py tests/test_discovery_regime_features.py`
  — 80 passed.
- `python -c "from engines.engine_e_regime.regime_config import RegimeConfig;
  RegimeConfig()"` — succeeds, and `RegimeConfig` no longer has a
  `cross_asset_confirm` attribute.
- `grep -rn "cross_asset_confirm\|CrossAssetConfirm\|confirm_regime_transition"
  --include="*.py"` outside `Archive/` returns no production hits. Doc
  hits remain in `docs/State/` as historical context — health_check.md
  finding is updated to RESOLVED in the same commit.

## Why now

`docs/State/health_check.md` (entry from 2026-05-06) flagged this as a
`[MEDIUM] soft-archive candidate` after regime-validation work showed
the underlying signals are coincident, not predictive. The audit-F1
brief categorised it as "misleading standing reference: 580+ LOC of
test for behavior never enabled." The dataclass and call site were
default-off and had zero production consumers; nothing wired into
Engine B reads the gate's output. Removing it tightens the engine
surface without changing any behavior.

## Behavioral impact

None. The gate was disabled by default on main, was never read by
Engine B, and the call site only ran when the flag was true. No
backtest, live, or paper path changes.

## Followups

- `docs/Core/Ideas_Pipeline/round_n_plus_1_dispatch_briefs.md:167`
  references the old function — leave as historical brief; the
  forward_plan note at line 49 already calls it "archive-pending".
- A scoped re-introduction is plausible only AFTER the predictive
  input-panel rebuild ships per `forward_plan.md` (VIX term, IV
  skew, put-call) — at which point a different gate is built, not
  this one revived.
