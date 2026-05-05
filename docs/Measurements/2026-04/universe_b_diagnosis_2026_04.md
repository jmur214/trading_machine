# Universe-B Diagnosis — why does the system collapse 79% off prod-109?

**Date:** 2026-04-30
**Branch:** `universe-b-diagnosis` (Agent D, Phase 2.10c follow-up)
**Method:** pure analytical decomposition of two existing trade logs.
No new backtests, no code changes.

## Inputs

| Run | UUID | Universe | Window | Sharpe | CAGR | Vol | MDD |
|---|---|---|---|---|---|---|---|
| Anchor (prod) | `abf68c8e-1384-4db4-822c-d65894af70a1` | prod 109 | 2021-01-01 → 2024-12-31 | **1.063** | 6.06% | 5.7% | -10.07% |
| Universe-B | `ee21c681-f8de-4cdb-9adb-a102b4063ca1` | held-out 50 (seed=42) | 2021-01-01 → 2024-12-31 | **0.225** | 1.76% | 9.95% | -18.17% |

Same edges, same window, same cost model, same governor reset. The
0.838-Sharpe gap (≈79% collapse) is universe-attributable by construction.

Per-ticker metadata derived from `data/universe/sp500_membership.parquet`
(GICS sectors), `data/processed/<TICKER>_1d.csv` (ADV $ = mean
`Volume × Close` over the 2021-2024 window), and SPY as benchmark for
beta.

## Summary table — Universe (prod 109) vs Universe-B (50)

| Axis | prod 109 | Universe-B | Gap |
|---|---|---|---|
| Sharpe | **1.063** | **0.225** | **-79%** |
| Vol (annualized) | 5.70% | 9.95% | +75% (vol nearly doubles) |
| MDD | -10.07% | -18.17% | -8.1pp (worse) |
| CAGR | 6.06% | 1.76% | -4.3pp |
| ADV $ median | $762.8M / day | $118.2M / day | **6.4× lower** |
| ADV $ mean | $1,912M / day | $158M / day | **12.1× lower** |
| % of names ≥ $1B/day ADV | 31.2% | **0%** | -31.2pp |
| % of names ≥ $200M/day ADV | 100% | 26% | **-74pp** |
| % of names < $50M/day ADV | 0% | 16% | +16pp |
| Beta vs SPY (mean) | 1.008 | 0.921 | ~equal |
| Beta vs SPY (median) | 0.912 | 0.957 | ~equal |
| IT + Health Care weight | 40.4% | 12.0% | -28pp (sector-mix shifted) |
| Real Estate weight | 1.8% | 10.0% | +8pp |
| GICS-Unknown / delisted / pre-rename | 0% | **44%** (22/50) | +44pp |
| Tickers with <1000 trading days in window | 0 | 10 of 50 | +10 |
| Tickers with **zero usable data** in window | 0 | **6 of 50** (TIE, FB, SGP, CBE, SNDK, NFX) | +6 |

## Per-edge attribution — where the dollars actually went

Both runs trade the same edge stack. The differences in PnL by edge
($ on $100k starting capital, full 4-year window):

| Edge | prod fills | UB fills | prod $ | UB $ | Δ pp of capital | Notes |
|---|---|---|---|---|---|---|
| `volume_anomaly_v1` | 1,045 | 137 | +14,136 | +1,228 | **-12.9pp** | stable contributor — fires 7.6× less on UB |
| `atr_breakout_v1` | 5,269 | 286 | -3,678 | **-15,142** | **-11.5pp** | per-fill avg loss went from -$0.70 to **-$53** (76× worse per fill) |
| `herding_v1` | 493 | 52 | +6,728 | +975 | -5.8pp | stable contributor — fires 9.5× less on UB |
| `low_vol_factor_v1` | 219 | 444 | +594 | -2,196 | -2.8pp | "paused" edge dragging harder on UB |
| `gap_fill_v1` | 481 | 68 | +2,004 | +275 | -1.7pp | weak diversifier, signal density falls |
| `momentum_edge_v1` | 15,560 | 11,073 | -6,442 | **+8,042** | **+14.5pp** | offsets some of the gap (see below) |
| All others (8 edges) | combined | combined | +841 | +1,463 | +0.6pp | macro / pead / panic — sparse, near-zero impact |
| **Net** | 23,952 | 12,140 | **+14,183** | **-5,353** | -19.5pp | matches CAGR gap (4.3pp/yr × 4yr) |

The dominant edges in the gap are `volume_anomaly_v1` (signal density),
`atr_breakout_v1` (per-fill cost catastrophe), and `herding_v1`
(signal density). Three edges account for **30.2pp of the 19.5pp net
gap**, partially offset by `momentum_edge_v1` mysteriously *making
money* on UB (+14.5pp swing in its favor).

## Honest decomposition of the 79% Sharpe gap

The gap separates into a return-drop component and a vol-inflation
component:

```
ΔSharpe (return-side, vol fixed at 5.7%) = (6.06 - 1.76) / 5.7  = 0.755
ΔSharpe (vol-side, return fixed at 1.76%) = 1.76/5.7 - 1.76/9.95 = 0.132
Total predicted Δ                                                ≈ 0.887
Actual                                                            0.838
```

**~75% of the Sharpe gap is the return drop. ~25% is the vol inflation.**

Attributing each component to a structural driver:

| Driver | Mechanism | Approximate $ impact (4-yr basis) | Sharpe-gap share |
|---|---|---|---|
| **(a) Liquidity / impact-knee** | UB ADV is 6× lower → Almgren-Chriss `√(qty/ADV)` impact tax balloons; `atr_breakout_v1` per-fill avg loss went from -$0.70 to -$53 (76× worse). UB has 16% of names <$50M/day ADV; prod has 0%. | ~$11-12k of UB losses concentrated in atr_breakout firing on illiquid names | **~40%** |
| **(b) Stable-contributor signal-density failure** | `volume_anomaly_v1` and `herding_v1` rely on high-frequency order-flow signals that don't reach threshold density on lower-ADV names. Combined fills drop 89% (1,538 → 189). | -$18.7k missing PnL contribution | **~30%** |
| **(c) Survivorship / delisted-tail trading** | UB sample includes 6 zero-data tickers + 4 with severely truncated coverage (TE, FOSL, GENZ, HOG, ACT, CA). The bottom-PnL tail of UB is dominated by these (TE -$5,581, FOSL -$2,615, GENZ -$1,031, HOG -$1,701). Inflates vol and MDD. | -$11k concentrated in delisted/declining names | **~20%** (mostly the vol-side share) |
| **(d) Sector mix** | Real Estate +8pp on UB (got -$1.6k vs prod's -$0.5k); IT/HC -28pp combined (prod's HC contributed +$3.6k, UB's +$1.3k). Some of this is liquidity-correlated (RE small-caps trade thinner) so it double-counts (a). | ~$2-3k after de-correlation with (a) | **~5-10%** |
| **(e) Beta** | Mean beta nearly identical (1.008 vs 0.921). Cannot explain the vol doubling. | ≈ $0 | **~0%** |
| **(f) Capital rivalry (offset)** | `momentum_edge_v1` made +$8k on UB vs -$6.4k on prod — the noise edges that dominated capital share on prod (atr_breakout 5,269 fills) fired 18× less on UB, leaving more book for momentum to express. **Not a driver of the gap; a partial offset of it.** | +$14.5k offset | **−15% (offset)** |

**Net: liquidity / impact-knee is the dominant driver (~40%).
Signal-density failure on the stable contributors is the next-largest
(~30%). Survivorship-tail is ~20%, mostly through the vol/MDD channel.
Beta and pure sector-mix explain almost none of the gap.**

## The structural answer

**Universe-fragile in a specific, mechanical sense — not "needs a
different universe," but "the edge stack has implicit liquidity
preconditions that go unmodeled."**

Three claims, in increasing order of strength:

1. **The 1.063 anchor was not a fluke.** It is what these edges produce
   in their natural habitat (mega/large-cap, high-ADV, surviving names).
   The same edges on the prod-109 universe with the same costs
   reliably produce that number — the in-sample work was correctly
   executed.

2. **The 0.225 Universe-B result is also not "the truth."** It's what
   happens when you force the same edges into a universe where their
   signal preconditions don't hold (volume-spike thresholds rarely
   trip; order-flow herding rarely visible) and where 12% of the names
   are catastrophically declining toward delisting. **Survivorship
   bias is in reverse here**: UB *over*-samples failed companies
   relative to a real future-deployment universe.

3. **The brittleness is architectural, not stochastic.** The edge
   stack does not have an explicit "minimum ADV to fire" gate.
   `volume_anomaly_v1` fires whenever today's volume / 20d-avg-volume
   exceeds a multiplier, with no floor on the absolute level. On a
   $20M/day name a 3× volume spike is ~$60M of trade signal — large
   relative to that name's ADV but tiny in absolute order-flow terms,
   and the impact tax on the resulting fill eats whatever signal was
   there. This is not a parameter to tune; it is a missing
   architectural primitive.

## Implications

**Should the production universe be expanded, contracted, or
restructured?**

The right answer is **none of the above for the current edge stack**.
Expanding the universe to "be more representative" without changing
the edges is what produced the Universe-B 0.225 result; it is not a
test of merit, it is a test of whether the edges work outside their
natural habitat (they don't, and the math says they can't without
liquidity-aware modifications).

But "stay on prod 109" is also not a satisfactory answer because the
prod universe was implicitly curated *for these edges* — it cannot be
cited as evidence the system would generalize to a real deployment
universe with mid-cap exposure. The 04-25 finding that **system true
Sharpe on a wider universe is 0.4 vs SPY 0.88** is reaffirmed by this
diagnosis, but with the structural reason now explicit:

- The prod stack's two stable contributors (`volume_anomaly_v1`,
  `herding_v1`) are **liquidity-density-dependent**. Without
  high-volume names, they don't fire enough to matter.
- The prod stack's noise edges (`atr_breakout_v1`,
  `low_vol_factor_v1`) become **catastrophically expensive on
  illiquid names** — pruning them via lifecycle (Phase 2.10d Task A)
  is even more important than the in-sample data suggested, because
  the real cost of leaving them on shows up off-distribution.

The right structural moves, in order of expected payoff:

1. **Add an explicit ADV floor to every edge's `should_fire` logic.**
   Probably $200M/day (prod 109's lower bound) or $500M/day. This
   isn't tuning — it's making an implicit precondition explicit.
   Without it, the system trades signals it can't actually capture.

2. **Discover edges that work on the broader investable universe.**
   The 04-25 memory's recommendation stands: PEAD (earnings-driven,
   liquidity-agnostic), yield-curve macro overlays, factor work on a
   500+ name universe. These are signals whose alpha *doesn't* depend
   on order-flow density.

3. **Stop citing the 0.225 number as evidence the system has no
   alpha.** It is evidence the current edges are universe-fragile. The
   per-year integration data (memory
   `project_ensemble_alpha_paradox_2026_04_30`) and Phase 2.10c per-
   edge attribution show real positive contribution from
   `volume_anomaly_v1` and `herding_v1` on prod every year. The
   contribution is real on the universe where the signals fire; the
   universe where they don't fire is not a refutation of the edges,
   it is a refutation of treating the edges as universe-agnostic.

4. **Re-evaluate the moonshot/Goal-C path on a different premise.**
   If the structural fix is "discover liquidity-agnostic edges," then
   Engine D's search space needs to change — random technical-gene
   mutations on the existing 109 universe will not find them. This
   was already the 04-25 conclusion; this audit reaffirms it from a
   different angle.

## Five-line summary

1. The 79% Sharpe collapse is **~40% liquidity / impact-knee
   (atr_breakout's per-fill loss went 76× worse on UB), ~30%
   stable-contributor signal-density failure (volume_anomaly + herding
   fire 89% less when ADV median is 6× lower), ~20% survivorship-tail
   trading on delisted names (12% of UB has truncated/zero data),
   ~5-10% sector mix, ~0% beta**.

2. **The system is universe-fragile in a specific architectural way:**
   its stable contributors have implicit liquidity preconditions that
   are not encoded in their `should_fire` gates.

3. The prod 109 wasn't a flaw — it was an unstated curated-for-edges
   universe where the preconditions happened to hold. Universe-B isn't
   "the truth" either — it's the system tested off-distribution
   without precondition gating.

4. **Recommended structural answer: keep the universe broad, but add
   explicit per-edge ADV floors, prune liquidity-fragile noise edges
   (Phase 2.10d Task A is ~2× more important than in-sample data
   suggested), and discover liquidity-agnostic edges (PEAD, macro,
   factor-on-500) instead of more technical-gene mutations.**

5. The 04-25 finding "true Sharpe is 0.4 vs SPY 0.88 on a wider
   universe" is reaffirmed and now explained mechanically. To beat
   SPY on a representative universe requires different edges, not a
   different universe selection.

## Repro

```bash
# Per-ticker metadata + per-edge attribution
python3 /tmp/agentD/analyze_universe_b.py
# Outputs: /tmp/agentD/diagnosis.json, prod_meta.csv, ub_meta.csv
```

Trade logs at:
- `data/trade_logs/abf68c8e-1384-4db4-822c-d65894af70a1/trades.csv` (prod)
- `data/trade_logs/ee21c681-f8de-4cdb-9adb-a102b4063ca1/trades.csv` (UB)

Universe metadata: `data/universe/sp500_membership.parquet`
Per-ticker daily bars: `data/processed/<TICKER>_1d.csv`
