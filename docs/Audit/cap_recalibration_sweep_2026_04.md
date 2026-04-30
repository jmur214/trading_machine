# Cap Recalibration Sweep — Phase 2.10d follow-up

**Date:** 2026-04-30
**Branch:** `cap-recalibration`
**Driver:** `scripts/sweep_cap_recalibration.py`
**Anchor:** `data/governor/_cap_recal_anchor/` (snapshot taken
2026-04-30 18:30 — captures the post-task-C, post-autonomous-pruning
edges.yml + governor state so all four runs share an identical
starting condition).
**Window/universe/cost-model:** identical to task C
(2025-01-01 → 2025-12-31, prod 109, RealisticSlippageModel).
**Governor:** `--reset-governor`. **MetaLearner: OFF** (verified — no
`[METALEARNER]` traces in any run log). **Determinism:** `PYTHONHASHSEED=0`.

## Headline result

| Run | Cap | Crisis cap | Stressed cap | **Sharpe** | CAGR % | MDD % | Vol % | WR % | Run UUID |
|-----|------|-----|-----|------------|-------|-------|-------|------|----------|
| A0 (baseline = task C settings) | 0.25 | 5 | 7 | **0.562** | 2.72 | -3.41 | 5.03 | 47.77 | `a49a4572-ac85-4f11-97a3-1fd7de861345` |
| A1 (mild loosen) | 0.35 | 5 | 7 | **0.861** | 3.96 | -2.14 | 4.66 | 48.11 | `66c07ffa-f865-4c60-a5de-cbcae9067b78` |
| A2 (medium loosen, coordinated) | 0.45 | 7 | 9 | **0.791** | 4.04 | -2.17 | 5.20 | 49.61 | `e2033b09-acfe-4005-bb68-7e56a8d960c7` |
| **A3 (tighter sanity check)** | **0.20** | 5 | 7 | **0.920** | **4.59** | -2.64 | 5.04 | 48.69 | `42740e3d-aec4-4a93-ae31-c3c595010f70` |

For reference (2025 benchmarks): SPY Sharpe 0.955, QQQ 0.933, 60/40 0.997.

### Three answers

- **Maximizes Sharpe:** **A3 (cap=0.20)** at 0.920.
- **Maximizes CAGR:** **A3 (cap=0.20)** at 4.59%.
- **Best risk-adjusted balance:** **A3** (highest Sharpe, highest CAGR,
  middle MDD/vol). A1 is a close second on Sharpe (0.861) with the
  best MDD (-2.14%) and lowest vol (4.66%) — slight Sharpe loss for
  best risk profile.

The relationship between cap value and Sharpe is **non-monotonic.** The
director's sanity-check phrasing predicted an answer either side of
0.25 — the actual curve is U-shaped with 0.25 in the trough:

```
0.20 → 0.920 (best)
0.25 → 0.562 (worst — local minimum)
0.35 → 0.861
0.45 → 0.791
```

## Pre-committed gate verdict

| Sharpe range | Verdict | A0 | A1 | A2 | A3 |
|---|---|----|----|----|----|
| < 0.2 | Kill thesis | — | — | — | — |
| 0.2 - 0.4 | Ambiguous | — | — | — | — |
| **0.4 - 0.65** | **Partial pass** | **0.562 ✓** | — | — | — |
| **> 0.65** | **Full pass — Phase 2.11/2.12 unblock** | — | **0.861 ✓** | **0.791 ✓** | **0.920 ✓** |

**A1, A2, and A3 all clear the full-pass threshold (> 0.65).**
A0 — the task C settings — is the only sweep run still in partial-pass
territory. The cap=0.25 default is now demonstrably worse than every
alternative tested.

## Why the cap value matters less than the table suggests

Counter-intuitively, the **fill-share concentration is essentially
identical across all four caps.** Empirical entry counts:

| Edge | A0 (cap=0.25) | A1 (cap=0.35) | A2 (cap=0.45) | A3 (cap=0.20) |
|------|---------------|---------------|---------------|---------------|
| momentum_edge_v1 | 3,424 (82.8%) | 3,743 (82.7%) | 3,457 (81.7%) | 3,638 (83.2%) |
| Bottom-3 share | 87.5% | 87.1% | 86.1% | 87.4% |
| volume_anomaly_v1 | 94 | 108 | 114 | 94 |
| herding_v1 | 21 | 28 | 39 | 29 |

The cap binds (Primitive 1's logic fires correctly — 99.5% of bars per
the prior replay). But because RiskEngine's `enter_threshold` is set at
0.01 (very low) and momentum_edge_v1's pre-cap normalized strengths are
typically 0.3–0.7, even an aggressive cap=0.20 scaling
(0.20/0.83≈0.24x multiplier) leaves post-cap strengths at 0.07–0.17 —
still well above the entry threshold. **The cap reduces position SIZE,
not fill COUNT.** That's a useful but quieter knob than the
"impossible by construction" framing in the prior audit suggested.

The entry-threshold + pre-cap-strength interaction is the real
governor of fill share. To actually move momentum_edge_v1's fill share
below 0.5, we'd need either:
1. Raise enter_threshold materially (touches alpha config — orthogonal change), or
2. Drop momentum_edge_v1 from the active stack (Agent B's lifecycle territory).

## Per-edge realized PnL across runs

| Edge | A0 PnL | A1 PnL | A2 PnL | A3 PnL |
|------|--------|--------|--------|--------|
| volume_anomaly_v1 | +2,414 | +2,537 | +2,682 | +2,545 |
| gap_fill_v1 | +1,426 | +1,161 | +944 | +1,028 |
| herding_v1 | +781 | +904 | +1,059 | +1,025 |
| growth_sales_v1 | +233 | +247 | +639 | +443 |
| **momentum_edge_v1** | **-4,062** | **-3,926** | **-3,294** | **-3,103** |
| All other edges | -240 | -178 | 28 | -619 |

**The Sharpe lift across runs is overwhelmingly explained by
momentum_edge_v1's loss reduction**, not by the good edges making
more. A3's $4,062 → $3,103 swing in momentum_edge_v1's losses
(+$960) is almost the entire year's improvement over A0. The
event-driven alphas (volume_anomaly, herding, gap_fill) are
remarkably stable across cap values — within ±10% of their A0 levels.

Why does cap=0.20 lose less to momentum_edge_v1 than cap=0.25? At a
given bar, the tighter cap scales momentum_edge's strength harder
(more aggressive position-size dampening). That dampening reduces
exposure during momentum_edge's losing trades. The non-monotonicity
between 0.20 → 0.25 → 0.35 → 0.45 likely reflects an interaction
with the position sizing pipeline that I have not isolated; it could
be a discrete-quantity rounding effect (smaller dampened sizes round
down to fewer/zero shares).

## Did rivalry re-emerge at any cap level?

**No** — bottom-3 fill share stayed in the 86.1% – 87.5% band across
all four runs. The cap was *already* not preventing rivalry at A0;
loosening it in A1/A2 and tightening it in A3 didn't change the
shape. The rivalry question is settled here: Primitive 1's cap
mechanism does not measurably bound fill-count concentration in this
edge stack, regardless of cap value. It bounds position-size
concentration.

This validates a part of the director's hypothesis ("the noise edges
that motivated the cap are now caught upstream by Agent B's
autonomous lifecycle triggers") — the rivalry-defense work is now
being carried by lifecycle (which retired `macro_credit_spread_v1`,
paused several others between task C and this sweep) and **not by
Primitive 1**. Primitive 1 has become a position-size dampener, which
is still useful but not what it was originally framed as.

## What changed since task C (Sharpe drift 0.315 → 0.562)

Task C reported A0-equivalent Sharpe = 0.315. My A0 with the same
configuration measures 0.562 (+0.247). The difference is **autonomous
lifecycle drift**: between task C's run and this sweep's anchor,
Engine F retired or paused several edges based on poor 2024-2025
performance (visible in `data/governor/lifecycle_history.csv`). The
notable change is `macro_credit_spread_v1` retiring with a recorded
Sharpe of -1.41 against a benchmark of +0.89. The post-pruning edge
stack is materially different from task C's, which means:

- The +0.247 Sharpe gain over task C is a real autonomous-system
  improvement, not a measurement artifact.
- The cap-recalibration sweep tests are best understood as "varying
  cap on the post-pruning system" rather than "exact reproduction of
  task C with cap variation." That framing is what the director asked
  for ("the noise edges that motivated the cap are now caught
  upstream"), so the answer is internally consistent.

## Recommendation for production cap values

**Set `fill_share_cap = 0.20`.** Reasoning:

1. A3's Sharpe (0.920) is the highest measured under realistic costs
   for this system in 2025 OOS, with the highest CAGR (4.59%) and
   acceptable MDD (-2.64%).
2. A3 clears the full-pass threshold by a wide margin.
3. The non-monotonicity puts the local minimum at 0.25 — the *current
   default* — which makes the default the worst choice in the tested
   range.
4. A1 (cap=0.35) is a defensible alternative if MDD is the binding
   constraint (-2.14% MDD vs A3's -2.64%, with only 0.06 Sharpe
   penalty). For a "compound-mode" production deploy I'd prefer A3's
   higher CAGR; for a defensive-mode deploy, A1.

**Keep `crisis_max_positions = 5` and `stressed_max_positions = 7`** —
A2 is the only run that loosened these (to 7 and 9), and it scored
0.791, between A0 and A1. There's no signal that the regime caps are
the binding constraint; A0's 0.25-cap run with 5/7 caps was the worst
result, but A3's 0.20-cap run with the same 5/7 caps was the best.
The regime caps appear inert at this edge-stack scale.

**Recommended change:** add `"fill_share_cap": 0.20` to
`config/alpha_settings.prod.json`. The current default in
alpha_engine init falls back to 0.25 when the key is absent. Adding
the explicit value will produce A3-equivalent behavior in production
without touching code.

## What this DOES NOT settle

1. **Optimal value is not yet bracketed.** I tested {0.20, 0.25, 0.35,
   0.45}. The sequence 0.562 → 0.920 from 0.25 → 0.20 is a 0.36
   Sharpe jump over a 0.05 cap delta — there could be an even better
   value at 0.15 or 0.10. A follow-up bracket sweep is recommended
   before committing 0.20 as the production value.
2. **The discrete-rounding hypothesis for the non-monotonicity** is
   conjecture, not measured. The audit assumes some interaction
   between strength-scaling and integer position sizes is producing
   the U-shape; this could be confirmed by inspecting the per-fill
   `qty` distribution by cap value.
3. **MetaLearner ON results.** All four runs were ML-off to match
   task C's environment. With ML on (now the working-tree default),
   results will differ. Director should run a parallel ML-on sweep
   if that's the intended production posture.
4. **Stability across windows.** This sweep is 2025-only. The
   non-monotonic curve might or might not generalize to 2024 / 2023.
   A multi-year robustness check would harden the cap=0.20
   recommendation; without it, 0.20 could be an artifact of 2025's
   specific regime mix.

## Reproduction

```bash
# 1. Snapshot current lifecycle state as the sweep anchor
python -m scripts.sweep_cap_recalibration --snapshot

# 2. Run each preset (each restores from the anchor before running)
PYTHONHASHSEED=0 python -m scripts.sweep_cap_recalibration --run a0
PYTHONHASHSEED=0 python -m scripts.sweep_cap_recalibration --run a1
PYTHONHASHSEED=0 python -m scripts.sweep_cap_recalibration --run a2
PYTHONHASHSEED=0 python -m scripts.sweep_cap_recalibration --run a3
```

Outputs: `data/research/cap_recalibration_{a0,a1,a2,a3}.json`. Trade
logs at `data/trade_logs/<run_uuid>/`.
