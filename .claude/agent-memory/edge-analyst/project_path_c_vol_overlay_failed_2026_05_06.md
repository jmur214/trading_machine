---
name: Path C vol overlay FAILED to rescue MDD on annual cadence — overlay-cadence/risk-cadence mismatch (2026-05-06)
description: Cell E (Cell D + 0.15-target vol overlay, 60d lookback, [0.3,2.0] clip) on 2022-2025 window. MDD identical to Cell D (-21.36%), CAGR cost -2.27pp after-tax, Sharpe cost -0.128. Overlay only fires at 4 annual rebalances; the 2022 bear drawdown happens entirely inside a hold period.
type: project
---
**5-cell harness on 2022-01-01 → 2025-04-30:**

| Cell | Strategy | CAGR pre | CAGR after | Sharpe | MDD |
|---|---|---:|---:|---:|---:|
| D | compounder_real_fundamentals | 6.89% | 5.64% | 0.461 | -21.36% |
| **E** | **+ vol overlay** | **4.26%** | **3.38%** | **0.333** | **-21.36%** |
| C | compounder_synthetic | 3.87% | 3.13% | 0.387 | -15.74% |
| A | spy_buyhold | 6.07% | 5.21% | 0.406 | -24.50% |
| B | 60_40_buyhold | 3.72% | 2.46% | 0.379 | -17.16% |

**Vol overlay diagnostics (4 rebalances, all early January):**
- raw scalar range:    [0.594, 1.163], mean 0.943
- applied scalar range: [0.594, 1.163], mean 0.943 (NO clip events — never hit 0.3 or 2.0)
- est. port vol range:  [0.129, 0.252], mean 0.170
- clip-state: 25% neutral, 50% levered_up, 25% de_levered, 0% upper/lower clip

**Mechanical falsification — overlay can't act on intra-year risk:**

The overlay only re-evaluates at annual rebalance dates (`2022-01-03, 2023-01-03, 2024-01-02, 2025-01-02`). Between rebalances the portfolio is buy-and-hold. The 2022 bear (Jan-Oct 2022) drawdown happened *entirely inside* the first hold period. By Jan 2023, the damage was already permanent.

This is a cadence mismatch, not a math bug. The overlay's helper math (`scripts/path_c_overlays.py`) is correct (15 unit tests pass). The signal it operates on is just stale relative to the risk it's supposed to hedge.

**Why the CAGR cost (asymmetric overlay):**
- 2 of 4 rebalances had port_vol < target → overlay wanted to lever up (scalars 1.16, 1.06)
- The script caps gross at 1.0 (no margin in this sim), suppressing those lever-ups
- 1 of 4 rebalances had port_vol = 0.252 → de-lever to 0.594 (cut deployed capital ~40%)
- The de-lever happens once but the suppressed lever-ups happen twice → net negative carry

**Verdict on spend gate:** Don't double-spend on this overlay. Two paths actually viable:
1. **Reset MDD target to "SPY -2pp"** — Cell D PASSES (-21.36% vs SPY -24.50% = +3.14pp better)
2. **Defer until Engine E HMM** — regime-conditional overlay can fire on regime change events, not just annual rebalances

**Reusable infrastructure shipped:** `scripts/path_c_overlays.py` is a clean standalone port of `PortfolioPolicy._apply_vol_target` — `apply_vol_target`, `estimate_portfolio_vol`, `apply_exposure_cap`, `summarize_overlay_diagnostics`, `VolOverlayDiagnostics` dataclass. Reuse when HMM-conditioned overlay testing happens.

**Hypothesis to falsify next:** does the same overlay rescue MDD on a *monthly* rebalance cadence? Hypothesis: yes, partially, but at non-trivial extra tax drag (12 events/yr vs 1). This is the Engine B vol-target path — different sleeve, out of scope this round.

**Branch:** `path-c-vol-overlay` (worktree-local, not pushed)
**Audit:** `docs/Measurements/2026-05/path_c_vol_overlay_2026_05_06.md`
**Tests:** 15/15 pass (`tests/test_path_c_overlays.py`); 11 path_c_real_fundamentals tests still pass (regression check).
**JSON output:** `data/research/path_c_synthetic_backtest.json` (gitignored)

**Statistical-traps takeaway:** "wire the production overlay onto a feasibility script" sounds incremental but exposes a deeper issue: production-grade risk machinery is calibrated for production-grade rebalance cadence. Mounting it on annual-cadence sleeves is structurally underpowered and the negative result was predictable in hindsight.
