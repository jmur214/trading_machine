# Capital Allocation Fixes — Phase 2.10d Task B

**Date:** 2026-04-30
**Branch:** `capital-allocation-fix`
**Status:** Primitives 1 + 2 shipped with tests. Primitive 3 — design only,
awaiting user approval (touches Engine E advisory).

This audit documents the three structural primitives identified in
[docs/Audit/oos_2025_decomposition_2026_04.md](oos_2025_decomposition_2026_04.md)
as missing from the signal-processor / risk-engine capital-allocation
chain, plus before/after replay measurements on the 2025 anchor trade log.

---

## Primitive 1 — Per-edge fill-share ceiling

**Module:** `engines/engine_a_alpha/fill_share_capper.py` (new)
**Integration:** `engines/engine_a_alpha/alpha_engine.py:454-470, 815-825`
**Tests:** `tests/test_fill_share_capper.py` (13 tests, all pass)

### Design

Per-bar single-edge attribution share ceiling, applied AFTER per-ticker
attribution and BEFORE downstream governor / ML / RiskEngine sizing. For
any edge whose share of the bar's signals exceeds `cap`, strengths of
all its signals are scaled by `cap / actual_share`. Signal count is
preserved (no drops); only magnitude is reduced. RiskEngine's existing
`enter_threshold` filter applies organically to the post-cap strengths,
so if a strength falls below threshold no fill is produced — the
fill-count effect is downstream-emergent, not enforced here.

### Defaults and rationale

- **`fill_share_cap = 0.25`** — no edge gets more than 25% of the bar's
  signal budget. Chosen to be ~3.3× below the empirical 2025 bottom-3
  concentration (83%), and well above the natural 1/N share for the
  active edge count (~7% with N=14). It binds the dominant case
  without binding the well-distributed case.
- **`fill_share_min_signals = 4`** — cap inactive on bars with <4
  signals to avoid degenerate "1 signal = 100% share" cases.
- **`fill_share_cap_enabled = True`** — master switch; backwards-compat
  flip-off.

All three are `cfg_raw` knobs in `alpha_settings.{prod,dev}.json`; the
defaults are coded in alpha_engine init so an absent config falls back
to the documented values.

### Why proportional scaling, not drop?

Director's spec: "preserves all signals at smaller magnitude." Three
empirical advantages over dropping:
1. Information preservation: the directional opinion of the signal is
   retained; only its magnitude is reduced.
2. Exit-side correctness: a signal with `side="none"` (the bagholder
   fade-exit path in alpha_engine) can't be dropped without breaking
   exit logic. Scaling its strength to ~0 is benign.
3. Smoothness: a bar where one edge crosses the cap doesn't suddenly
   lose all its signals; the strengths shrink continuously.

### Test coverage

`tests/test_fill_share_capper.py`:
- `test_disabled_passes_through`
- `test_below_min_signals_passes_through`
- `test_invalid_cap_raises` (boundary check on cap value)
- `test_well_distributed_no_change` (4 edges × 5 = 25% each, no bind)
- `test_cap_scales_dominant_edge` (80/20 → scale to 0.3125)
- `test_cap_attaches_diagnostic_meta` (per-signal `meta.fill_share_cap`
  records `share_pre`, `scale`, `strength_pre`)
- `test_cap_preserves_signal_count`
- `test_cap_preserves_relative_strengths_within_capped_edge`
- `test_multiple_edges_over_cap` (40/40/20 → both 40s scaled to 0.625)
- `test_cap_handles_missing_edge_id` (defensive `_unknown` bucket)
- `test_post_cap_budget_share_equals_cap` (the budget invariant)
- `test_2025_style_dominant_momentum_capped` (5-edge synthetic)
- `test_2025_anchor_replay_concentration_bounded` (real trade-log
  replay; 194/195 entry-days binding)

### Measurement — 2025 Q1 anchor replay (cap=0.25)

Reproducible via `python -m scripts.replay_fill_share_cap_2025`. Reads
the Q1 anchor's `trades_72ec531d-...csv`, treats each entry-day's
attributions as a bar, runs the capper:

| Edge                    | Pre count | Pre share | Post strength | Post share (vs pre-total) |
|-------------------------|-----------|-----------|---------------|----------------------------|
| momentum_edge_v1        | 1,921     | 42.6%     | 1,059.7       | **23.5%**                  |
| low_vol_factor_v1       | 1,404     | 31.1%     | 1,045.5       | **23.2%**                  |
| atr_breakout_v1         | 544       | 12.1%     | 508.0         | 11.3%                      |
| macro_credit_spread_v1  | 218       | 4.8%      | 217.8         | 4.8%                       |
| gap_fill_v1             | 128       | 2.8%      | 72.8          | 1.6%                       |
| growth_sales_v1         | 116       | 2.6%      | 106.7         | 2.4%                       |
| volume_anomaly_v1       | 89        | 2.0%      | 84.5          | 1.9%                       |
| value_trap_v1           | 31        | 0.7%      | 31.0          | 0.7%                       |
| herding_v1              | 19        | 0.4%      | 19.0          | 0.4%                       |
| (others)                | 40        | 0.9%      | 40.0          | 0.9%                       |
| **TOTAL**               | **4,510** | **100%**  | **3,185**     | **70.6%**                  |

- **Bottom-3 capital-rivalry edges (momentum, low_vol, atr_breakout)
  pre-cap share: 85.8%.**
- **Bottom-3 post-cap budget consumption (vs pre-total): 57.9%.**
- 29.4% of total budget redistributed away from the dominant edges
  (4,510 → 3,185 strength units).
- Cap binds on **194 of 195 entry-days (99.5%)** — only one entry-day
  in 2025 had a sufficiently distributed signal mix that the cap
  didn't fire.

### Most surprising finding from the replay

**The maximum single-day single-edge share was 100%, on 2025-04-11,
edge = `low_vol_factor_v1`.** A whole day's worth of entry signals
were attributed to one paused edge. That's the dictionary definition
of capital rivalry expressed at extreme — and it happened in April
2025 right next to the `market_turmoil` regime cliff. The cap reduces
that day's `low_vol_factor_v1` budget contribution to 25%, freeing
75% of the day's budget for whatever else was firing (probably
nothing — only 4 entry-days had < 4 signals so the cap couldn't fire,
which means single-edge dominance was the rule, not the exception).

---

## Primitive 2 — Soft-pause weight ceiling

**Module:** `engines/engine_a_alpha/signal_processor.py:104-138, 392-403`
**Tests:** `tests/test_signal_processor_paused_cap.py` (7 tests, all pass)

### Design

`SignalProcessor.process()` already applies an initial soft-pause
weight cap in `mode_controller.py:837` via
`min(weight × 0.25, 0.5)`. The bug closed here: that initial cap is
the **starting weight**; the per-bar processing path then applies
further multiplications (regime_gate, learned_affinity) that can
push the effective weight back above the cap.

The fix: signal_processor receives `paused_edge_ids: Set[str]` and
`paused_max_weight: float` from alpha_engine (which reads the paused
set from EdgeRegistry in the same scan that already produces
regime_gates and edge_tiers). After every weight multiplication in
the per-bar loop, if `edge_name in paused_edge_ids and w > paused_max_weight`,
clamp `w = paused_max_weight`. The clamp is one-sided: it never lifts
weights below the cap (so the benign-regime suppression at 0.075 is
preserved).

### Test coverage

- `test_no_paused_set_does_not_clamp` (no-op default)
- `test_unpaused_edge_with_high_weight_not_clamped` (selectivity)
- `test_paused_cap_clamps_above_ceiling` (gate=2.0 amplifier → clamp)
- `test_paused_cap_does_not_inflate_low_weights` (one-sided)
- `test_2025_low_vol_factor_leak_closed` (reconstructs the 2025 case
  with a stacked `{benign:0.15, stressed:1.5, crisis:2.0}` adversarial
  gate)
- `test_paused_cap_invariant_across_all_regimes` (property test:
  20 random regime/raw combinations, w ≤ cap always)
- `test_paused_max_weight_is_configurable`

### What's NOT addressed by Primitive 2

The soft-pause cap value is still 0.5 — same as before. The leak fix
just enforces it as an absolute ceiling. If the cap value itself is
too generous (the audit recommended "0.1–0.2 would be honest soft
pause"), that's a config change, not a code change, and is
**deliberately not done here** — Agent B's autonomous-lifecycle work
on `lifecycle_manager.py` is the right surface for adjusting pause
semantics. Primitive 2 only closes the leak; the cap value is Agent
B's call.

---

## Primitive 3 — Regime-aware slot reduction (DESIGN ONLY)

**Status:** Design doc shipped at
[primitive3_regime_slot_reduction_design_2026_04_30.md](primitive3_regime_slot_reduction_design_2026_04_30.md).
**No code on this branch — awaiting user approval per CLAUDE.md.**

Touch surface: a ~15-line addition in
`engines/engine_e_regime/advisory.py:192-201` that adds a
`regime_summary`-floored `suggested_max_positions` (in addition to
the existing correlation-state map). RiskEngine already consumes
`advisory.suggested_max_positions` correctly via the
"can-only-tighten" rule, so no Engine B change is needed.

The design doc covers: API choice (no new fields), interaction with
existing sector caps + gross exposure, in-flight-position behavior on
regime flip (block new only — endorsed by director), unstress-down
rule (symmetric and immediate), default values
(`crisis = max(2, max_positions // 2) = 5`,
`stressed = max(2, int(max_positions * 0.7)) = 7`),
risk profile, the three required tests if approved.

If approved, the implementation can be a single commit on this
branch with the three tests inline. If declined, Primitives 1 + 2
already close two of the three structural defects.

---

## Open issues / decisions flagged

1. **`min_signals_for_cap = 4` may be too low.** With the 2025
   anchor showing the cap binding on 194/195 days, the cap is
   essentially always-on. That's the desired effect for the
   diagnosed pathology, but it means the cap is doing very heavy
   lifting in the strength chain. If a future bar genuinely *should*
   have 80% of signals from one edge (e.g. a real cross-sectional
   factor day where momentum signals are correctly broad), the cap
   penalizes it. Defer tuning until OOS evidence.

2. **The cap is uniform.** Every edge has the same 25% ceiling. It
   could be per-edge (e.g. let `volume_anomaly_v1` have a 35% ceiling
   because its per-fill avg is +$10.12, while `low_vol_factor_v1`
   gets a 10% ceiling because its per-fill avg is negative). I did
   not implement per-edge caps — the diagnosis is that we don't yet
   trust any edge's per-fill expectation enough to set differential
   caps, and a uniform cap is the safer default. If Agent B's
   lifecycle work surfaces credible per-edge expectations later,
   this is a clean follow-up.

3. **Primitive 2's cap value (0.5) is unchanged.** The leak is
   closed; the *amount* of soft-pause budget is Agent B's domain.
   The audit hypothesized 0.1–0.2 would be more honest; not pursued
   here.

4. **No backtest run.** Director instructed not to run a full
   backtest at the end of this task — that's task C, sequential
   after both branches merge. Pre-merge, the only behavioral
   evidence is the 2025 trade-log replay, which is not the same as
   running both fixes in a live backtest. The replay shows the
   constraint binds correctly per-day; whether it produces a Sharpe
   improvement requires the actual run.

5. **Engine B / Engine C deferred.** Per the original spec, this
   branch was scoped to `signal_processor.py` (Engine A) plus
   "Engine B/C touches via design proposal." Both ships honor that
   scope: Primitives 1 + 2 are pure Engine A; Primitive 3 is design
   only with Engine E identified as the natural owner.

## Reproduction

```bash
# Run all primitive tests
python -m pytest tests/test_fill_share_capper.py \
    tests/test_signal_processor_paused_cap.py -v

# 2025 Q1 anchor replay (Primitive 1 measurement)
python -m scripts.replay_fill_share_cap_2025
```
