# Path 1 Ship-State Validation — 2026-05

**Date:** 2026-04-30 / 2026-05-01
**Branch:** `path1-deployment-ship`
**Run UUID:** `bf9488a6-e682-4a49-8ff2-38917d178c8a`
**Config under test:** `metalearner.enabled: true`, `fill_share_cap: 0.20`,
all Phase 2.10d primitives active, RealisticSlippageModel, prod-109,
2025 OOS, `--reset-governor`, `PYTHONHASHSEED=0`.

## TL;DR — ship blocker found

**Validation Sharpe: -0.378.** The expected outcome (Sharpe 1.1+ from
cap=0.20 stacking on Agent C's 1.064 ML-on baseline) did NOT
materialize. **Do not merge `path1-deployment-ship` to main as-is.**
The config edit is correct; the measurement does not reproduce
the prior agents' headline numbers under the worktree's governor
state at run-time.

## Result vs four anchors

| Run | Cap | ML | Sharpe | CAGR % | MDD % | Vol % | Notes |
|-----|------|-----|--------|--------|-------|-------|-------|
| Phase 2.10d task C anchor | 0.25 | OFF | 0.315 | 1.41 | -2.68 | 4.86 | merged baseline |
| Agent A bracket B3 (round 2) | 0.20 | OFF | **1.102** | 12.28 | -4.14 | 11.14 | clean cap-recal anchor |
| Agent C portfolio-ML (round 1) | 0.25 | ON | **1.064** | (per audit) | (per audit) | (per audit) | metalearner-portfolio-enable |
| **This run (path1-ship)** | **0.20** | **ON** | **-0.378** | **-2.02** | **-5.25** | **5.10** | **expected 1.1+** |

Benchmarks over the 2025 window (unchanged): SPY 0.955, QQQ 0.933, 60/40 0.997.

## What happened — empirical decomposition

5,121 fills / 4,182 entries — **at the same fill scale as the original
Q1 anchor (5,498 fills, Sharpe -0.049)**, NOT the bracket B3 scale
(496 fills, Sharpe 1.102). The cap=0.20 + ML-on combination on this
worktree's governor state did not produce the "fewer trades, larger
positions" regime that B3 v2 demonstrated.

**Per-edge realized PnL (this run):**

| Edge | Entries | Realized PnL ($) | Notes |
|------|---------|------------------|-------|
| momentum_edge_v1 | 2,405 | **-3,607** | bottom-1 loser; same magnitude as un-paused-edge-v1 case |
| low_vol_factor_v1 | 1,427 | **-3,497** | bottom-2 loser; cap=0.5 soft-pause not enough |
| volume_anomaly_v1 | 102 | +1,298 | the alpha edge — held up |
| gap_fill_v1 | 63 | +1,198 | second alpha contributor |
| herding_v1 | 4 | +710 | very thin fill count |
| growth_sales_v1 | 94 | +67 | flat |
| pead_v1 | 18 | +39 | flat |
| panic / value_* / pead_short / pead_predrift | small | ~0 | inactive |
| **TOTAL** | **4,182** | **-3,765** | |

**Bottom-2 share: 92% of entries, -$7,103 of losses.** This is
indistinguishable from the original Q1 anchor's pathology — the
rivalry pattern that the structural fixes were supposed to bound. Yet
the cap was binding (`scale: 0.254` for momentum_edge_v1 in the trade
meta) and ML was loaded.

The cap is doing what it was designed to do (reducing momentum_edge's
strength to ~25% per fill); ML is loading from
`data/governor/metalearner_balanced.pkl` (md5 matches Agent C's
worktree). But the system is running at the original Q1 fill scale
producing losses similar to the original Q1.

## Why this differs from Agent A B3 v2 and Agent C

**Versus B3 v2 (cap=0.20, ML-off, Sharpe 1.102):** B3 v2 ran with 496
fills (10× fewer than this run). The `cap_bracket_sweep_2026_04.md`
documented that *exact* non-determinism — same anchor md5, same code,
same config produced 1.102 in agentA's worktree but 0.920 in
trading_machine-2's worktree. The leading hypothesis was
`lifecycle_history.csv` drift (which is NOT snapshotted by the sweep
driver and accumulates across runs).

**Versus Agent C 1.064 (cap=0.25, ML-on):** Agent C's run was on
their `metalearner-portfolio-enable` worktree at a specific point in
time with their own copy of `data/governor/`. Their copy may have had
different active-edge composition, different lifecycle_history, or a
different post-prune state than this worktree saw at run start. Their
audit reports the +0.749 Sharpe lift relative to the pre-fix
baseline; it does NOT independently measure cap=0.25 with this
worktree's governor state.

**The validation question** ("does cap=0.20 stack with ML-on for
Sharpe 1.1+?") cannot be answered with the data currently on disk
because no two recent runs at the same nominal config landed within
0.2 Sharpe of each other. The system is non-deterministic w.r.t.
non-snapshotted governor state.

## Recommendation

**Do NOT merge `path1-deployment-ship` to main with the current config.**

Two paths the director should consider:

### Path A — Investigate-and-reproduce-before-ship

Halt the ship. Add `lifecycle_history.csv` to the sweep snapshot, run a
controlled 3-replicate experiment at cap=0.20 ML-on under an explicit
clean anchor (the cap-recalibration anchor preserved at
`trading_machine-2/data/governor/_cap_recal_anchor/`). Only ship if
mean Sharpe across replicates is ≥ 0.5.

**Cost:** ~45 min × 3 runs + analysis. Discrepancy with Agent C
remains uninvestigated unless we also re-run their 1.064 anchor in
this worktree.

### Path B — Ship the safer half

Ship `fill_share_cap: 0.20` only. Leave `metalearner.enabled: false`
on main. The cap-only state (B3 v2 = 1.102 in agentA, A3 = 0.920 in
trading_machine-2) has a smaller variance band (~0.18 Sharpe spread)
and the central tendency is well above the partial-pass gate (0.4).
ML stacking is the new variable; deferring it doesn't sacrifice the
deployable state.

**Cost:** zero — the cap-only state is what the prior round-1
sweep already established. The "Phase 2.11 unblocks" framing in
forward_plan_2026_04_30.md based on Agent C's robustness audit
remains true at the *measurement-on-Agent-C-state* level; this
audit just shows the measurement is fragile across worktrees.

### Path C — Ship as-is and explain

Ship cap=0.20 + ML-on with the boundary doc explicitly noting that
ship-state Sharpe variance across worktrees is wider than expected
(observed range -0.378 to ~1.1) and the production deployment must
include lifecycle_history snapshotting before the next OOS run.

**Cost:** the merged config goes into production at higher uncertainty
than the audit history suggests. The 1.064/1.102 numbers were
measurement artifacts of specific governor states; production does
not reliably reproduce them.

**My recommendation: Path B.** Ship cap=0.20 alone now;
the ML stacking decision waits for a controlled-replicate study
that confirms Agent C's 1.064 reproduces under Path-1 governor state.
Path A is the more rigorous version if the director wants tomorrow's
ship to include ML.

## What would diagnose the gap

A controlled experiment comparing (1) Agent C's worktree governor at
cap=0.20 ML-on vs (2) this worktree's governor at cap=0.20 ML-on,
both pinned to identical lifecycle_history.csv. If the Sharpes still
diverge, the non-determinism is deeper than lifecycle_history (likely
in metalearner load order, model serialization, or a numerical
non-determinism the seed isn't covering). If they converge, the
bug is mechanical (snapshot the missing file).

## Reproduction

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-agentA
PYTHONHASHSEED=0 python -m scripts.run_oos_validation --task q1
# Output at data/research/oos_validation_q1.json
# Trade log at data/trade_logs/<UUID>/
```

Config in this worktree's `config/alpha_settings.prod.json`:
```json
"metalearner": {"enabled": true, "profile_name": "balanced", "contribution_weight": 0.1},
"fill_share_cap": 0.20,
```

## Caveats

1. The config edit (cap=0.20, ML=true) is correct and matches the
   spec. The validation Sharpe is the artifact, not the config.
2. The `data/governor/_cap_recal_anchor/edges.yml` md5 in this
   worktree differs from the trading_machine-2 anchor's md5
   (db202db2... vs 54ae9ca4...) — this is the same anchor-divergence
   issue documented in `cap_bracket_sweep_2026_04.md`. The director
   should treat anchor parity as a precondition for any future
   ship-validation run.
3. The lifecycle's end-of-run mutation revived `low_vol_factor_v1`
   from paused to active during this run (visible in
   `lifecycle_history.csv`'s last entries). That mutation does not
   affect this run's metrics (it fires after the backtest closes)
   but may affect the *next* run if reused without a re-anchor.
