# Path C Compounder — Unblock Plan

**Branch:** `agent-ac32a6dc9cf7f48b6` (research-only worktree)
**Date:** 2026-05-04
**Status:** Plan, not commitment. Awaiting director approval to schedule execution.
**Sibling:** `docs/Audit/ws_f_fundamentals_data_scoping.md`

---

## TL;DR

The Path C compounder synthetic FAILED on a 51-name curated universe with price-derived proxies (`docs/Audit/path_c_compounder_synthetic_backtest_2026_05.md`). To get to a real-data feasibility test, we need three things, in order:

1. **Fundamentals source** — SimFin BASIC ($420/yr). Decision memo at `docs/Audit/ws_f_fundamentals_data_scoping.md`. Choose source.
2. **Universe** — S&P 500 historical PIT membership panel, ~500-name target. Build via Wikipedia historical S&P 500 lists + SimFin coverage check.
3. **Factor definitions** — six explicit factor formulas across Value / Quality / Accruals, defined in this doc. Compute on the live panel.

Everything else (engine wiring, sleeve aggregator, capital-pct ramp gates from D1.5) is already built or scaffolded. **The unlock is data + universe.**

**"Do X next" recommendation:** Adopt **SimFin BASIC** as the fundamentals source. Build the **S&P 500 PIT membership panel** as the ticker universe. Compute the six **Value / Quality / Accruals factors** specified in §3 below. Validate on a 4-cell harness (compounder vs SPY vs 60/40 vs no-fundamentals proxy) before flipping the M2 enable. This is the first sequenced unit of work; it does not require any further research before kickoff.

---

## 1 — Data Source Decision

**Choice:** SimFin BASIC, $420/yr (40 % annual discount applied).

Detailed comparison and risks: `docs/Audit/ws_f_fundamentals_data_scoping.md`. Summary:

| Property | Value |
|---|---|
| Cost | $420/yr |
| US ticker coverage | ~5,000 |
| Historical depth | 15 years |
| PIT discipline | Approximated via `PUBLISH_DATE` join; bias toward latest-restated values is documented and accepted for value/quality, flagged for accruals |
| Update lag | 1-3 days post-filing |
| Schema for V/Q/A factors | All six factors below are computable directly from SimFin's bulk income / balance-sheet / cashflow tables |
| Integration cost | ~1 day (column-rename in existing `engines/data_manager/fundamentals/loader.py`) |
| Fallback for tail / audit | SEC EDGAR `companyfacts` JSON (free, no key) |

**Pre-commit gate:** Validate the **FREE** SimFin tier against 5 random S&P 500 names matched to EDGAR `companyfacts`. Exact match expected on Revenue, Net Income, Total Assets, Cash. If validation passes, upgrade to BASIC.

---

## 2 — Universe Scope

### 2.1 Target

**S&P 500 historical PIT membership panel, 2010-01-01 → present.** Approximately 500 names per year, with adds and drops correctly applied, including delisted names (Lehman, GE pre-spin, Pacific Gas pre-bankruptcy, Sears, Bed Bath & Beyond, etc.).

This directly addresses the failure mode in `project_compounder_synthetic_failed_2026_05_02.md`: at 51 names, top-quintile = 10 names = "the 10 most defensive mega-caps" ≈ low-vol-tilted SPY. At 500 names, top-quintile = 100 names — enough cross-sectional dispersion for factor signals to actually rank.

### 2.2 Construction

1. **Membership history:** Wikipedia "List of S&P 500 companies — Historical changes" tables, scraped or pulled from a maintained dataset (e.g., the `martinellison/sp500-historical` GitHub repo, or directly from S&P's published index methodology archive).
2. **Price panel:** existing yfinance ingest (already used by `path_c_synthetic_compounder.py`).
3. **Fundamentals panel:** SimFin bulk download, filtered to membership-active tickers as of each rebalance date.
4. **Survivorship:** Drop-out tickers stay in the panel through their delisting date; their post-delisting positions are zeroed (no rebalance into them).

### 2.3 Why S&P 500 not Russell 1000

Russell 1000 is theoretically better (more dispersion, more academic factor papers use it). But:

- SimFin coverage is ~5,000 US tickers, which includes the Russell but the **PIT membership reconstruction for Russell 1000 is harder** (Russell published methodology shifts; FTSE Russell does not freely publish historical constituents the way Wikipedia mirrors S&P 500 lists).
- A 500-name universe is already 10× the synthetic-test universe and is large enough for factor cross-sections.
- If S&P 500 + factors works, expanding to Russell 1000 is a separate sub-task and is not blocking for the M2 feasibility decision.

### 2.4 Out of scope for the first cut

- Mid-cap and small-cap.
- International (developed or emerging).
- Sector-relative ranking (we'll start with universe-relative; sector neutrality is a Phase M3 enhancement).

---

## 3 — Factor Definitions

Six factors, three families. All are computed using SimFin fields with `PUBLISH_DATE` for PIT alignment. Each becomes a Foundry feature (`@feature` decorator, the `(ticker, dt) -> Optional[float]` shape; reference: `core/feature_foundry/features/dist_52w_high.py`).

### 3.1 Value family (2 factors)

**`value_ep_yield`** — Earnings-to-price (E/P), trailing twelve months.

```
EP_yield(t,i) = TTM_NetIncomeLoss(i, as_of=t) / MarketCap(i, t)
```

Foundry metadata: `tier="A"`, `horizon=63` (~3 mo), `license="commercial"`, `source="simfin"`.

**`value_bp_yield`** — Book-to-price (B/P), most recent quarterly book value.

```
BP_yield(t,i) = StockholdersEquity(i, as_of=t) / MarketCap(i, t)
```

Foundry metadata: `tier="A"`, `horizon=63`, `license="commercial"`, `source="simfin"`.

### 3.2 Quality family (2 factors)

**`quality_roic`** — Return on invested capital, TTM.

```
ROIC(t,i) = TTM_OperatingIncome(i, as_of=t) × (1 - effective_tax_rate)
            / (StockholdersEquity + TotalDebt - Cash)(i, as_of=t)
```

Use a constant 21 % federal corporate rate as the effective tax rate proxy if SimFin doesn't expose it directly. Foundry metadata: `tier="A"`, `horizon=63`.

**`quality_gross_profitability`** — Gross profitability (Novy-Marx 2013), the highest-Sharpe quality variant in the academic literature.

```
GP(t,i) = TTM_GrossProfit(i, as_of=t) / TotalAssets(i, as_of=t)
```

Foundry metadata: `tier="A"`, `horizon=63`.

### 3.3 Accruals family (2 factors)

**`accruals_sloan`** — Sloan working-capital accruals (Sloan 1996), inverted so high values = low accruals = high-quality earnings.

```
ΔWC(t,i) = (CurrentAssets - Cash)_t  -  (CurrentAssets - Cash)_{t-1y}
         - [(CurrentLiabilities - ShortTermDebt)_t  -  (CurrentLiabilities - ShortTermDebt)_{t-1y}]

Sloan(t,i) = -ΔWC(t,i) / TotalAssets(i, t)
```

Foundry metadata: `tier="A"`, `horizon=63`. **Flagged as PIT-approximate per the SimFin restatement caveat — restatements correlate with the signal, so backtest results require an EDGAR cross-validation pass before promotion.**

**`asset_growth_inverse`** — Cooper-Gulen-Schill (2008) asset growth, inverted so high values = low growth = high quality.

```
AssetGrowth(t,i) = (TotalAssets_t  -  TotalAssets_{t-1y}) / TotalAssets_{t-1y}
AGI(t,i) = -AssetGrowth(t,i)
```

Foundry metadata: `tier="A"`, `horizon=63`.

### 3.4 Composite (the compounder edge signal)

```
composite(t,i) = mean(zscore_universe(EP_yield),
                      zscore_universe(BP_yield),
                      zscore_universe(ROIC),
                      zscore_universe(GP),
                      zscore_universe(Sloan),
                      zscore_universe(AGI))
```

Top-quintile of `composite` becomes the compounder basket. **This replaces the four price-derived proxies used in the synthetic.**

---

## 4 — Validation Plan (how do we know factors are orthogonal to SPY)

The synthetic FAILED partly because the price-derived proxies were not orthogonal to SPY. The validation discipline for the real-data version:

### 4.1 Per-factor pre-flight (before composite)

For each of the six factors, compute on the S&P 500 PIT panel and run the following diagnostics. **All six must pass before the composite is built.**

| Diagnostic | Pass criterion |
|---|---|
| Cross-sectional rank IC vs forward 1-year return | Mean IC ≥ 0.02 over 2010-2024 (academic literature shows 0.03-0.05 for these factors) |
| Factor return regressed on SPY return | R² ≤ 0.25 on monthly returns (factor is *meaningfully orthogonal* to market beta) |
| Long-short top-quintile vs bottom-quintile annualized return | ≥ 1 % gross spread |
| Coverage | ≥ 80 % of S&P 500 universe has a non-NaN factor value at each rebalance |

Factors that fail any criterion are dropped from the composite. The composite ships with whatever subset passes.

### 4.2 Composite-level test (4-cell harness)

| Cell | Universe | Factors | Expected behavior |
|---|---|---|---|
| **A** | S&P 500 PIT, real fundamentals | Six-factor composite | The candidate. Should beat SPY after-tax. |
| **B** | S&P 500 PIT, real fundamentals | Synthetic price-derived proxies (re-using the failed synthetic factors) | **Negative control.** Confirms the failure was the proxies, not the strategy. |
| **C** | 51-name curated, real fundamentals | Six-factor composite | Confirms universe size matters. |
| **D** | SPY buy-and-hold | n/a | Baseline. |

Plus the existing 60/40 from the synthetic harness as a **floor** check.

### 4.3 Pass criteria for M2 enable

Reusing the pre-committed criteria from the synthetic test:

1. Compounder after-tax CAGR > SPY after-tax CAGR over 2010-2024 (strict >).
2. Compounder MDD ≥ -15 % over 2010-2024 (the synthetic broke this at -25 %; if real fundamentals don't fix the MDD, the **regime-conditional intra-year de-gross** from `path_c_compounder_synthetic_backtest_2026_05.md` becomes a hard prerequisite for M2, not optional).

Both criteria must pass on Cell A. Failure on either pushes us to a regime-conditional de-gross redesign **before** M2 enable, not after.

### 4.4 Restatement-bias audit (accruals-only)

Sample 50 random ticker-year pairs from 2014-2020 (mature-XBRL window). For each, pull both:
- SimFin's stored values (latest restated).
- EDGAR `companyfacts` filings as-of the original `PUBLISH_DATE`.

If accruals computed from the two diverge by more than 10 % on more than 20 % of samples, the `accruals_sloan` factor is **demoted from `tier="A"` to `tier="B"`** in its Foundry metadata and excluded from the composite until we wire a true PIT pull. The other five factors are not gated by this audit — the bias on value and quality fields is small.

---

## 5 — Pre-existing Path C work that does NOT need to change

- **Sleeve abstraction (D1).** The interface, aggregator, and migration plan ship as designed. Path C unblock is about a new *implementation* of the compounder sleeve, not a new abstraction.
- **Tax model.** The 15 % LT cap-gains assumption with carry-forward is reusable.
- **Reproducibility script.** `scripts/path_c_synthetic_compounder.py` is the right shape; what changes is the input data (`fundamentals_static.csv` stub → live SimFin pull) and the factor compute (price-derived proxies → six real factors).
- **Capital-pct ramp gates (D1.5).** 5 % / 10 % / 15 % per gate, each requiring positive empirical evidence at the prior tier. No change.
- **Engine C integration.** The compounder is a sleeve, not an edge. Engine C aggregator already accepts sleeve outputs.

---

## 6 — Sequenced execution plan

Each step ends in a measurable, reviewable artifact. Each step can fail and abort the next.

| # | Step | Time est. | Pass artifact | If it fails |
|---|------|-----------|---------------|-------------|
| 1 | SimFin FREE signup; pull 5 random S&P 500 names; cross-check Revenue / Net Income / Total Assets / Cash against EDGAR | 0.5 day | Side-by-side comparison sheet, mean abs diff ≤ 1 % | Re-evaluate FMP or pure-EDGAR build |
| 2 | Wire SimFin → `engines/data_manager/fundamentals/loader.py` adapter; ingest current S&P 500 fundamentals | 1 day | Parquet at `data/processed/fundamentals.parquet` with PIT join verified on 5 names | Loader rewrite |
| 3 | Build S&P 500 PIT membership panel | 1 day | Parquet at `data/processed/sp500_membership.parquet` with adds/drops 2010-2024 | Reduce universe to current S&P 500 + accept survivorship caveat for first feasibility cut |
| 4 | Implement 6 factors as Foundry features; per-factor pre-flight diagnostics | 1.5 days | Diagnostic table per §4.1; subset of factors passing pre-flight | Drop failing factors from composite; if <4 pass, abort and revisit factor library |
| 5 | Run 4-cell harness from §4.2 | 1 day (mostly compute) | `data/research/path_c_real_fundamentals_4cell.json` + summary doc | If Cell A fails pass criteria, do NOT enable M2; redesign with regime-conditional de-gross |
| 6 | Restatement-bias audit per §4.4 (accruals only) | 0.5 day | Audit table; demote-or-keep decision on `accruals_sloan` | Demote to tier B; drop from composite for v1 |
| 7 | Upgrade SimFin to BASIC ($420/yr) **only after step 5 passes**, then run with full 15-yr history | 0.5 day | New harness run on 2010-2024 vs the 2015-2024 free-tier window | If the longer history changes the conclusion, flag for review |
| 8 | M2 enable proposal (capital pct ramp gate per D1.5) | 0.5 day | Proposal doc with go/no-go recommendation | n/a — this is the deliverable |

**Total time-to-decision:** ~5-6 working days **after** approval to spend $420 (and assuming the FREE-tier validation in step 1 passes).

**Total cost-to-decision:** $0 (steps 1-6 fit inside SimFin FREE), then $420/yr conditional on step 7.

---

## 7 — What this plan does NOT promise

- **It does not promise the compounder will pass the 4-cell harness.** Two outcomes are likely:
  1. Real fundamentals + S&P 500 universe = positive Cell A, M2 enable proceeds.
  2. Real fundamentals + S&P 500 universe = improvement over the synthetic but still falls short of SPY after-tax. In this outcome we have a clean falsifying result on the *strategy*, not on the *data layer*, and the compounder thesis is structurally weak. That is a valid project outcome and should be documented as a `project_compounder_real_data_falsified_*.md` memory.
- **It does not promise SimFin's PIT-approximation is good enough for accruals factors.** The §4.4 audit is the gate. If the audit fails, accruals get demoted and we ship a 5-factor composite instead.
- **It does not promise the universe scope decision is final.** If S&P 500 PIT works, it works. If it shows promise but is undersized, expand to Russell 1000 in a follow-up cycle.

---

## 8 — Audit of `noterminusgit/statarb` (statistical-arbitrage repo, ~35 strategies)

Per the task. Read this section if you want to know whether to mine the repo for additional Foundry features or portfolio-optimizer modules.

### 8.1 Strategy inventory (35 strategies, 7 families)

| Family | Count | Files | Fundamentals required? | Foundry-portable? |
|---|---|---|---|---|
| **High-Low Mean Reversion** | 6 | `hl.py`, `hl_intra.py`, `qhl_intra.py`, `qhl_multi.py`, `qhl_both.py`, `qhl_both_i.py` | No — daily OHLCV only | **Yes, low effort** — fits Foundry feature shape directly |
| **Beta-Adjusted Order Flow** | 9 | `bd.py`, `bd1.py`, `bd_intra.py`, `badj_*` (multi/intra/both/dow/2_*) | Some need Barra factor exposures (see optimizer); the simpler `bd` variants are price+volume only | **Mixed** — price-only variants port; Barra-dependent variants need a beta proxy |
| **Analyst Signals** | 4 | `analyst.py`, `analyst_badj.py`, `rating_diff.py`, `rating_diff_updn.py` | **Yes — IBES analyst database** (consensus EPS, median estimates, std dev, analyst count) | **No** — IBES is a paid Refinitiv product; out of budget. Skip these strategies. |
| **Earnings & Valuation** | 3 | `eps.py`, `target.py`, `prod_tgt.py` | Earnings dates, actual vs estimate EPS, price targets | **Partial** — actual EPS is in SimFin/EDGAR, but consensus estimates and price targets are not. Could approximate `eps.py` (earnings drift / PEAD-style) using just actual EPS and event dates from yfinance (already wired per memory `project_finnhub_free_tier_no_historical_2026_04_25.md`). |
| **Volume-Adjusted** | 5 | `vadj.py`, `vadj_multi.py`, `vadj_intra.py`, `vadj_pos.py`, `vadj_old.py` | No | **Yes, low effort** |
| **PCA & Residuals** | 3 | `pca_generator.py`, `pca_generator_daily.py`, `rrb.py` | `rrb.py` needs Barra factors; `pca_generator*` is self-contained | **Mixed** — PCA-only variants port |
| **Specialized** | 5 | `c2o.py` (close-to-open), `mom_year.py`, `ebs.py`, `htb.py`, `badj_rating.py` | `mom_year.py` and `c2o.py` are price-only; `ebs.py` and `badj_rating.py` need analyst data; `htb.py` needs hard-to-borrow data | **Mixed** |

**Foundry-portable count without buying new data:** ~16-18 strategies (HL family, simple BD variants, vadj family, PCA-only variants, `c2o.py`, `mom_year.py`).

### 8.2 What "Foundry-portable" means concretely

The Foundry's `@feature` decorator wants `(ticker, dt) -> Optional[float]`. The statarb strategies in the repo are written as **panel-level signal generators** — they ingest a panel and emit a panel of signals. Porting a single statarb strategy to a Foundry feature is roughly:

1. Read the strategy's signal computation (typically 50-200 LOC).
2. Refactor to single-ticker, single-date callable: pull the lookback window, compute the signal scalar, return.
3. Add Foundry metadata.

**Per-strategy port cost: ~1-3 hours for the price-only family.** A bulk port of the 16-18 portable strategies is ~3-5 days of work. **Not on the critical path for Path C compounder unblock**, but a clean follow-up if the compounder ships and we need to expand the active edge count past 3 to make HRP composition useful (memory `project_hrp_slice_3_paused_small_ensemble_2026_05_02.md`).

### 8.3 Portfolio-optimizer module — `opt.py`

The repo has **one optimizer module: `opt.py`, ~707 LOC**, doing mean-variance optimization with realistic transaction-cost modeling.

**Inputs:**
- `g_mu`: alpha signals (expected returns).
- `g_factors`: factor loadings matrix.
- `g_fcov`: factor covariance matrix.
- Position bounds, liquidity, vol, market cap.

**Risk model:** explicit Barra-style two-component (specific risk + factor risk), `κ(σ²·x² + x'Fx)`.

**Solver:** `scipy.optimize.minimize` with `trust-constr`.

**Drop-in replacement for our `weighted_sum` baseline?** **No, not without significant glue.** The optimizer assumes Barra factor exposures are provided externally. We do not have Barra. Substituting our own factor model (PCA from returns, or HRP-style hierarchical) is possible but is **a port, not a drop-in.**

**Realistic positioning of `opt.py` in our stack:** It is **architecturally aligned with where Engine C is heading** (Sharpe-aware optimization with cost modeling) but does not slot in cleanly to our current `weighted_sum` aggregator. It is more useful as a **reference implementation** for what an Engine C v3 optimizer should look like once HRP slice work resumes (currently paused per memory `project_hrp_slice_3_paused_small_ensemble_2026_05_02.md`). The transaction-cost model in `opt.py` (slippage = `γ · vol · participation^β + ν · vol · (Δpos/advpt)^β`) is genuinely useful and worth borrowing into our cost model.

**Recommendation on `opt.py`:** Do not adopt as-is. Borrow the transaction-cost formulation for our cost model when we revisit HRP. License is Apache 2.0 — borrowing snippets with attribution is fine.

### 8.4 Bottom line on statarb audit

- Repo is high-quality and architecturally well-designed but heavily dependent on data we cannot afford (IBES analyst data, Barra factors).
- ~16-18 of 35 strategies are price/volume-only and could be ported to Foundry features in ~3-5 days. Not on Path C critical path; queue as a separate workstream once active edge count needs to grow for HRP.
- The optimizer module is a useful architectural reference for Engine C v3 but not a drop-in. Borrow its transaction-cost model.
- Path C is unblocked by **fundamentals data**, not by mining this repo. **The statarb repo is a separate opportunity, not a Path C dependency.**

---

## Final recommendation — what to do next

Adopt **SimFin BASIC** as the fundamentals source. Build the **S&P 500 PIT membership panel** as the ticker universe. Compute the **six Value / Quality / Accruals factors** specified in §3. Run the **4-cell harness** in §4.2 with M2-enable contingent on Cell A passing both pre-committed criteria (after-tax CAGR > SPY, MDD ≥ -15 %).

**Concrete action item, ready to schedule without further research:**

> Workstream F kickoff — sign up SimFin FREE, validate 5 S&P 500 names against EDGAR, wire the SimFin-shaped adapter into `engines/data_manager/fundamentals/loader.py`, and produce the per-factor pre-flight diagnostic table in §4.1. Time-boxed at 3 working days. Output is a go/no-go on the BASIC purchase and on continuing to the 4-cell harness.

Statarb-repo mining is **not** on this critical path; it is a parallel follow-up once active edge count needs to grow.
