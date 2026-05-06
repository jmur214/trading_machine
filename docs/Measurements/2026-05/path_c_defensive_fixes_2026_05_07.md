# Path C — Defensive Fixes Falsified, Cell F Closest Miss (2026-05-07)

**Window:** 2022-01-01 → 2025-04-30 (FREE-tier feasible, matches yesterday's vol-overlay test for cell-by-cell comparison).
**Universe:** S&P 500 ex-Financials ∩ SimFin coverage = 359 tickers (real-fundamentals cells); 51 hardcoded mega-caps for synthetic Cell C.
**Initial capital:** $10,000. **LT cap-gains rate:** 15%. **Annual rebalance** (4 events: 2022-01-03, 2023-01-03, 2024-01-02, 2025-01-02).
**Branch:** `path-c-defensive-fixes` (worktree-local).
**Audit verdict:** Branch 3 — defer Path C with explicit unblock criteria. Cell F is the closest miss in any Path C iteration to date.

## Results — 8-cell harness

| Cell | Strategy | CAGR pre | CAGR after | Sharpe | MDD |
|---|---|---:|---:|---:|---:|
| A | spy_buyhold | 6.07% | 5.21% | 0.406 | -24.50% |
| B | 60_40_buyhold | 3.72% | 2.46% | 0.379 | -17.16% |
| C | compounder_synthetic | 3.87% | 3.13% | 0.387 | -15.74% |
| D | compounder_real_fundamentals (baseline) | 7.08% | 5.83% | 0.468 | -21.84% |
| E | + vol overlay (annual cadence) | 4.27% | 3.40% | 0.332 | -21.84% |
| **F** | **+ defensive vol-rank pre-screen** | **5.60%** | **4.74%** | **0.439** | **-16.09%** |
| **G** | **+ 70/30 IEF bond buffer** | **4.41%** | **3.67%** | **0.390** | **-20.12%** |
| **H** | **+ pre-screen + bond buffer (combined)** | **3.28%** | **3.09%** | **0.343** | **-15.79%** |

Cell D differs from yesterday's harness (5.83% vs 5.64% after-tax) because the SimFin panel was re-fetched and updated; rerunning Cell D against today's panel was the consistent baseline for F/G/H comparison.

## Pass criterion (load-bearing -15% MDD target preserved per `path_c_compounder_design_2026_05.md` line 341)

| Cell | After-tax CAGR > SPY (5.21%)? | MDD ≥ -15%? | Verdict |
|---|---|---|---|
| D | 5.83% PASS (+0.62pp) | -21.84% FAIL (-6.84pp) | FAIL |
| E | 3.40% FAIL (-1.81pp) | -21.84% FAIL (-6.84pp) | FAIL |
| **F** | **4.74% FAIL (-0.47pp)** | **-16.09% FAIL (-1.09pp)** | **FAIL — closest miss** |
| **G** | **3.67% FAIL (-1.54pp)** | **-20.12% FAIL (-5.12pp)** | **FAIL** |
| **H** | **3.09% FAIL (-2.12pp)** | **-15.79% FAIL (-0.79pp)** | **FAIL** |

**No cell PASSES both criteria.** This is Branch 3 from the dispatch.

## What each fix actually does

### Cell F — defensive vol-rank pre-screen (lowest-200 by 252d vol, then V/Q/A composite)

Mechanism: at each rebalance, rank universe by trailing 252d annualized realized vol, keep the lowest 200, apply the 6-factor V/Q/A composite, take top quintile (~40 names). Vol lookback uses an extended price panel (2020-12-01 → 2025-04-30) so the 2022-01-03 first rebalance has a real 252-day window.

Annual returns reveal the trade:

| Year | Cell F | Cell D | Cell A (SPY) | F vs D | F vs A |
|---|---:|---:|---:|---:|---:|
| 2022 (bear) | -4.55% | -10.24% | -18.65% | **+5.69pp** | **+14.10pp** |
| 2023 (recovery) | +9.13% | +26.16% | +26.71% | **-17.03pp** | **-17.58pp** |
| 2024 (bull) | +16.93% | +16.82% | +25.59% | +0.11pp | -8.66pp |
| 2025 YTD (Apr-30) | -1.34% | -4.91% | -4.90% | +3.57pp | +3.56pp |

Honest interpretation: the pre-screen is **doing exactly what it was designed to do** — cushion bear years by skewing to low-vol names — but the 2023 recovery was led by previously-high-vol names (META, NVDA, technology), and the pre-screen filtered them OUT. Net: gives up too much upside to pay for the downside protection.

The MDD of -16.09% is **5.75pp better than Cell D (-21.84%)** but still misses the -15% target by 1.09pp. The 2022 drawdown is the binding constraint: even on the calm subset, the long-only equity quintile rode the 2022 bear down.

### Cell G — 70/30 compounder/IEF bond buffer

Mechanism: at each annual rebalance, allocate 30% of buying power to IEF (intermediate-term Treasuries), 70% across the V/Q/A top quintile. IEF rebalanced annually alongside equities.

The arithmetic prediction was naive: "70% × -21.84% MDD = -15.3%". Actual MDD: -20.12%. The shortfall (4.82pp worse than naive prediction) is the 2022 bond-equity correlation breakdown — IEF lost ~17% in 2022 as the Fed hiked 525bp. Bonds and equities drew down together. The Cell B 60/40 shows the same pattern (-17.16% MDD).

| Year | Cell G | Cell D | Cell A (SPY) |
|---|---:|---:|---:|
| 2022 | -11.47% | -10.24% | -18.65% |
| 2023 | +19.17% | +26.16% | +26.71% |
| 2024 | +11.69% | +16.82% | +25.59% |
| 2025 YTD | -2.04% | -4.91% | -4.90% |

Bonds were a worse 2022 hedge than no hedge at all. CAGR cost from the bond drag: -2.16pp after-tax (5.83% → 3.67%) for only 1.72pp of MDD relief. **Bad risk-adjusted trade.**

### Cell H — combined pre-screen + bond buffer

Stacks both costs without compounding the benefit. MDD -15.79% is the closest of any cell to the -15% target (only 0.79pp short), but CAGR after-tax 3.09% is 2.12pp below SPY. The drawdown protection arithmetic is roughly additive (F's cushion + G's bond drag) but the upside surrender is also additive.

If the user is willing to surrender CAGR for MDD-target compliance, Cell H is closest — but at 3.09% after-tax it's barely above 60/40 (Cell B's 2.46%) and underperforms SPY by 41% (3.09 / 5.21 = 59%).

## Why the vol overlay (Cell E from yesterday) failed differently

Cell E's failure was **cadence mismatch** — annual-rebalance overlay can't react to intra-year drawdowns (`project_path_c_vol_overlay_failed_2026_05_06.md`). Cells F and G fail differently:

- Cell F fails on **upside surrender during recovery years**, not cadence — the pre-screen IS doing its job in bear years
- Cell G fails on **2022-specific bond-equity correlation breakdown** — bonds were not a diversifier in a rate-shock regime

These are independent failure modes, not the same "annual cadence is too coarse" critique.

## Honest assessment of how close Cell F came

Cell F is **the closest miss in any Path C iteration to date:**

- 1.09pp from the -15% MDD target
- 0.47pp from beating SPY after-tax

Could a slight parameter tweak push F over the line? Two candidate knobs:

1. **Top-N pre-screen tighter** (e.g. top 100 instead of top 200) — would force more low-vol concentration but on a 4-year window with only 4 rebalances, the parameter is at risk of being curve-fit. Pre-registered hypothesis without re-running before commit: top 100 would push MDD into the target zone but worsen CAGR by another 1-2pp (edges to Cell H territory).
2. **Universe construction** (e.g. defensive-sector overweight instead of vol-rank) — sectors with structurally lower vol (Staples, Utilities, Healthcare) would more reliably cushion bears but at deeper structural CAGR underperformance.

Neither knob is investigated here per the time budget. The recommendation is **not to tune** — adding a third knob to a 4-year, 4-rebalance backtest is over-fitting territory.

## Recommendation — Branch 3 (defer with explicit unblock criteria)

**Path C is not shippable today** under the load-bearing -15% MDD constraint. Three structural prerequisites must land before any defensive-fix combination can plausibly clear the bar:

### Unblock criterion 1 — Engine E HMM in production decision path

Today HMM is observability-only. To make Path C work, the regime detector needs to produce an actionable signal that downstream consumers (Engines B, C, or this script's overlay machinery) can read at any time, not just at the annual rebalance.

Specifically: a regime-state vector (e.g. `bull / chop / bear-onset / bear-bottom`) updated daily, callable from outside Engine E.

Reference: HMM first-slice work in `engine_e_hmm_first_slice_2026_05.md`.

### Unblock criterion 2 — Engine B reads regime signals and de-grosses during stress

Engine B currently has vol-targeting and exposure-cap machinery (`PortfolioPolicy._apply_vol_target`, advisory exposure cap), but neither is regime-conditional in the way Path C needs. Required behavior:

- On a regime-state transition into `bear-onset`, the compounder sleeve trims gross exposure (e.g. 100% → 70%) within days, not at the next annual rebalance
- The trim is not a vol-target re-fit (which is too slow) but a discrete regime-change response

This is an Engine B change. Out of scope for an Engine A / Quant Analyst lens to specify. Flagged for a future Engine B / Risk dispatch.

### Unblock criterion 3 — Vol-overlay infrastructure becomes load-bearing

`scripts/path_c_overlays.py` is already shipped, tested (15/15), and unused after the 2026-05-06 cadence-mismatch falsification. Once criteria 1 and 2 are in place, the overlay's `apply_vol_target` becomes the natural callsite for regime-conditional de-grossing. The 0.15 vol target and [0.3, 2.0] clip range are sane defaults; only the trigger cadence needs to change from "annual" to "regime-change events."

## What this measurement cost

- ~25 minutes implementation (defensive_pre_screen + bond_buffer plumbed through `run_compounder_backtest`, extended-history lookback panel for the pre-screen first-rebalance)
- ~10 minutes harness execution (yfinance redownload due to SimFin re-fetch invalidating the price cache; SimFin downloads required ~5 min)
- 1 worktree, 1 branch, 1 audit doc

**Falsification rigor:** all three defensive fixes (F, G, H) failed at least one criterion. The closest miss (F) failed by 1.09pp on MDD and 0.47pp on CAGR. No cell crossed the bar. Cell F's annual-return decomposition shows the mechanism is real and as-designed, just insufficient — strengthens the "regime-conditional fix is what's missing" diagnosis.

## Limitations of this measurement

- 4-year window only — single bear (2022 rate shock), single recovery (2023), single bull (2024), 4 months of 2025. Statistically thin like the 2026-05-05 baseline.
- 2022 is a rate-shock bear, not a credit-driven bear. The bond buffer's failure in 2022 may not generalize to e.g. a 2008-style bear where Treasuries rallied. Without 2008 in window the bond-buffer test is incomplete.
- Defensive pre-screen vol-rank lookback uses a separate price panel starting 2020-12-01 — this only matters for the 2022-01-03 first rebalance (subsequent rebalances have in-window history). Backtest equity curve still starts cleanly at 2022-01-01.
- All three new cells use the same quarterly SimFin restated panel as Cell D — restatement bias is inherited.
- Cell F's basket size at the 2022 rebalance is 40 names from the lowest-200 vol pool; further diluted to ~33-37 when factor data is missing. Concentration drift is bundled with the upside-surrender effect.

## Reproducibility

```bash
# 8-cell harness (incl. Cells F/G/H defensive fixes)
# Edit START_DATE = "2022-01-01", END_DATE = "2025-04-30" in the script
# (committed default is 2010-01-01 / 2024-12-31, BASIC-tier-feasible window)
PYTHONHASHSEED=0 python scripts/path_c_synthetic_compounder.py --run
```

JSON output: `data/research/path_c_synthetic_backtest.json` (gitignored)
Branch: `path-c-defensive-fixes` (worktree-local)
Worktree: `/Users/jacksonmurphy/Dev/trading_machine-2/.claude/worktrees/agent-aa3aef9e22c9e8c51`
