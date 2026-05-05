# Workstream F — Fundamentals Data Source Scoping

**Branch:** `agent-ac32a6dc9cf7f48b6` (research-only worktree)
**Date:** 2026-05-04
**Status:** Recommendation memo. Not yet acted on. No code changes.
**Author:** Workstream F scoping pass — research-only deliverable.
**Sibling:** `docs/Core/Ideas_Pipeline/path_c_unblock_plan.md`

---

## TL;DR — Recommendation

**Start with SimFin FREE ($0). Upgrade to SimFin BASIC ($420/yr) only if Path C compounder demonstrates real lift on the 5-year FREE-tier window — i.e., gate-conditional on the data layer paying for itself.** Director correction 2026-05-05: the original recommendation framed BASIC as primary, but the FREE tier covers exactly the 2021-2025 measurement window the Foundation Gate just validated, and the upgrade buys 10 additional pre-2021 years of history — important for statistical power but not blocking for a feasibility test. Use the SimFin bulk dataset's `PUBLISH_DATE` column (not `RESTATED_DATE`) to construct point-in-time panels in our own ingest layer — same approximation works on FREE and BASIC. Keep the SEC EDGAR `companyfacts` JSON API as a free secondary source for tail tickers SimFin doesn't cover and as ground-truth audit. **Do not pursue Compustat** — institutional licensing is wildly out-of-budget for retail scale, and **do not build an EDGAR XBRL parser from scratch** — every alternative is more expensive in engineering time than it returns in differentiation.

**Spend gate:** Don't pay $420 until SimFin FREE has demonstrated real fundamentals fix Path C. If FREE shows no Path C lift, neither would BASIC — saves $420 and tells us fundamentals alone aren't the unblock.

---

## Context

The Path C compounder synthetic FAILED on a 51-name curated mega-cap universe with price-derived factor proxies (`docs/Audit/path_c_compounder_synthetic_backtest_2026_05.md`, memory `project_compounder_synthetic_failed_2026_05_02.md`). Two prerequisites surfaced:

1. A real S&P 500 (or wider) point-in-time panel (universe scope).
2. Real fundamentals for value / quality / accruals factor families (this doc).

This memo addresses (2). Universe scope is a separate Workstream F sub-task; the data source decision here is independent of universe size, except where noted.

The codebase already contains a **PIT-aware ingest skeleton** at `engines/data_manager/fundamentals/loader.py`. It is hard-coded to FMP (Financial Modeling Prep) bulk-ratios CSV format. That code is not deployed (the `fundamentals_static.csv` stub used by the synthetic compounder is a 7-row placeholder), but it is the correct shape: `pd.merge_asof(..., direction="backward")` on `publish_date` is exactly the PIT join we need. **Whichever vendor we pick, the loader needs only a column-rename layer** — no architectural rewrite.

---

## Comparison matrix

| Dimension | **SimFin BASIC** (recommended) | **SEC EDGAR `companyfacts` API** (free fallback) | **Compustat / S&P CIQ** | **EDGAR direct + custom parser** | **FMP (already wired)** |
|---|---|---|---|---|---|
| **Annual cost (USD)** | **$420** ($35/mo × 12, 40 % annual discount applied) | **$0** (no key, no auth) | **~$3-70k+/yr** for individual / institutional access via WRDS or direct license; not retail-priced | **$0** data, but ~2-4 weeks engineering build | $19-79/mo (Starter through Premium) — also viable but already-known |
| **US ticker coverage** | ~5,000 US stocks (BASIC) | All 10-K / 10-Q / 8-K filers (~6,500 active companies) | 30,000+ global; 12,000 US | All XBRL filers since 2009 (~6,500 active US) | ~5,000+ US stocks |
| **Historical depth** | **15 years** on BASIC (10 yrs on START, 20+ yrs on PRO) | **2009-present** (XBRL mandate began phased rollout 2009) | 70+ years on US Compustat; PIT (Snapshot) variant available | 2009-present | ~30 years (varies by ticker) |
| **Point-in-time vs restated** | **Latest restatement by default**, BUT exposes both `PUBLISH_DATE` and `RESTATED_DATE` columns. ⚠ **Critical:** SimFin's docs explicitly state "the SimFin datasets are not so-called 'point-in-time' data." We approximate PIT by joining on `PUBLISH_DATE` and accepting that the figures themselves reflect the *latest* restatement — a known bias against value/accruals factors that catch earnings-management restatements. | True "as-filed" — the filing JSON is the actual filed numbers. Restatements appear as **new filings**, so a careful consumer can reconstruct true PIT by date-filtering to filings ≤ as-of date. | **Compustat Snapshot** is industry-standard PIT. **Compustat Standard** is restated (same problem as SimFin). The Snapshot is a separate paid product and is the reason academic papers pay for it. | True PIT achievable with care (same as `companyfacts` API) | Provides `fillingDate`. Loader treats this as `publish_date`. Same bias as SimFin's `PUBLISH_DATE`. |
| **Schema completeness — Value** (P/E, P/B, P/S, EV/EBITDA) | **Yes** — direct ratios + raw inputs (Revenue, Net Income, Book Value, Total Debt, Cash, Shares Out) | **Partial** — raw fields available (Revenues, Assets, StockholdersEquity, etc.) but ratios must be computed; market-cap inputs (shares outstanding) are present, market data (price) is not — bring your own | **Yes** — every standard ratio | **Partial** — same as `companyfacts` (raw fields, you compute ratios) | **Yes** — `peRatio`, `priceToSalesRatio`, `priceToBookRatio` precomputed |
| **Schema completeness — Quality** (ROE, ROIC, ROA, gross margin, FCF margin) | **Yes** — full income statement + balance sheet + cash flow | **Partial** — raw fields present, you compute | **Yes** | **Partial** — same as `companyfacts` | **Yes** — `roe`, `roic`, `returnOnAssets`, `grossProfitMargin`, etc. |
| **Schema completeness — Accruals** (working-capital accruals, total accruals, asset-growth, net-issuance) | **Partial → Yes** — Sloan accruals can be computed from balance-sheet deltas (ΔWC, ΔAccounts Receivable, ΔInventory) which SimFin provides; net-issuance is a multi-period diff of shares outstanding | **Partial → Yes** — same components are in `us-gaap:AccountsReceivableNetCurrent`, `us-gaap:InventoryNet`, `us-gaap:CommonStockSharesOutstanding`. Construction is identical, just from a different feed | **Yes** — Sloan-style accruals are first-class in WRDS | **Partial → Yes** — same as `companyfacts`, with the parser tax | **Partial** — FMP exposes some balance-sheet line items but the bulk-ratios endpoint is ratio-only; would need `historical-balance-sheet-statement` endpoint too |
| **Update lag** | **~1-3 days** post-filing for the standard SimFin dataset | **<1 minute** processing delay (real-time as filings disseminate) | <1 day | <1 minute | ~1 day |
| **API rate / bulk** | BASIC: 15,000 high-speed credits / month, ~10 req/s; **bulk CSV download for backtests** (preferred path) | No keys, no auth, no rate limit posted but expects "fair use"; bulk dataset downloads available quarterly | WRDS: bulk SQL pulls; CIQ direct: REST | Same as `companyfacts` for raw, plus your parser layer | Generous on Premium; bulk endpoints |
| **Engineering cost to integrate** | **Low** — column-rename in `engines/data_manager/fundamentals/loader.py` (already FMP-shaped); ~1 day to wire bulk download + ingest cron | **Medium** — need to walk `companyfacts` JSON, denormalize concept→time-series, dedupe (the API returns duplicate amounts across overlapping filings — a known gotcha), unit-normalize. ~1 week | N/A (cost-blocked) | **High** — XBRL is verbose and tag-set is sparse on small filers. Reference repos (`pysec`, `secdatabase/SEC-XBRL-Financial-Statement-Dataset`) exist but are stale (pysec last touched 2014-ish, `datasets/edgar-financials` returns 404). Realistic build: 2-4 weeks for a system covering ~50 fields with edge-case handling for unit/scale/period mismatches | **Already wired** — but partial schema |
| **Data quality / provenance** | Aggregated from filings; some manual review per their blog post on data quality. Known to have gaps on micro-caps and recent filings | Authoritative — filings are the source of truth. But raw filings have inconsistent tagging (companies use custom extensions to us-gaap) | Highest quality; most peer-reviewed academic factor papers use this | Same as `companyfacts` plus your parser adds an error layer | Aggregated; quality varies; community reports of bad data on ratios |
| **License** | Commercial (paid tier permits backtesting and internal use; redistribution restricted) | Public domain (US government work) | Commercial, restrictive | Public domain | Commercial |

### Notes on the comparison

- **PIT discipline is the most important property and the place all free/cheap sources lose to Compustat.** SimFin and the `companyfacts` JSON store a single "latest restated" value per period; rebuilding true PIT requires iterating filings in time order and snapshotting "what was known as of date D." For our use (annual rebalance compounder on a value/quality composite), the PIT-approximation by `PUBLISH_DATE` is a **first-cut acceptable** approach. Restatements bias the *measured* alpha favorably (we see what was true in hindsight, not what was reported). That bias is small for slow-moving balance-sheet items (book value, total debt, shares outstanding) and **larger for accruals and earnings-management-flavored signals**. We will document this bias in our backtest reports.
- **The FMP wiring already in `loader.py` is not wasted work.** SimFin's bulk-CSV schema can be mapped to FMP's column names with a tiny adapter; the merge_asof PIT logic is unchanged.
- **EDGAR direct via `companyfacts` is the right *fallback*, not the right primary.** It is the audit ground-truth and the right path if SimFin's coverage proves inadequate for our universe (see `path_c_unblock_plan.md` for the universe definition we need to satisfy).

---

## Detailed reasoning

### Why SimFin BASIC over Compustat

Compustat is the gold standard. The honest reason we are not buying it: **even individual / non-institutional pricing is in the $3k-$70k/yr range** depending on which datasets and Compustat Snapshot vs Standard. At our retail capital scale (`project_retail_capital_constraint_2026_05_01.md`: $5K-$15K AUM), data cost > 5 % of capital is unjustifiable when SimFin BASIC at $420/yr gives us 90 % of the schema and a defensible PIT approximation. The cost gap is **two orders of magnitude**, and the marginal alpha from "latest restated → true PIT" is not two orders of magnitude — it is a single-digit-percent measurement bias on accruals signals.

If the system grows to sub-institutional AUM where Compustat starts to make sense (mid-six-figures, multi-strategy, cross-sectional factor scale), revisit. Until then, this is a forced choice driven by retail economics, not a quality preference.

### Why SimFin BASIC over the SEC EDGAR `companyfacts` API alone

Free is tempting. The dealbreakers are:

1. **Engineering time cost.** Walking `companyfacts` JSON, deduping, unit-normalizing, computing ratios is realistically a **week of focused work** vs **a day** to wire SimFin's bulk-CSV download. At our delivery cadence, $420/yr buys us 6 working days back. That is a clean trade.
2. **Coverage tail.** SimFin's ~5,000 US tickers cover everything we'd want for a Russell 1000 / S&P 500 universe with margin to spare. EDGAR covers more, but the coverage tail is small-cap names where XBRL tagging quality drops sharply (custom us-gaap extensions, missing fields). For a compounder strategy that targets large/mid-cap by design, the EDGAR coverage edge does not buy us anything.
3. **Pre-computed ratios.** SimFin gives us `peRatio`, ROIC, accruals components ready to go. EDGAR gives raw line items only — every ratio and every accruals construction is our problem to write and validate.

EDGAR `companyfacts` stays in the design as the **secondary ground-truth**: when SimFin and EDGAR disagree on a number, EDGAR is right. When SimFin doesn't cover a ticker we need, EDGAR is the fallback.

### Why not roll our own EDGAR XBRL parser

The two reference repos in the task are both red flags:

- **`datasets/edgar-financials`** returns **HTTP 404** — the repo is gone or moved. Stale enough that even GitHub no longer serves it.
- **`lukerosiak/pysec`** is a Django-based XBRL parser with **25 total commits, no releases, GNU GPL license**. The XBRL parsing is "translated from VB script." Stale, low-confidence, and the GPL license has implications for any code we cargo-cult from it.

A more credible reference is **`secdatabase/SEC-XBRL-Financial-Statement-Dataset`** (a packaged dataset and parser) and the actively-maintained **`dgunning/edgartools`** Python library — but using those is itself an integration project. Neither closes the gap to "ratios are computed and PIT joins work" without further glue.

Build vs buy math: 2-4 weeks of engineering to replicate what SimFin gives us for $420/yr. Buy.

### Why not stay on FMP (already wired)

FMP is also a perfectly reasonable choice. The reasons to migrate:

1. **FMP has had ratio-quality complaints** in the community (incorrect normalization of trailing fields, occasional bad data on small-caps).
2. **The `loader.py` is already FMP-shaped** but no one is actually paying FMP and feeding it data. Switching to SimFin at this point is the same engineering work whether we move from "FMP-shaped stub with no data" to SimFin or to live FMP.
3. **SimFin's data-quality blog and explicit `RESTATED_DATE` tracking signals more discipline about what is actually known when** — it's the kind of thing we want from a vendor on a system that takes determinism seriously.

This is a soft preference. If a reader pushes back hard for FMP we'd reconsider — they are within rounding distance on every dimension. The deciding factor is SimFin's explicit commitment to surfacing publish vs restate dates, which we can use to build a better PIT join than FMP's `fillingDate` alone.

---

## Risks and known gaps

1. **PIT bias from latest-restatement values.** SimFin's standard dataset gives us the *latest restated* numbers as of the most recent restatement, even when we filter on `PUBLISH_DATE`. This means a backtest at date D sees the *eventual* numbers for periods ending ≤ D, not the *originally reported* numbers. For value (P/B, P/E) the bias is small (book value and earnings rarely get materially restated). For **accruals, working-capital changes, and earnings-quality signals the bias is real** — restatements are *correlated* with the very signal we are trying to extract. **Mitigation:** flag accruals-style factors as "PIT-approximate" in their feature metadata; cross-check against EDGAR `companyfacts` filings on a sample of ~50 names per year before promoting any accruals-based factor edge.
2. **Survivorship bias in any ticker list.** This is a universe problem, not a fundamentals-source problem, and is addressed in `path_c_unblock_plan.md`. SimFin claims ~5,000 US tickers but does not explicitly market a delisted-included historical panel. **Verify on intake** — pull a 2010-vintage S&P 500 list and confirm SimFin returns fundamentals for names that delisted (e.g., Lehman Brothers, GE pre-spinoffs, Pacific Gas pre-bankruptcy).
3. **Free-tier evaluation period.** Before paying for BASIC, run a 1-week trial on the **SimFin FREE tier** (5 yr depth, 5,000 tickers, 500 high-speed credits/mo, bulk download limited): pull 100 tickers, validate against EDGAR for 5 random names, confirm `PUBLISH_DATE` plumbing works through `loader.py`. **If the free tier delivers the schema we need, the paid tier is buying history depth (15 yr vs 5 yr) and bulk access — both important but not blocking for a first feasibility run.**
4. **Vendor risk.** SimFin is a small company, not S&P. Mitigated by EDGAR fallback path being permanently available.

---

## Decision

**Source (now):** SimFin FREE, $0. Covers 5 years (2021-2025), ~5,000 US tickers, 500 high-speed credits/month, bulk download with limits.
**Source (gated upgrade):** SimFin BASIC, $420/yr — only after FREE-tier Path C run shows real fundamentals fix the synthetic-compounder failure (`project_compounder_synthetic_failed_2026_05_02.md`).
**Fallback:** SEC EDGAR `companyfacts` JSON API (free, no key) for ground-truth audit and tail-coverage.
**Universe:** Defined in `path_c_unblock_plan.md` (S&P 500 PIT panel target).
**Factor families enabled:** Value (Yes), Quality (Yes), Accruals (Yes — with PIT-approximation caveat).

**Sequenced actions (no $ commitment until step 5 says so):**

1. Sign up for SimFin FREE — no card required.
2. Pull bulk income / balance / cashflow CSVs for current S&P 500.
3. Validate 5 random tickers against EDGAR `companyfacts` — exact match expected on Revenue, Net Income, Total Assets, Cash; minor differences acceptable on derived ratios (different denominators).
4. Spike a 50-LOC SimFin → `engines/data_manager/fundamentals/loader.py` adapter (column rename; do not refactor the existing loader).
5. Run Path C compounder with real fundamentals on 2021-2025 (the Foundation-Gate-validated window).
6. **Decision point:**
   - **Real fundamentals produce demonstrable Path C lift** (CAGR > SPY, MDD ≤ -15% target met, statistical-significance check vs synthetic baseline) → upgrade to BASIC for 15-year history.
   - **No measurable lift** → fundamentals alone are not the Path C unblock; reassess whether the failure is data, universe, or factor design. $420 saved.

**Time-to-first-real-fundamentals-backtest:** 1-2 working days after sign-up. Spend gate: end of step 5.

---

## Sources

- [SimFin pricing page](https://www.simfin.com/en/prices/) — BASIC $35/mo or $420/yr, FREE tier 5,000 US stocks / 5 yr / 500 credits-per-month.
- [SimFin bulk dataset documentation, 01_Basics.ipynb](https://github.com/simfin/simfin-tutorials/blob/master/01_Basics.ipynb) — explicit "the SimFin datasets are not so-called 'point-in-time' data," documents `PUBLISH_DATE` and `RESTATED_DATE` columns.
- [SEC EDGAR companyfacts API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) — free, no auth, real-time, all XBRL filers.
- [SEC Financial Statement Data Sets](https://www.sec.gov/data-research/sec-markets-data/financial-statement-data-sets) — quarterly bulk CSV downloads.
- [Compustat WRDS overview](https://wrds-www.wharton.upenn.edu/) — institutional pricing only; informal community estimates put individual access at $3k+/yr.
- [pysec (lukerosiak)](https://github.com/lukerosiak/pysec) — stale, GPL, 25 commits, "translated from VB script." Reference for what *not* to use as the build target.
- Existing repo PIT logic: `engines/data_manager/fundamentals/loader.py` (FMP-shaped, ready to adapt).
