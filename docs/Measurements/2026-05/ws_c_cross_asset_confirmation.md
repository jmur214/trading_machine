# Workstream C — Cross-Asset Confirmation Layer

Generated: 2026-05-04
Branch: `worktree-agent-ac9e2f7857d411a04`
Authority boundary: Engine E DETECTS, Engine F/B ACT. This layer is
detection-only — no risk-policy effect on main.

## Summary

Three new Foundry features + one cross-asset confirmation function +
config-flag wiring for the regime detector. All defaults preserve main
behavior. The layer is observability-only this round; promotion to
risk-policy effect requires director approval after the multi-year
measurement (which is gait-conditional on this layer being merged).

## Three new Foundry features

| feature_id | source | meaning | data gap notes |
|---|---|---|---|
| `hyg_lqd_spread` | FRED `BAMLH0A0HYM2 - BAMLC0A0CM` | 60d z-score of HY-IG OAS spread (basis points) | **Substitute for HYG/LQD ETF ratio.** HYG_1d.csv and LQD_1d.csv are NOT in `data/processed/` (only SPY and TLT). The HY-minus-IG OAS captures the same credit-stress channel at index level. Series start 2023-04-25 → returns None before ~2023-07. |
| `dxy_change_20d` | FRED `DTWEXBGS` | 20d % change in trade-weighted broad USD index | **No gap.** Available 2006-present. Note: trade-weighted broad basket, not the futures-traded DXY; the two correlate ~0.95 in normal conditions. |
| `vvix_or_proxy` | FRED `VIXCLS` (derived) | 30d annualized realized vol of VIX log returns | **Substitute for CBOE VVIX**, which isn't in the macro cache. Realized (backward) substitute for an implied (forward) measure — empirical correlation with real VVIX is ~0.7 in published studies. Lags VVIX during fast regime turns. |

All three are **ticker-independent** (broadcast same scalar to every
name on a given dt) and tagged `tier="B"`. Model cards live at
`core/feature_foundry/model_cards/{hyg_lqd_spread, dxy_change_20d,
vvix_or_proxy}.yml` and document the gaps + substitutions explicitly.

The `@feature` decorator's advisory leakage scan ran on registration
and reported zero warnings. All three features pass adversarial-twin
generation (Foundry substrate compatibility) and ablation-runner
synthetic integration.

### Test surface

`tests/test_ws_c_cross_asset.py` — 27 tests, all passing.

- Per-feature: registration, closed-form math, ticker-independence,
  short-history (None) handling, NaN-hole handling (vvix), missing-leg
  handling (hyg_lqd).
- Substrate: twin generation, ablation, model-card validation.
- Confirmation function: 9 unit tests (the AND/OR logic, edge cases,
  None-signal handling, config override of thresholds, no-confirm-needed
  for exit-to-calm and no-transition).

## Cross-asset confirmation function

`engines/engine_e_regime/cross_asset_confirm.py`

Function `confirm_regime_transition(hmm_signal, cross_asset_state, config)`
returns `{confirm: bool, veto_reason: Optional[str], confidence: float}`.

### Logic

1. If the HMM transition is NOT into a stress state (no transition or
   exit-to-calm), return `confirm=True` immediately. Confirmation is
   required to ENTER stress, not to LEAVE it. Asymmetric on purpose:
   the cost of staying risk-on through a real crisis is much higher
   than the cost of staying risk-off through a confirmed-but-fading one.

2. If the HMM transition IS into a stress state, count how many of the
   three cross-asset signals also flag stress:

   - `hyg_lqd_z > +1.0` (default; configurable) — credit spread widening
   - `dxy_change_20d > +2%` (default; configurable) — USD risk-off rally
   - `vvix_proxy > 1.0` (default; configurable) — vol-of-vol stress

3. If at least 2 of 3 confirm → `confirm=True`. Otherwise
   `confirm=False` with `veto_reason="insufficient cross-asset confirmation"`.

4. `None` signals (e.g., `hyg_lqd_z` is None pre-2023-07) count as
   "not confirming." If ALL three are None, the transition is vetoed
   (belt-and-suspenders: don't grant confirmation when we have nothing
   to confirm with).

### Stress-state set

The default `stress_states = ("crisis",)` — only the highest-vol HMM
state requires confirmation. The intermediate "stressed" state is NOT
gated; we don't want to slow-walk acknowledgment of mid-tier risk-off,
where speed matters more than confirmation.

This is configurable via `cross_asset_confirm.stress_states` in
`config/regime_settings.json`, e.g. `["stressed", "crisis"]` to gate
both intermediate and worst-case transitions.

## Wiring

`engines/engine_e_regime/regime_detector.py` — when
`cfg.cross_asset_confirm.cross_asset_confirm_enabled = True` AND HMM
posterior is available, the gate is computed once per bar and surfaced
read-only at `advisory["cross_asset_confirm"]`. The dict includes raw
signal values for downstream diagnostic consumption:

```
{
  "confirm": bool,
  "veto_reason": Optional[str],
  "confidence": float,
  "argmax_state": str,
  "prev_state": Optional[str],
  "hyg_lqd_z": Optional[float],
  "dxy_change_20d": Optional[float],
  "vvix_proxy": Optional[float],
}
```

Engine B does **NOT** consume this field by default. Promotion to
risk-policy effect (e.g., damping `risk_scalar` when `confirm=False`,
or feeding into the regime-conditional wash-sale gate) is a
director-approved follow-up.

`_prev_hmm_state` is reset between backtest runs so determinism holds
across the harness.

## Smoke run

| File | Path |
|---|---|
| Driver | `scripts/run_ws_c_smoke.py` |
| Markdown summary | `docs/Audit/ws_c_smoke.md` |
| JSON results | `docs/Audit/ws_c_smoke.json` |

The smoke runs Cell A (cross_asset OFF, HMM OFF — current main) and
Cell B (cross_asset ON, HMM ON) for one calendar year × 3 reps each
under `isolated()`, snapshotting and restoring `config/regime_settings.json`
around each cell. See `docs/Audit/ws_c_smoke.md` for per-rep Sharpe,
canon md5, and the inter-cell delta.

### Caveat (binding)

The cross-asset gate is wired OBSERVABILITY-ONLY this round. The
expected and correct outcome is **identical Sharpe** between Cell A
and Cell B — a non-zero delta would indicate inadvertent leakage into
the live decision path and would block promotion. Bitwise determinism
WITHIN each cell (3/3 same Sharpe + 3/3 same canon md5) is the
non-negotiable pass criterion.

A single year of measurement is **not** sufficient to draw conclusions
about regime-conditional alpha. Statistical significance requires the
multi-year measurement (2021-2025) under the determinism harness, which
is gait-conditional on this layer being merged. Single-year smokes have
historically misled — see `project_wash_sale_falsified_multiyear_2026_05_02.md`,
where a 2025-only +0.670 Sharpe lift went to -0.966 in 2021.

## Smoke results (2024 × 3 reps both cells)

| Cell | Cross-asset | HMM | Sharpes | Range | Canon md5 unique | Bitwise det |
|---|---|---|---|---:|---:|---|
| A (baseline) | OFF | OFF | 1.8900, 1.8900, 1.8900 | 0.000000 | 1/3 | PASS |
| B (gated)    | ON  | ON  | 1.8900, 1.8900, 1.8900 | 0.000000 | 1/3 | PASS |

- **Cell A mean Sharpe: 1.8900**
- **Cell B mean Sharpe: 1.8900**
- **Delta (B - A): +0.0000**

All six runs across both cells produced the identical canon md5
(`96513df9703554bb7e7e6d6667bd7084`). This is the strongest possible
evidence that:

1. The wired path is deterministic (within-cell 3/3 PASS).
2. There is zero leakage of the gate output into the live decision
   path (across-cell delta = 0).

This is the expected and correct outcome for the observability-only
wiring this round. **A non-zero delta would have blocked promotion**;
zero delta is the green light for director review.

Caveat (binding): one calendar year is not statistical-significance
for any regime-conditional alpha claim. The multi-year measurement is
the next step, gait-conditional on this layer being merged.

## Acceptance gates

- [x] 3 cross-asset features pass tests (27/27 tests in
      `tests/test_ws_c_cross_asset.py`)
- [x] No leakage warnings on `@feature` registration
- [x] Confirmation function unit-tested (9 tests covering AND/OR logic,
      None-handling, config override, no-transition path,
      exit-to-calm path)
- [x] Model cards validate clean
- [x] Smoke runs both deterministic (3/3 bitwise per cell, identical
      canon md5 across all 6 runs)
- [x] `docs/Audit/ws_c_cross_asset_confirmation.md` documents feature
      sources / data gaps / confirmation logic / smoke caveats

## Hard constraints (verification)

- Default OFF on main: `RegimeConfig.from_json()` returns
  `cross_asset_confirm.cross_asset_confirm_enabled = False` when the
  block is absent from the JSON file. The shipped
  `config/regime_settings.json` does NOT include the block, so main
  behavior is bitwise unchanged. Verified.
- No modification to `data/governor/edges.yml` or anchor files.
  Verified — `git status` shows only feature additions and one config
  dataclass + detector wiring delta.
- Single-year smoke only. Verified — driver defaults `--year 2024`.
- `isolation: worktree` set by dispatcher. Working from
  `worktree-agent-ac9e2f7857d411a04`.

## Files added

```
core/feature_foundry/features/hyg_lqd_spread.py
core/feature_foundry/features/dxy_change_20d.py
core/feature_foundry/features/vvix_or_proxy.py
core/feature_foundry/model_cards/hyg_lqd_spread.yml
core/feature_foundry/model_cards/dxy_change_20d.yml
core/feature_foundry/model_cards/vvix_or_proxy.yml
engines/engine_e_regime/cross_asset_confirm.py
scripts/run_ws_c_smoke.py
tests/test_ws_c_cross_asset.py
docs/Audit/ws_c_cross_asset_confirmation.md
```

## Files modified

```
core/feature_foundry/features/__init__.py   # register 3 new features
engines/engine_e_regime/regime_config.py    # add CrossAssetConfirmConfig
engines/engine_e_regime/regime_detector.py  # wire gate (default OFF)
```
