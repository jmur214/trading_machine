# Primitive 3 — Regime-Aware Slot Reduction (DESIGN, awaiting user approval)

**Date:** 2026-04-30
**Branch:** `capital-allocation-fix`
**Status:** **DESIGN ONLY — no code shipped yet.** Engine B / Engine E touches require user approval per CLAUDE.md.

## Problem

`docs/Audit/oos_2025_decomposition_2026_04.md` showed that April 2025 — tagged `market_turmoil` for 239 of 453 fills (53% of April fills) — produced a single-month realized-PnL drawdown of **-$3,551**, with five edges (`low_vol_factor_v1` -$1,664, `atr_breakout_v1` -$827, `momentum_edge_v1` -$647, `gap_fill_v1` -$578, `panic_v1` -$161) taking simultaneous catastrophic losses. The portfolio engine's existing per-edge risk advisor is sized per-trade; nothing reduced the **count of concurrent open positions** when the macro regime classifier flipped to `market_turmoil`.

## What's already there

- `engines/engine_b_risk/risk_engine.py:472-507`: RiskEngine reads `advisory.suggested_max_positions` from Engine E and uses it via the `min(suggested, cfg.max_positions)` rule (advisory **can only tighten, never loosen** — already the right shape).
- `engines/engine_e_regime/advisory.py:192-201`: Engine E currently produces `suggested_max_positions` keyed off the **correlation axis** only:
  - `correlation == "spike"` → 8
  - `correlation == "elevated"` → 12
  - `correlation == "dispersed"` → 25
  - else (`normal`) → 18
- `engines/engine_e_regime/advisory.py:165-172`: Engine E also produces `regime_summary` keyed off `risk_score`:
  - `< 0.25` → `benign`
  - `< 0.50` → `cautious`
  - `< 0.75` → `stressed`
  - `>= 0.75` → `crisis` (the label that maps to the trade log's `market_turmoil` per Engine E's macro regime mapping)

The gap: `suggested_max_positions` doesn't move with `regime_summary`. April 2025's `market_turmoil` could co-occur with `correlation = normal`, in which case `suggested_max_positions` stayed at 18 — i.e., no reduction at all.

## Design

**Owner: Engine E (advisory.py).** Reasoning: this is a regime-aware advisory; Engine B already consumes the advisory correctly. Adding the rule on the producer side keeps the existing one-way "advisory tightens, RiskEngine enforces" contract intact. Putting the rule in Engine B would require Engine B to read the regime label directly and re-implement regime knowledge, which violates the existing separation.

**Single change point:** in `advisory.py`'s `suggested_max_positions` block (currently lines 192-201), apply a regime-summary floor on top of the existing correlation-state map. The minimum of the two values wins — preserving "advisory can only tighten."

```python
# Existing correlation-state map → suggested_max_positions
if corr_state == "spike":
    suggested_max_positions = 8
elif corr_state == "elevated":
    suggested_max_positions = 12
elif corr_state == "dispersed":
    suggested_max_positions = 25
else:
    suggested_max_positions = 18

# NEW Phase 2.10d Primitive 3: regime-summary floor.
# When regime_summary indicates stressed or crisis (which maps to
# market_turmoil in the trade-log labelling), cap concurrent positions
# at half of the cfg.max_positions ceiling. Floor takes the min of the
# correlation-state-derived value and the regime-summary-derived value
# so it can never loosen the existing advisory.
REGIME_TURMOIL_CAP = max(2, cfg.max_positions // 2)  # config-driven; default 5
if regime_summary == "crisis":
    suggested_max_positions = min(suggested_max_positions, REGIME_TURMOIL_CAP)
elif regime_summary == "stressed":
    suggested_max_positions = min(
        suggested_max_positions, max(2, int(cfg.max_positions * 0.7))
    )
```

The constants (`max_positions // 2` for crisis, `max_positions * 0.7` for stressed) are the cleanest defaults in the absence of empirical calibration. If the rule is too aggressive in OOS, the next iteration can move them.

### API

No public-API change. The advisory dict still carries `suggested_max_positions`; the value is just sometimes lower than before. No new field; no Engine B change required.

### Interaction with existing controls

1. **Sector caps + gross exposure** — independent. The regime cap reduces position **count**; sector cap reduces **same-industry concentration**; gross exposure caps **total dollars deployed**. They compose multiplicatively at the RiskEngine `min(...)` step.
2. **Existing correlation-state map** — preserved as-is. `min(corr_state_value, regime_summary_value)` means whichever is more conservative wins.
3. **`risk_advisory_enabled = false`** — the new rule is gated behind the same flag (existing config knob in `risk_settings.prod.json`). When disabled, the advisory is ignored and `cfg.max_positions` (currently 10) applies — same as today.

### In-flight positions on regime flip

**Block new entries only; do NOT close existing positions on regime flip.** Reasoning:
- The director explicitly endorsed this read: "only block new ones; closing on regime flip is its own bag of trouble."
- Memory `project_adverse_regime_stop_tighten_falsified` documents that retroactive stop-tightening on killed-regime positions loses to chop in the empirical 2024 measurement.
- RiskEngine's existing flow naturally implements this: when `_positions_count() >= effective_max_positions and current_qty == 0`, only **new** trades are blocked (line 503). Existing positions exit on their own per-trade SL/TP/exit signals.

### Unstress-down rule

**Symmetric and immediate.** The advisory is recomputed every bar; a regime that flips back to `cautious` or `benign` lifts the `regime_summary` floor immediately on that bar. No explicit hysteresis or cooldown — the `risk_score` itself is smoothed (Engine E's existing duration_factor logic), so a noisy single-bar flip won't cause a violent slot-count whipsaw.

This may need calibration after OOS measurement: if the regime label oscillates between `stressed` and `cautious` on adjacent bars and the system is opening/closing fewer/more slots on each flip, hysteresis could be added. Defer that until evidence.

### Default values

- `cfg.max_positions` (existing in `risk_settings.prod.json`): 10
- `crisis` floor: `max(2, max_positions // 2)` = 5
- `stressed` floor: `max(2, int(max_positions * 0.7))` = 7

April 2025 had 5 edges firing simultaneously into `market_turmoil`. With this rule active, only 5 concurrent positions could exist post-flip, and those 5 wouldn't all be entries — many would be carry-overs from the prior `benign` regime. **The constraint binds at the open-position level, so April's joint drawdown shape (5 simultaneous new entries into turmoil) becomes impossible.** Existing positions would still take their losses, but no new ones could open until the regime cleared.

## Risk

**The ~10% post-2.10b OOS Sharpe was -0.049, not deeply negative.** Adding a slot reduction in `crisis` won't move the average massively, but in months like April 2025 it directly avoids the new-entry pile-on. Expected effect: lower vol in crisis regimes, slightly lower CAGR (some good entries blocked), small Sharpe improvement.

**The rule is reversible.** A single config flag (`risk_advisory_enabled = false`) restores the prior behavior verbatim. The change is also idempotent across re-runs.

## Tests required if approved

1. Unit: `engines/engine_e_regime/test_advisory_regime_floor.py` — assert that for each `regime_summary` value, the floor is applied correctly and only tightens (never loosens) the existing correlation-state value.
2. Integration: smoke test in `tests/test_risk_engine_regime_floor.py` — synthetic regime flip to `crisis` with an existing 7-position book; assert RiskEngine refuses new entries until count drops below the floor.
3. Replay: a thin script that takes the 2025 anchor advisory record (per-bar regime labels) and counts how many bars `regime_summary == 'stressed'/'crisis'` co-occurred with `correlation_state == 'normal'/'dispersed'`. That number tells us how much the new floor would have bound in 2025 — pre-flight evidence the rule isn't a no-op.

## Open issues / decisions to flag

1. **Constants 0.5 and 0.7 are guesses.** They feel reasonable but are not empirically calibrated. Lower the bar in subsequent iterations if the evidence supports it. I am not proposing tuning these — the system should learn the right values via the lifecycle, but for the first cut they are static defaults.
2. **April 2025's `market_turmoil` regime tag is from the trade log, not the advisory dict.** It maps to Engine E's `crisis` summary via the macro_regime → regime_summary mapping. This needs verification before code: confirm the mapping path produces `regime_summary == 'crisis'` (or `stressed`) on the bars that carry the `market_turmoil` regime_label in the trade log. If the mapping is loose, the rule won't fire when it should.
3. **`risk_settings.json` doesn't currently expose a regime-floor knob.** I'm reading the constants off `cfg.max_positions`, which already exists; no new config schema needed. If we want different constants for `stressed` vs `crisis` in production, we can add `crisis_max_positions_pct: 0.5` later without breaking compatibility.
4. **Should the rule stack with Primitive 1 + 2?** Yes — they live at different layers (Primitive 1: per-bar single-edge attribution share, Primitive 2: per-edge weight ceiling for paused, Primitive 3: portfolio concurrent-position ceiling under crisis). Three orthogonal constraints; they compose. If all three bind in April 2025 simultaneously, it's the design working as intended.

## Recommendation

Approve the design as written. The implementation is ~15 lines in `engines/engine_e_regime/advisory.py`, no Engine B changes needed, no new config schema, and reversible via the existing `risk_advisory_enabled` flag. Ship to a separate commit on this branch once approved, with the three tests listed above.

If approval blocks, the alternative is **don't ship Primitive 3** for this Phase 2.10d task — Primitives 1 + 2 alone close two of the three structural defects identified in the 2025 decomposition, which is a substantial fraction of the win. The director can decide whether to wait for Engine E approval or merge what's done now.
