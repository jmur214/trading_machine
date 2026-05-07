# C-engines-1 Determinism Follow-on + Audit-Geometry Note

**Status:** 2026-05-07 night verification per the C-engines-1 dispatch agent's caveat that their 3-rep determinism check ran on a worktree with incomplete governor state (zero-trade backtests).

## Verification result — PASSED bitwise

Re-ran the 3-rep determinism harness on `main` post-`cae2002` (post-merge of C-engines-1) with full governor state:

```
PYTHONHASHSEED=0 python -m scripts.run_isolated --runs 3 --task q1
```

| Rep | Sharpe | Canon md5 |
|---:|---:|---|
| 1 | 0.0 | (identical) |
| 2 | 0.0 | (identical) |
| 3 | 0.0 | (identical) |

`Sharpe range: 0.0000`. `Canon md5 unique: 1 / 3` → bitwise-identical.

**Conclusion:** the HRP+TurnoverPenalty relocation in C-engines-1 is byte-equivalent to the prior in-place version. Three reps producing identical output on populated main confirms the relocation didn't introduce any behavioral change.

## Surfaced finding (NOT a regression) — audit edge-status changes ↔ production-default config

All three reps produced **zero trades**, even on populated main with default config. This is independent of C-engines-1; it's a downstream consequence of the C-collapses-1 audit's edge-status changes.

### What changed in production state post-audit

The C-collapses-1 audit narrowed the active set from 9 → 6 edges:

| Active | tier |
|---|---|
| `gap_fill_v1` | feature |
| `volume_anomaly_v1` | **alpha** |
| `value_earnings_yield_v1` | feature |
| `value_book_to_market_v1` | feature |
| `accruals_inv_sloan_v1` | feature |
| `accruals_inv_asset_growth_v1` | feature |

Of the 6 surviving, only `volume_anomaly_v1` is `tier="alpha"` (standalone trade-producer). The other 5 are `tier="feature"` (research inputs that feed into the meta-learner).

`signal_processor.py:64-65` describes the architecture:

> The meta-learner combines tier=feature edge scores into a profile-aware contribution that ADDS to the legacy weighted_sum over tier=alpha edges.

But MetaLearner is currently default-OFF in production (per `project_metalearner_drift_falsified_2026_05_01.md`).

### What this means

Two paths in `mode_controller.run_backtest`:

1. **Default mode** (run_isolated, run_multi_year without `--exact-edges`): loads active+paused via `registry.list_tradeable()`. tier=feature edges still produce raw signals that feed weighted_sum. But the Q1 2025 result shows zero trades — suggesting that under reset_governor + the new active set, signal/threshold combinations don't fire enough to produce buy proposals.

2. **Audit mode** (`exact_edge_ids` parameter): pins exact edges, bypasses tier filtering. The audit's surviving-edges multi-year used this mode and produced 0.9154 mean Sharpe. The 6 surviving edges DO produce signals when run via exact_edge_ids.

**This is a measurement-geometry distinction, not a code defect.** The audit's 0.9154 was measured on a path that pins all 6 edges; production-default goes through `list_tradeable() + weighted_sum + tier-aware aggregation` which apparently produces a different (zero-trade) result on this specific 2025 Q1 window.

### What to investigate (next dispatch, not blocking)

1. **Reconcile the two paths.** Verify whether production-default produces non-zero trades on, e.g., a 2024 backtest (where the audit measured 0.582 Sharpe via `exact_edge_ids`). If 2024 production-default also produces zero trades, the gap is structural; if it produces real trades, 2025 Q1 is a window-specific signal-gap.

2. **MetaLearner re-enable becomes higher priority than originally framed.** With 5 of 6 surviving edges being tier=feature, the meta-learner is the path to production-using them. The 2026-05-01 falsification was on the substrate-conditional 9-edge baseline; that result is now stale. A substrate-honest re-attempt with the 6-edge surviving set is a candidate for C-engines-1.5 or sandwiched into C-engines-3.

3. **Tier-reclassification cycle worth running.** `tier_classifier.py` reclassifies edges based on factor decomposition. Running it on the substrate-honest surviving-edges trade logs may reveal that some currently-feature edges should be promoted to alpha (e.g., gap_fill_v1 had Δ=−0.620 standalone-on-historical, suggesting it's a viable standalone trader on the wider universe).

## Side-effect: minor harness bug surfaced

`scripts/run_isolated.py:246` reads `trades_<run_id>.csv` for canon md5 calculation. The cockpit logger writes `trades.csv` (single name) when there are no trades, OR both `trades.csv` AND `trades_<run_id>.csv` when trades exist. The canon md5 reports `(missing)` when only `trades.csv` exists.

Low-priority: filename pattern fix (~10 LOC) so the canon md5 always computes.

## Final commits state

- `cae2002` — C-engines-1 merge (F4 closure)
- `22dd9de` — corrections to forward_plan/drift inventory/lessons; A+C version bumps to 0.2.0
- (this note) — determinism verification + audit-geometry finding

C-engines-1 is verified clean. Engine completion sequence proceeds: C-engines-3 (Engine E minimal-HMM) is next, with the audit-geometry investigation as a sub-deliverable to scope the meta-learner re-attempt.
