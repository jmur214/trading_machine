# Lifecycle Counterfactual — 2025 OOS — Phase 2.10c precursor

**Date:** 2026-04-30
**Branch:** `lifecycle-counterfactual`
**Driver:** `scripts/run_oos_validation.py --task counterfactual`
**Question:** Did the 2026-04-24 lifecycle pause of `atr_breakout_v1` +
`momentum_edge_v1` cause the 2025 OOS underperformance documented in
`docs/Audit/oos_validation_2026_04.md`?

## Headline

**Counterfactual 2025 OOS Sharpe = +0.273** (vs Q1 anchor -0.049,
delta **+0.32**). Un-pausing the two momentum edges in a strong-trend
bull year raised Sharpe meaningfully but did not close the gap to
SPY (0.955) — by 0.68 Sharpe.

**Outcome bucket: 0 to +0.5 → "Pause helped a little, edges contribute
partial signal — Hybrid: refine lifecycle + run gauntlet."**

## Setup

- Mechanism: `temporarily_unpause()` in
  `scripts/run_oos_validation.py` patches
  `data/governor/edges.yml` `status: paused → active` for the two
  named edges, runs the backtest, then restores from backup.
  Lifecycle code untouched. Edges.yml restoration verified
  post-run (both edges back to `paused`).
- Window: `2025-01-01 → 2025-12-31`
- Universe: prod 109
- Cost model: `RealisticSlippageModel` (default in
  `config/backtest_settings.json`)
- Governor: `--reset-governor`
- `PYTHONHASHSEED=0`

## Results — side-by-side vs Q1 anchor

| Metric          | Q1 anchor (soft-paused 0.5x) | Counterfactual (un-paused, full weight 1.0) | Δ        |
|-----------------|------------------------------|---------------------------------------------|----------|
| **Sharpe**      | -0.049                       | **+0.273**                                  | **+0.322** |
| Total Return %  | -0.43                        | +1.41                                       | +1.84pp  |
| CAGR %          | -0.43                        | +1.42                                       | +1.85pp  |
| Max Drawdown %  | -6.48                        | **-3.09**                                   | +3.39pp better |
| Volatility %    | 5.65                         | 5.78                                        | +0.13pp  |
| Win Rate %      | 40.39                        | 41.94                                       | +1.55pp  |
| Trade count     | 5,498                        | 4,167                                       | -1,331   |
| Run UUID        | `72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34` | `a8c335a3-a014-4434-989b-1fda70f44481` | — |

### 2025 benchmark context (unchanged from Q1)

| Benchmark | Sharpe | CAGR%  |
|-----------|--------|--------|
| SPY       | 0.955  | 18.18  |
| QQQ       | 0.933  | 21.22  |
| 60/40     | 0.997  | 12.93  |
| **Counterfactual** | **0.273** | **1.42** |

The counterfactual still trails the strongest benchmark (60/40, 0.997)
by **-0.72 Sharpe** and SPY by **-0.68 Sharpe** in absolute return
terms. Un-pausing alone doesn't make this system competitive in 2025.

## Per-edge fill counts and PnL — counterfactual run

(Read from `data/trade_logs/a8c335a3-a014-4434-989b-1fda70f44481/trades_a8c335a3-a014-4434-989b-1fda70f44481.csv`)

| Edge                    | Fills | Realized PnL ($) | Notes |
|-------------------------|-------|------------------|-------|
| **momentum_edge_v1**    | 2,353 | **+315.84**      | un-paused; turned positive at full weight |
| **atr_breakout_v1**     | 1,712 | **-2,514.19**    | un-paused; still the largest single loser |
| macro_credit_spread_v1  | 53    | +243.01          | small contributor |
| volume_anomaly_v1       | 19    | -22.17           | factor-decomp "real alpha" — barely traded in 2025 |
| gap_fill_v1             | 14    | -11.12           | — |
| growth_sales_v1         | 8     | 0.00             | — |
| low_vol_factor_v1       | 4     | 0.00             | — |
| herding_v1              | 2     | +11.80           | other "real alpha" — also barely traded |
| macro_dollar_regime_v1  | 2     | +0.93            | — |

### Comparison to the Q1 anchor's per-edge contributions (same window, soft-paused)

| Edge                    | Q1 fills | Q1 PnL ($) | CF fills | CF PnL ($) | Δ PnL  |
|-------------------------|----------|------------|----------|------------|--------|
| momentum_edge_v1        | 2,203    | -883.23    | 2,353    | +315.84    | **+1,199** |
| atr_breakout_v1         | 768      | -2,229.07  | 1,712    | -2,514.19  | -285   |
| low_vol_factor_v1       | 1,613    | -2,532.67  | 4        | 0.00       | +2,533 |
| volume_anomaly_v1       | 191      | +1,933.73  | 19       | -22.17     | -1,956 |
| herding_v1              | 44       | +546.59    | 2        | +11.80     | -535   |

The two un-paused edges between them moved by **+$914** of realized
PnL on the year. But notice the second-order effect: `low_vol_factor_v1`
went from 1,613 fills + (-$2,533) PnL in Q1 down to 4 fills + $0 in
the counterfactual; `volume_anomaly_v1` and `herding_v1` (the
factor-decomp "real alphas") collapsed in fill count too.

This is the signal-processor sharing capital across active edges:
giving full weight back to the two largest momentum edges starves the
mean-reversion / factor-anomaly edges of capital. The system goes
from "diluted but diverse" (Q1) to "concentrated on un-paused
momentum, the rest are crowded out" (CF). The +0.32 Sharpe lift
mostly comes from `low_vol_factor_v1` no longer trading
(+$2,533) more than from `momentum_edge_v1` turning positive
(+$1,199).

## Honest commentary

**The pause hurt 2025 but the edge stack is the bigger problem.** The
+0.32 Sharpe gap between Q1 and the counterfactual establishes that
the soft-pause is not regime-aware: pausing two momentum-shaped edges
ahead of a strong-trend bull year cost ~0.32 Sharpe in 2025. So the
pause decision wasn't free.

But un-pausing alone gets the system to Sharpe 0.273 — still
underperforming SPY by -0.68 Sharpe over the same window, with
**less than a tenth of SPY's CAGR** (1.42% vs 18.18%). The
counterfactual is closer to the prior universe-B baseline (0.225)
than to anything that beats a benchmark. The "real alphas"
(`volume_anomaly`, `herding`) get crowded out as soon as the momentum
edges trade at full weight, suggesting the signal-processor's
ensemble allocation isn't capable of running both edge families
simultaneously even when both are active.

**Implication (per the four-outcome table):** outcome bucket #2 —
**hybrid: refine lifecycle + run full gauntlet.** Two work items, not
one:

1. Lifecycle redesign: the current pause logic conditioned on
   prod-universe 2021-2024 data alone — without regime-conditional
   evaluation it punished `momentum_edge_v1` for poor performance in
   periods that don't generalize. The pause needs to be regime-aware,
   or at minimum gate the decision on universe-B + held-out-window
   evidence (which Phase α v2 does not currently do). This dovetails
   with the active HIGH finding "regime-conditional activation
   net-negative across 3 splits" — we have the harness already
   (`scripts/walk_forward_regime`), it just isn't wired to the
   pause/revival side of the lifecycle.
2. Full gauntlet on all 18 edges remains required. Even un-paused,
   the system can't beat SPY in 2025; the "two real alphas"
   identified by factor decomposition (`volume_anomaly_v1`,
   `herding_v1`) barely fired in the counterfactual run (19 + 2 fills
   total). They need to clear the gauntlet under realistic costs on
   universe-B before any further claims about this system's alpha
   are credible.

**What this kills.** Nothing new — Phase 2.11 / 2.12 / 2.5 stay
🚫 BLOCKED per the 2026-04-29 forward plan. The counterfactual
result reinforces Phase 2.10c's "falsification triage" framing:
fixing only the pause is insufficient.

**What this enables.** A more focused next step than the original
"full standalone gauntlet" plan: the lifecycle subsystem itself is a
candidate for redesign before re-running the gauntlet, since the
gauntlet sweep is the long-pole step and we'd rather not re-run it
once the lifecycle changes. Suggested order: (1) regime-conditional
pause/revival gate, (2) gauntlet sweep with the new lifecycle in
place, in that order.

## Reproduction

```bash
PYTHONHASHSEED=0 python -m scripts.run_oos_validation \
    --task counterfactual \
    --unpause-edges atr_breakout_v1,momentum_edge_v1
```

Output at `data/research/oos_validation_counterfactual_2025.json`.
Trade log at `data/trade_logs/a8c335a3-a014-4434-989b-1fda70f44481/`.
The script backs up `data/governor/edges.yml` to
`edges.yml.counterfactual_bak` before mutation and restores it on
exit (success or exception).
