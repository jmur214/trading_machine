# Path C — Synthetic Compounder Sleeve Backtest (D3 Feasibility Test)

**Branch:** `path-c-compounder-sleeve-design`
**Date:** 2026-05-02
**Status:** **FAIL** on both pre-committed pass criteria.
**Script:** `scripts/path_c_synthetic_compounder.py`
**Raw output:** `data/research/path_c_synthetic_backtest.json`

---

## TL;DR

The simple price-derived top-quintile compounder, on a curated 51-ticker mega/large-cap universe over 2010-2024, **underperforms SPY after-tax by 154 bps CAGR** and **breaches the -15% MDD floor** with a -25.19% drawdown (2020 COVID crash). Both pre-committed pass criteria failed.

This **does not invalidate the compounder sleeve design**, but it does materially constrain how it should ship. The synthetic test was deliberately a stripped-down version using price-derived factor proxies (no fundamentals data available at design phase) on a curated mega-cap universe (no S&P 500 PIT panel available yet). The honest reading: this version of the sleeve is not deployment-ready, and the gap is largely explained by the limitations of the synthetic. Concrete corrective actions for the production design are listed below.

---

## Result table

| Strategy | CAGR pre-tax | CAGR after-tax | Sharpe | Max Drawdown |
|---|---|---|---|---|
| **Compounder synthetic** | **12.03%** | **11.11%** | **0.852** | **-25.19%** |
| SPY buy-and-hold | 13.69% | 12.65% | 0.839 | -33.72% |
| 60/40 (SPY/IEF) annual | 8.83% | 7.84% | 0.916 | -19.46% |

Pass criteria (pre-committed in the task):

| Criterion | Required | Actual | Result |
|---|---|---|---|
| Compounder after-tax CAGR > SPY after-tax CAGR | strict > | 11.11% vs 12.65% | **FAIL** (Δ -1.54 pp) |
| Compounder max drawdown ≥ -15% | ≥ -15% | -25.19% | **FAIL** (-10.19 pp through floor) |

---

## What was actually run

- **Universe:** 51 liquid mega/large-caps with continuous 2010-2024 yfinance history (curated, NOT survivor-bias-free S&P 500). Sectors: Tech, Healthcare, Financials, Consumer, Industrials, Energy, Materials/Utilities, Telecom.
- **Period:** 2010-01-01 → 2024-12-31 (15 years, 3,773 trading days).
- **Cadence:** annual rebalance on first trading day of January.
- **Allocation:** equal-weight, top quintile of composite score (≈10 names per cycle).
- **Factor composite (price-derived proxies):**
    1. 12-1 month momentum (Jegadeesh-Titman) — quality/persistence proxy
    2. Inverse 252-day vol — defensive/quality proxy
    3. Inverse 1-month return — mean-reversion guard against hot names at rebalance
    4. Inverse 252-day max drawdown — drawdown-control proxy
  Each ranked to percentile, four percentiles equal-weight averaged to composite. Top 20% goes into the long basket.
- **Tax model:** all rebalance turnover deemed long-term (held ≥ 365d by construction). Realized gains taxed at 15% federal LT cap gains; losses carried forward.
- **Initial capital:** $10,000 (matches retail-scale framing in `project_retail_capital_constraint_2026_05_01.md`).

---

## Why it failed (honest diagnosis)

### 1. Curated mega-cap universe is NOT a real S&P 500 panel

The 51-ticker list is essentially a representative slice of *current* SPY top constituents (no historical drop-outs, no Pacific Gas, no Lehman, no GE-pre-2018). The compounder is supposed to extract a *cross-sectional* premium by ranking value/quality/momentum across a broad universe. With 51 names, top-quintile = ~10 names — exactly the same pathology that killed `momentum_factor_v1` on the 39-ticker prod universe in April (memory: `project_factor_edge_first_alpha_2026_04_24.md`). At this universe size, the strategy degrades to **"hold the most defensive 10 mega-caps"**, which is approximately a low-vol-tilted SPY — but with 1.5pp tracking error after taxes.

The design doc (D2.1) already argues for the full S&P 500 with PIT membership for exactly this reason. The synthetic test confirms the prior empirically: at the universe size we have data for *today*, the compounder cannot beat SPY.

### 2. Price-derived "factors" are NOT real factors

The four signals used here are price-derived proxies, not the value/quality composite the design specifies (P/E + P/B + EV/EBITDA + ROIC + accruals + asset growth + net issuance). The proxies were chosen as the honest stand-in for what fundamentals data would provide, but they are correlated with the same return streams SPY provides — they're not orthogonal premia. The academic factor literature (QMJ, profitability, accruals) generates 2-4% annual alpha *only* when the underlying signal is true fundamental data; when the signal is price-derived persistence/vol, the alpha collapses to near zero net of costs.

The `fundamentals_static.csv` file in this repo is a 7-row stub (3 tickers, 2 dates each), and yfinance only exposes TTM fundamentals — not historical quarterly. **A fundamentals-backed compounder needs a real data source (Compustat, FactSet, SimFin, or scraped 10-Q EDGAR pulls).** This is a Workstream F dependency that has not been scoped.

### 3. The -25% MDD is a 2020 COVID artifact and an inherent annual-cadence problem

The compounder hit its peak drawdown in March 2020. With annual rebalance, the strategy was holding its January 2020 basket through the COVID crash with no ability to de-gross. SPY took a worse drawdown (-33.7%) but recovered faster; the compounder's concentration in 10 names amplified the path. This is not a bug in the design — it's a consequence of (a) low diversification at this universe size, and (b) the design's deliberate refusal to react intra-year to regime changes.

The design's tradeoff was *tax efficiency for sluggishness*. The synthetic shows the sluggishness isn't free.

---

## What this means for the design (D1 + D2)

### Things this result does NOT invalidate

- **The sleeve abstraction itself** (D1). The interface, aggregator, and migration plan are unaffected — they are independent of any one sleeve's empirical performance.
- **The compounder's tax-efficiency thesis.** The synthetic's 15% LT rate vs the 30% ST rate on the core sleeve is real and reproducible; if the compounder *did* match SPY pre-tax, the after-tax win would compound. The current result simply says compounder can't match SPY pre-tax with these inputs.
- **The architectural value of having an independent low-turnover sleeve** that doesn't share Engine B's daily vol-target machinery with the core. That's a real benefit even if Phase M2 ramp is paused.

### Things this result DOES update

| Original design choice | Synthetic finding | Updated recommendation |
|---|---|---|
| Universe: S&P 500 with PIT membership | At a 51-name curated universe, top-quintile is too concentrated to extract real factor premia | **Hard requirement: S&P 500 (or wider) PIT panel BEFORE Phase M2 enable**. Sub-task 6 in D4 is now BLOCKING for M2, not parallel. |
| Edges: 5 fundamentals composites + optional low-vol | Price-derived proxies replicate SPY rather than offering orthogonal returns | **Hard requirement: real fundamentals data source.** Workstream F or a vendor add. The 5 edges as specified cannot ship until this is in place. Sub-task 7 in D4 absorbs this dependency. |
| MDD floor: -15% sleeve-level kill | Synthetic broke -25%; design has no de-grossing mechanism within a year | **Add intra-year de-gross trigger.** Engine E regime confidence drop into "stressed" or "crisis" should trigger a partial sleeve de-gross (e.g., compounder weights × 0.5) without realizing taxable gains where avoidable. This is a Phase M3 addition; not blocking M2 enable, but the MDD floor as a kill switch alone is empirically insufficient. |
| Capital pct: ramp 0.05 → 0.15 | Synthetic underperforms SPY net of taxes | **Compounder Phase M2 enable requires positive empirical evidence on the real S&P 500 + fundamentals build, not just on this synthetic.** The 5% / 10% / 15% ramp gates from D1.5 should each require a positive A/B Sharpe + after-tax CAGR observation. |

### Things that need to happen BEFORE the compounder ships in production

1. **S&P 500 PIT price + membership panel** (Workstream F). Without this, every synthetic and every backtest is on a survivor-biased universe.
2. **Fundamentals data source** (Workstream F). Without this, the 5 designed edges literally cannot be implemented.
3. **A second feasibility test on the real universe + real fundamentals**, ideally using the same script structure with the data inputs swapped. If that test still fails the pass criteria, the compounder thesis is structurally weak and the design should be revisited (potentially: drop annual cadence to quarterly with longer-than-365d-targeted holds, or weight mega-caps differently).
4. **Engine E regime confidence consumption** for intra-year de-gross. This couples to Workstream C (HMM regime work) which has shipped its first slice but isn't yet feeding sleeve-level decisions.

---

## What the synthetic IS useful for

- **It validates the script infrastructure.** Annual rebalance, equal-weight top quintile, tax model with carry-forward, three-way comparison (compounder / SPY / 60-40) — the harness works and produces honest measurement. The same script can be re-run with real fundamentals when they're available.
- **It establishes the SPY 12.65% after-tax CAGR baseline** that any production compounder must beat.
- **It establishes the 60/40 8.84% pre-tax / 7.84% after-tax baseline** as a *floor* — if the compounder ever fails to beat 60/40 after-tax under realistic costs, the sleeve's reason-for-existing is gone (60/40 is also low-turnover and tax-efficient).
- **It demonstrates the MDD risk** that any production compounder must address, ideally before Phase M2 enable.

---

## Connection to the kill thesis

The pre-committed kill thesis in `docs/Core/forward_plan_2026_05_02.md` applies to the *combined system Sharpe under harness*, not to the compounder synthetic specifically. **This synthetic FAIL does not trigger any kill thesis.** It is, however, a valid **caution flag**: don't enable the compounder in production until the data layer dependencies are satisfied AND a real-data feasibility test passes. Shipping the compounder on this evidence would repeat the `momentum_factor_v1` mistake (memory: `project_factor_edge_first_alpha_2026_04_24.md`) — a 39-ticker factor edge that passed in-sample but failed OOS because the universe was too small to support cross-sectional factor exposure.

The **architecture is still worth shipping** (Phase M0). The **enable** is the part that needs more evidence.

---

## Reproducibility

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-pathc
python scripts/path_c_synthetic_compounder.py
```

Cached price panel at `data/research/path_c_cache/prices_2010-01-01_2024-12-31.parquet`. Re-running uses the cache; delete to refresh from yfinance.

Full numerical results at `data/research/path_c_synthetic_backtest.json` including:
- Per-rebalance basket composition (`rebalance_events[]`)
- Per-year returns for each strategy
- All metadata (universe, factors used, tax assumptions, limitations)

---

## Bottom line

Honest synthetic measurement says: **the simple version of the compounder cannot beat SPY after-tax over 2010-2024 on a 51-name curated universe with price-derived proxies.** The design's premise (low-turnover, tax-advantaged, broad-factor exposure) is sound but the execution depends on data layer work that hasn't been done. The **sleeve abstraction itself (D1) ships unchanged.** The **compounder enable (D2 specifics) waits on (1) S&P 500 PIT data, (2) fundamentals data, (3) a real-data feasibility test, and (4) a regime-conditional de-gross trigger.**

This is the kind of result the project's deterministic-measurement discipline is designed to surface. Shipping the compounder on this synthetic alone would have re-created the false-positive pattern the team has worked hard to suppress.
