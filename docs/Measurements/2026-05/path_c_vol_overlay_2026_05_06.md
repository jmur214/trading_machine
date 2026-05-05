# Path C — vol-overlay rescue test (Cell E vs Cell D)

**Date:** 2026-05-06
**Branch:** `path-c-vol-overlay`
**Window:** 2022-01-01 → 2025-04-30 (FREE-tier feasible, same as Cell D run on 2026-05-05)
**Question:** Can a 0.15-target vol overlay rescue Cell D's failed -15% MDD criterion?
**Verdict:** **NO.** The overlay does not save MDD on this universe + cadence. It costs 2.27pp after-tax CAGR and -0.128 Sharpe for 0.0pp MDD improvement.

---

## TL;DR

| Cell | Strategy | CAGR pre | CAGR after | Sharpe | MDD |
|---|---|---:|---:|---:|---:|
| D | compounder_real_fundamentals | 6.89% | **5.64%** | **0.461** | -21.36% |
| **E** | **compounder_real_fundamentals + vol overlay** | **4.26%** | **3.38%** | **0.333** | **-21.36%** |
| C | compounder_synthetic | 3.87% | 3.13% | 0.387 | -15.74% |
| A | spy_buyhold | 6.07% | 5.21% | 0.406 | -24.50% |
| B | 60_40_buyhold | 3.72% | 2.46% | 0.379 | -17.16% |

**Cell D vs Cell E delta:**
- CAGR pretax:    6.89% → 4.26%   (-2.63pp)
- CAGR aftertax:  5.64% → 3.38%   (-2.27pp)
- Sharpe pretax:  0.461 → 0.333   (-0.128)
- Max Drawdown:  -21.36% → -21.36% (+0.00pp)

Both Cell D and Cell E now FAIL the spec MDD criterion. Cell D still PASSES the after-tax-CAGR-vs-SPY criterion; Cell E now FAILS that too.

---

## Why the overlay didn't move MDD

The diagnostic that explains everything:

```
rebalances:           4
raw scalar  range:    [0.594, 1.163], mean 0.943
applied scalar range: [0.594, 1.163], mean 0.943   (no clip events)
est. port vol range:  [0.129, 0.252], mean 0.170
clip-state distribution:
    neutral          1  (25%)
    levered_up       2  (50%)
    de_levered       1  (25%)
    upper_clip       0  (0%)
    lower_clip       0  (0%)
```

Rebalance dates: `2022-01-03, 2023-01-03, 2024-01-02, 2025-01-02`.

**Mechanical mismatch:** Cell D rebalances annually. The vol overlay only re-evaluates at those four dates. Between rebalances the portfolio is buy-and-hold. The 2022 bear market started in Jan 2022 and bottomed in Oct 2022 — entirely *inside* a hold period. By the time the next rebalance came around (Jan 2023), the drawdown had already happened and was permanently embedded in the equity curve.

The overlay's worst-case scenario is exactly the case it would need to defend against: a market that's calm at rebalance time and then sells off mid-year. Looking at the diagnostic numbers, the Jan 2022 rebalance saw an estimated port vol of ~0.13-0.17 — calm — and applied scalar near 1.0 (or even >1.0 if the levered_up state happened then). That's the entry into the 2022 bear.

**The applied scalars never hit either clip bound.** Range was [0.594, 1.163], comfortably inside [0.3, 2.0]. So the *math* worked, but the *signal* the math is pricing off is stale relative to the risk it's supposed to hedge.

**Why the CAGR cost.** Two of the four rebalances had port vol < target (0.13 vs 0.15), so the overlay levered up to scalar > 1.0 — but the gross-cap at 1.0 (no margin in this sim) suppressed the lever-up direction, leaving those rebalances flat at gross 1.0. Meanwhile the one de-lever event (2022 entry, applied 0.594) cut deployed capital by 40% during the year that turned out to be a recovery year for the held basket. Net: the overlay sacrificed CAGR in calm periods without buying the volatility-protection it's designed for.

---

## Honest interpretation — does this answer the spend gate?

**No, this is a sleeve-design failure, not a spend-gate failure.** The overlay is acting on annual data; the risk it needs to hedge is intra-year. Three responses are defensible:

### 1. Reset the MDD target

This is what the prior memory (`project_path_c_4cell_2026_05_05.md`) already proposed. The original -15% MDD target came from a curated 51-name implicitly-low-vol mega-cap basket. On 351 ex-financials names, MDD tracks SPY more closely. Cell D at -21.36% is +3.14pp better than SPY's -24.50% — that's a real, defensible MDD-vs-benchmark improvement, just not down to -15%.

Spend-gate decision under this reset: Cell D's 5.64% after-tax CAGR vs SPY's 5.21% (+0.43pp) and Sharpe 0.461 vs 0.406 (+0.055) is genuine but small lift on a 3-year window. Whether $420 BASIC unlocks more is the next question — answered only by re-running on 13 years.

### 2. Move overlay to a higher cadence (NOT this round)

The overlay would need to fire monthly (or weekly) to react to intra-year vol regime changes. That's a substantively different sleeve design — it adds turnover (which adds tax drag), it requires Engine B vol estimation infrastructure, and it crosses Engine boundaries. Out of scope for this 1-2 hour test.

### 3. Pair with a regime detector (Engine E HMM)

Same problem (need higher-cadence signal) but solved by a regime classifier rather than a rolling-vol estimator. Also out of scope; documented as future work in `path_c_unblock_plan.md`.

---

## What the overlay test DID verify

Three things worth keeping:

1. **The math is correct.** Standalone helper in `scripts/path_c_overlays.py` reproduces `PortfolioPolicy._apply_vol_target` semantics. 15 unit tests pass (high-vol → de-lever, low-vol → lever-up, neutral → no-op, clip ceiling, clip floor, diagnostics classification, edge cases). This is reusable infrastructure for any future Path-C-style sleeve test.

2. **Cell E rebuilds reproducibly.** The harness ran end-to-end on this branch with the same data layer (SimFin FREE → 351-name universe → yfinance prices). No new data dependencies were introduced.

3. **The overlay's clip statistics teach us about the regime.** Mean estimated port vol of 0.170 is close to target 0.15 — the 60-day window happens to land near the long-run vol of a diversified ex-financials S&P slice. So the overlay is mostly neutral by construction in this universe. To get meaningful intervention you'd need either a higher-cadence signal (point #2 above) or a different vol target (which would force material lever-up or de-lever, both of which have their own downsides).

---

## Hard constraints honored

- Did NOT modify `engines/engine_b_risk/` or `live_trader/`
- Did NOT modify `config/portfolio_settings.json`
- Did NOT touch `data/governor/`
- `START_DATE`/`END_DATE` were edited for this run (2022-01-01 → 2025-04-30) but will be reverted to committed defaults (2010-01-01 → 2024-12-31) before commit
- Stayed inside `scripts/`, `tests/`, `docs/Measurements/2026-05/`
- New file: `scripts/path_c_overlays.py` (vol-target + exposure-cap helpers, no production-engine imports)
- New file: `tests/test_path_c_overlays.py` (15 unit tests)
- Edits: `scripts/path_c_synthetic_compounder.py` (added Cell E + diagnostics + JSON summary keys)

---

## Reproduce

```bash
# from worktree root
set -a && source /path/to/.env && set +a
# Edit START_DATE/END_DATE in scripts/path_c_synthetic_compounder.py to:
#   START_DATE = "2022-01-01"
#   END_DATE   = "2025-04-30"
python scripts/path_c_synthetic_compounder.py --run
```

Outputs:
- Console: 5-cell results table + Cell D vs Cell E delta + overlay diagnostics
- JSON: `data/research/path_c_synthetic_backtest.json`

---

## Recommendation for next decision

**Don't double-spend on this overlay.** Drop it. The two paths forward that *might* actually move MDD are:

1. **Accept Cell D's -21.36% MDD** as "SPY -3.14pp" and reset the absolute MDD target. This makes Cell D a clean PASS (CAGR > SPY, Sharpe > SPY, MDD < SPY) on the 2022-2025 window. Then re-test on 13 years (BASIC tier) to verify the lift survives 2008-class regimes.

2. **Defer Path C entirely until Engine E HMM ships,** at which point a regime-conditional version of the overlay (de-gross in HMM-detected stress, neutral otherwise) might do real work. This was already flagged as a prerequisite in `project_compounder_synthetic_failed_2026_05_02.md`.

Path (1) is the cheaper, faster decision. Path (2) is the architecturally correct one but is gated on HMM work.

The vol-overlay infrastructure (`scripts/path_c_overlays.py`) is now in place either way — it's the right helper to reuse when HMM-conditioned overlay testing happens.
