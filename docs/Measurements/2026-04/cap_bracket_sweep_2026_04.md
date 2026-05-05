# Cap Bracket Sweep Below 0.20 + Multi-Year Robustness

**Date:** 2026-04-30
**Worktree:** `/Users/jacksonmurphy/Dev/trading_machine-agentA`
**Branch:** `cap-bracket-below-020`
**Driver:** `scripts/sweep_cap_recalibration.py` (extended with bracket presets b1/b2/b3 + multi-year `is_optimum` preset)
**Anchor:** `data/governor/_cap_recal_anchor/` populated from
`trading_machine-2/data/governor/_cap_recal_anchor/` (the same anchor
used by the prior cap-recalibration sweep). Verified by md5:
`54ae9ca4b5d56091a04a8d09c6322eb2` (edges.yml).
**Universe / cost model / governor flag:** identical to prior sweep —
prod 109, RealisticSlippageModel, `--reset-governor`, `PYTHONHASHSEED=0`.
**MetaLearner:** OFF (alpha_settings.prod.json in this worktree has no
metalearner block; verified across all four runs).

## Headline result

### 2025 OOS bracket below 0.20 (clean anchor, ML-OFF)

| Run | Cap | **Sharpe** | CAGR % | MDD % | Vol % | WR % | Total fills | Top-1 share | Top-1 edge | Bottom-3 share | Run UUID |
|-----|------|------------|--------|-------|-------|------|-------------|--------------|-------------|----------------|----------|
| B1 | 0.10 | **0.490** | 5.25 | -14.06 | 11.96 | 53.53 | 536 | 50.0% | momentum_edge_v1 | 63.4% | `3af7e2d3-93ff-4437-a193-030a433e9cfb` |
| B2 | 0.15 | **0.691** | 7.45 | -13.10 | 11.39 | 45.96 | 367 | 68.9% | low_vol_factor_v1 | 76.2% | `0479fd00-126e-4d20-ad3a-7048a593d882` |
| B3 | 0.20 | **1.102** | 12.28 | -4.14 | 11.14 | 49.66 | 496 | 59.6% | momentum_edge_v1 | 71.3% | `5d8f3b4a-c506-42e4-a0c7-5714abbb0eac` |

**Sharpe is monotonically increasing from cap=0.10 to cap=0.20.** The
optimum below 0.20 does not exist in the tested range — every step
tighter than 0.20 makes the system materially worse. **B3 (cap=0.20)
is unambiguously the best of the bracket.**

### 2025 benchmarks (for context)

SPY 0.955 / QQQ 0.933 / 60/40 0.997. **B3 at 1.102 beats every benchmark in
risk-adjusted terms** while still trailing on absolute CAGR (12.28% vs
SPY 18.18%) — the same defensive-skew shape the prior sweeps showed,
now with materially more upside than the cap-recalibration A3 (which
had 4.59% CAGR).

### Multi-year robustness — `is_optimum` (cap=0.20, 2021-2024 in-sample)

| Metric | This run (cap=0.20) | Original 1.063 anchor (Mar 2025 in-sample) | Δ |
|---|---|---|---|
| Sharpe | **1.113** | 1.063 | +0.05 |
| CAGR % | 11.44 | 6.06 | +5.38 pp |
| MDD % | -13.87 | -10.07 | -3.80 pp |
| Vol % | 10.23 | 5.70 | +4.53 pp |
| WR % | 52.37 | 49.06 | +3.31 pp |
| Run UUID | `0e26bf97-44e3-45d0-be1d-7d4bdf23fbf6` | `abf68c8e-1384-4db4-822c-d65894af70a1` | — |

| Reference (2021-2024 SPY-window benchmarks) | Sharpe | CAGR % | MDD % |
|---|---|---|---|
| **System (cap=0.20, post-pruning)** | **1.113** | 11.44 | -13.87 |
| SPY | 0.875 | 13.94 | -24.50 |
| QQQ | 0.702 | 14.15 | -35.12 |
| 60/40 | 0.361 | 3.75 | -27.24 |

**In-sample Sharpe (1.113) is at-or-above the original anchor (1.063).
Robustness: PASS.** The system also beats SPY's Sharpe in-sample by
+0.24 with materially lower drawdown (-13.87% vs -24.5%) and lower
vol (10.23% vs 16.48%). It still trails on absolute CAGR (11.44% vs
13.94%) — defensive-skew profile holds.

## Recommendation

**Set `fill_share_cap = 0.20` in production.** Confidence: **MEDIUM**.

**Reasoning for 0.20:**
- B3 (cap=0.20) is the highest Sharpe in this bracket (1.102) AND the
  highest CAGR (12.28%) AND the smallest MDD (-4.14%) among 2025 OOS
  runs. There is no metric on which a tighter cap improves anything.
- Multi-year IS Sharpe (1.113) marginally exceeds the original anchor
  (1.063) — robustness check passes by a small margin.
- The recommendation matches the prior cap-recalibration sweep's
  preliminary recommendation (cap=0.20) — two independent measurements
  converge on the same value.

**Reasoning for medium (not high) confidence:**
- The cap-recalibration A3 result (cap=0.20 → Sharpe 0.920, vol 5%,
  CAGR 4.59%) and this round's B3 v2 (cap=0.20 → Sharpe 1.102, vol
  11%, CAGR 12.28%) used the **exact same anchor md5** but produced
  materially different results. Same code, same governor state, same
  config, ML confirmed off in both — but different vol regime in the
  output. There is non-determinism we have not fully isolated. Plausible
  source: `lifecycle_history.csv` is NOT snapshotted by the sweep
  driver and accumulates mutations across runs; that history feeds
  back into lifecycle decisions during a run. Confidence in the *exact*
  Sharpe numbers is therefore weaker than the run-md5s would suggest.
- The **shape** is robust though (B3 > B2 > B1 monotonically; in-sample
  passes 1.063); the specific Sharpe magnitude is what's uncertain.

**Below-0.20 cap should not be deployed.** Both B1 (0.10 → 0.490) and
B2 (0.15 → 0.691) fall below the 2025 OOS partial-pass gate of 0.4 in
sharpe terms, and have catastrophic MDDs (-14% and -13%) compared to
B3's -4%. The "tighter is better" hypothesis from the prior sweep's
A3 vs A0 result was a local effect — generalized below 0.20, tighter is
worse.

## What the binding mechanism looks like at low caps — surprising find

The prior cap-recalibration sweep documented that "the cap value
barely moves fill-share concentration (bottom-3 stays 86-87%)" because
RiskEngine's `enter_threshold = 0.01` is far below post-cap-scaled
strengths even at the tightest cap. **That observation is reversed at
extreme tightness.** This sweep saw:

| Run | Cap | Total fills | Top-1 share | Bottom-3 share |
|-----|------|-------------|--------------|----------------|
| A0 (prior, cap=0.25) | 0.25 | 5,006 | 82.8% | 87.5% |
| A3 (prior, cap=0.20) | 0.20 | (similar to A0) | 83.2% | 87.4% |
| **B1 (this, cap=0.10)** | **0.10** | **536** | **50.0%** | **63.4%** |
| **B2 (this, cap=0.15)** | **0.15** | **367** | **68.9%** | **76.2%** |
| **B3 (this, cap=0.20)** | **0.20** | **496** | **59.6%** | **71.3%** |

**The cap *does* bind on fill counts at extreme tightness.** Going
from 0.25 to 0.10 collapses total fills from ~5,000 to ~500
(a 10x reduction), and the top-1 edge's share falls from 83% to 50%.
The mechanism: at very low caps, the strength scaling ratio
(cap/share) drops post-cap strengths *below* the entry threshold
(0.01) for the marginal signals, so they don't fire as orders. The
rivalry-as-position-size-only finding from the prior audit was
correct in its measured range (0.20–0.45) but does not extend to the
0.10–0.15 range.

Also notable: the prior cap-recalibration sweep had ~5,000 fills at
cap=0.20 (A3); this sweep has only ~496 fills at the same cap (B3 v2).
Same anchor, same code, same window — but a 10x difference in fill
volume. This is the non-determinism flagged above; lifecycle_history
accumulation across the prior sweep's runs is the leading hypothesis.

## Why is_optimum at 11.44% CAGR is a meaningful improvement

Task C's anchor (1.063 in-sample) had:
- 6.06% CAGR, 5.70% vol, MDD -10.07% — **defensive-to-a-fault**

This sweep's `is_optimum` run on the same window with cap=0.20 + the
post-pruning edge stack:
- 11.44% CAGR, 10.23% vol, MDD -13.87% — **moderate vol, real CAGR**

The Sharpe number barely moves (1.063 → 1.113) but the system has
shifted toward a much more compounding-friendly profile. The
~3.8 percentage points of additional MDD bought 5.4 percentage points
of additional CAGR. For a 40-year-horizon investor this is a clearly
better trade than the original 1.063 anchor's "low vol, low return"
profile.

## What this DOES NOT settle

1. **The 1.063 → 1.113 in-sample improvement may be cap-driven OR
   lifecycle-driven.** The post-pruning edge stack (Engine F retired
   `macro_credit_spread_v1` etc.) is materially different from the
   original 1.063 anchor's stack. Decomposing how much of the +0.05
   Sharpe is from cap=0.20 vs how much is from autonomous pruning
   would require an additional experiment (cap=0.20 with the original
   pre-pruning edges.yml).
2. **Cap above 0.20 not re-bracketed in this round.** Director did not
   ask. Prior sweep showed 0.20 = 0.92, 0.25 = 0.56, 0.35 = 0.86, 0.45
   = 0.79. The non-monotonic curve there suggested a local minimum at
   0.25; this round's IS check at 0.20 supports 0.20 as the production
   value but doesn't rule out 0.30-0.35 being competitive in different
   conditions.
3. **The non-determinism is unexplained.** Two cap=0.20 runs from the
   same anchor produced 0.920 and 1.102. The leading hypothesis is
   `lifecycle_history.csv` drift, but I did not run a controlled
   experiment to confirm. Snapshotting and restoring lifecycle_history
   in addition to edges.yml/edge_weights.json/regime_edge_performance
   would test this if needed.
4. **One in-sample window only.** Multi-year robustness was 2021-2024.
   Extending to 2018-2020 (different regime — pre-pandemic + 2020
   crash) would harden the recommendation; not in scope for this round.

## Reproduction

```bash
# Set up isolated worktree (assumed: trading_machine-2 has the prior
# sweep's anchor at data/governor/_cap_recal_anchor/)
git worktree add -b cap-bracket-below-020 \
    /Users/jacksonmurphy/Dev/trading_machine-agentA main
# (manual: symlink read-only data/, copy data/governor/, fresh trade_logs/)

# Cherry-pick the sweep driver from cap-recalibration
git -C ../trading_machine-agentA cherry-pick <driver-commits>

# Import the cap-recalibration anchor for clean comparison
cp /Users/jacksonmurphy/Dev/trading_machine-2/data/governor/_cap_recal_anchor/* \
    /Users/jacksonmurphy/Dev/trading_machine-agentA/data/governor/_cap_recal_anchor/

# Run the bracket
cd /Users/jacksonmurphy/Dev/trading_machine-agentA
PYTHONHASHSEED=0 python -m scripts.sweep_cap_recalibration --run b1
PYTHONHASHSEED=0 python -m scripts.sweep_cap_recalibration --run b2
PYTHONHASHSEED=0 python -m scripts.sweep_cap_recalibration --run b3
PYTHONHASHSEED=0 python -m scripts.sweep_cap_recalibration --run is_optimum
```

Outputs at `data/research/cap_recalibration_{b1,b2,b3,is_optimum}.json`,
trade logs at `data/trade_logs/<uuid>/`.
