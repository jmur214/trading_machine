# Path C — Real-Fundamentals Wiring (2026-05-05)

**Status:** WIRED, not yet validated. Director directive: do NOT run the 4-cell harness in this session.

**Branch:** `path-c-real-fundamentals` (worktree `agent-a6891c49be3f9c6a0`)

**Predecessor failure:** `project_compounder_synthetic_failed_2026_05_02` — synthetic compounder underperformed SPY (CAGR 12.03% vs 13.69%, MDD -25.19%). Hypothesis was that the failure was driven by (a) a 51-name universe too small for cross-sectional factor work, and (b) price-derived factor proxies that aren't orthogonal to SPY.

**This change:** Replace both. Universe → S&P 500 ex-financials ∩ SimFin coverage. Factors → six V/Q/A primitives from real fundamentals (SimFin FREE adapter shipped 2026-05-05).

---

## What changed

**`scripts/path_c_synthetic_compounder.py`** — Same file, both code paths now coexist:

| Function                                    | Purpose                                                   |
|---------------------------------------------|-----------------------------------------------------------|
| `compute_composite_score_synthetic`         | Original 4 price-derived factors. Cell C of harness.      |
| `compute_composite_score` (alias)           | Backwards-compat → points at `_synthetic`.                |
| `compute_composite_score_real`              | NEW — 6 V/Q/A factors from SimFin. Cell D of harness.     |
| `build_universe`                            | NEW — S&P 500 ex-financials ∩ SimFin (~359 tickers).      |
| `run_compounder_backtest`                   | Now takes `panel` + `use_real_fundamentals` kwargs.       |

The script's `__main__` block is now guarded: with no args it prints a wiring summary and exits; `--run` triggers the 4-cell harness. The director's directive is encoded in code: the harness does **not** auto-run on import or invocation.

**`tests/test_path_c_real_fundamentals.py`** — 11 new tests. All pass.

---

## Universe

```
S&P 500 current constituents     —  523 tickers (Wikipedia, cached weekly)
  drop GICS Financials sector    —  447 tickers
  drop hard-exclude backstop     —  ~440 tickers
  intersect SimFin coverage      —  359 tickers
```

The hard-exclude list (`FINANCIALS_HARD_EXCLUDE`) is a belt-and-suspenders backstop on top of the GICS sector filter. It catches edge cases like BLK / V / MA which SimFin happens to cover but which we still treat as Financials for V/Q/A composition purposes.

**Coverage gaps observed on SimFin FREE:**
- All large banks: JPM, BAC, C, WFC, GS, MS, USB, PNC, TFC (matches the spec).
- CVX is in the panel but with only 1 quarter of history (2025-Q1 publish), so it gets PIT-filtered out for any 2024 rebalance. This is a real coverage gap on SimFin FREE, not a bug — the BASIC tier likely has 5-15 years of CVX history.
- ~100 names that are in S&P 500 but not in SimFin's US universe (foreign-domiciled, REITs, etc.).

---

## V/Q/A factor composition (Cell D)

Six factors, equal-weighted on cross-sectional rank-percentile:

| Factor                  | Family    | Formula                                                                | Direction      |
|-------------------------|-----------|------------------------------------------------------------------------|----------------|
| `earnings_yield_market` | Value     | TTM_NetIncome / market_cap                                             | high = cheaper |
| `book_to_market`        | Value     | total_equity / market_cap                                              | high = cheaper |
| `roic_proxy`            | Quality   | TTM_OperatingIncome × (1 − 0.21) / (equity + LT_debt)                  | high = better  |
| `gross_profitability`   | Quality   | TTM_GrossProfit / total_assets (Novy-Marx 2013)                        | high = better  |
| `inv_sloan_accruals`    | Accruals  | −sloan_accruals (precomputed by SimFin adapter)                        | high = better  |
| `inv_asset_growth`      | Accruals  | −asset_growth (precomputed by SimFin adapter)                          | high = better  |

**Methodological notes:**
- TTM (trailing twelve months) for flow items requires summing the most recent 4 quarterly publishes available with `publish_date <= as_of`. Tickers with fewer than 4 quarters of history are dropped from that rebalance.
- Market cap is computed at backtest time as `as_of_price × shares_diluted_at_latest_publish`. PIT-correct.
- ROIC tax rate is constant 21% (federal statutory). SimFin doesn't expose effective tax rate; for cross-sectional ranking this is fine — we're ranking, not measuring absolute returns.
- Negative-equity tickers get NaN on `book_to_market` rather than a misleading sign-flipped value. NaN factors are excluded from that ticker's composite mean (handled by `pd.rank(pct=True)` + `.mean(skipna=True)`).

---

## Sample composite scores (eyeball sanity check)

Computed as of 2024-06-14, on the 38-ticker overlap of the cached price panel and the universe (the harness will use the full 359-name universe at runtime — this subset is just for diagnostic).

**Top of cross-section (cheapest + highest quality):**
```
UPS    0.730       Big-cap industrial, depressed multiple, high ROIC
NKE    0.724       Retailer trading near 5-year-low P/E
XOM    0.712       Cheap energy on book + earnings yield
JNJ    0.695       Defensive value, high gross profitability
HD     0.682       High ROIC + low asset-growth
MCD    0.673       High gross profitability, mature low-growth
```

**Bottom of cross-section (most expensive / lowest quality):**
```
TXN    0.396       High P/E semis
TMO    0.392       Premium-multiple lab tools
ORCL   0.384       Stretched on earnings yield post-rally
GE     0.377       Asset growth high (post-spin)
INTC   0.359       Negative ROIC drag
LLY    0.329       Highest-multiple pharma, GLP-1 premium
PFE    0.283       Negative TTM net_income → very low E/P
MMM    0.178       Lawsuits-depressed equity (negative book/market signal)
```

Both ends pass the eyeball test. The ranking is doing what the academic V/Q/A literature predicts:
- Pharma's expensive growth names (LLY) sit at the bottom; cheap pharma (PFE) is also low because its TTM earnings are negative — the factor sees that as low quality, not cheapness.
- TSLA was confirmed at 0.21 (well below the median) on a separate diagnostic — the factor model penalizes high P/E + low gross profitability + high asset growth simultaneously.
- LOW (Lowe's), NVR (homebuilder), and EXPD (logistics) topped the broader 50-ticker sample with composite > 0.78 each. All three are textbook high-ROIC, low-asset-growth, reasonable-multiple names.

---

## Known limitations

1. **No PIT membership tracking.** `build_universe()` returns *current* S&P 500 constituents. A ticker that was in S&P 500 in 2021 but dropped in 2023 won't appear in any historical rebalance, even though it should at its 2021 rebalance. This is survivorship bias on the universe side. The eventual harness should use `SP500MembershipLoader.historical_constituents(as_of)` per rebalance — not done in this round to keep the wiring scope tight.

2. **Financials excluded.** SimFin FREE doesn't cover most banks; we drop the entire GICS Financials sector. This means the universe doesn't represent "S&P 500" — it represents "S&P 500 ex-financials." The composite's claims about Sharpe / CAGR will only be meaningful for a non-financials sleeve.

3. **SimFin restatement bias on accruals.** The adapter's docstring flags this: SimFin reports latest-restated values keyed on `Publish Date`, which is PIT-defensible but can introduce restatement bias on the accruals factors (Sloan, asset_growth). The plan calls for an EDGAR cross-validation pass before any promotion to production; that work is out of scope for this wiring round.

4. **5-year window only.** SimFin FREE covers 2020-06-30 → 2025-04-30. Pre-2020 backtests can't use this composite. The 2010-2024 window in `START_DATE`/`END_DATE` constants is from the synthetic baseline — the harness will need to either (a) restrict to 2021-2024, or (b) upgrade to SimFin BASIC for the longer window.

5. **`compute_composite_score_real` is unvectorized.** The function loops over universe tickers, calling `panel.xs(ticker, ...)` for each. On the 359-ticker universe this is ~5 seconds per rebalance, which is fine for ~15 annual rebalances but would be a bottleneck if the cadence shortened to monthly. Optimization is a follow-on.

6. **ROIC denominator simplification.** Per the plan doc, full ROIC needs (equity + total_debt − cash). We use (equity + LT_debt) only. SimFin's `cash_and_st_investments` field is sparsely populated for some tickers; our fallback is methodologically defensible (academic ROIC variations differ on this) but worth flagging.

---

## What is NOT done in this round

- **The 4-cell harness has not been run.** Director directive: stop after wiring + tests pass.
- **No claim about strategy economic merit.** The wiring is in place; whether real fundamentals fix the synthetic's failure is an empirical question that gets answered next session.
- **No promotion to production.** This is feasibility-test scaffolding, not Engine A or Engine C wiring. The eventual production path runs through Engine D Discovery and the 4-gate validation pipeline, not through this script.
- **No SimFin BASIC purchase.** The plan's spend gate keeps us on FREE until a 4-cell harness verdict justifies the upgrade.

---

## Acceptance check (per spec)

| Requirement                                                                                                                                                  | Status     |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------|------------|
| `scripts/path_c_synthetic_compounder.py` modified with real-fundamentals composite alongside the synthetic baseline (both available)                        | DONE       |
| Universe is S&P 500 ex-financials intersected with SimFin coverage (~350-430 names)                                                                          | DONE (359) |
| Running `python scripts/path_c_synthetic_compounder.py` with no args prints the wired-up summary and exits — does NOT run the harness                         | DONE       |
| New tests pass; existing Foundry / observability tests still pass                                                                                            | DONE (11/11 + 37/37) |
| `docs/Audit/path_c_real_fundamentals_wired_2026_05_05.md` summarizes universe size, factor composition, sample composite score, known limitations            | DONE (this doc) |
| Branch: `path-c-real-fundamentals`                                                                                                                            | DONE       |
| 4-cell harness NOT run                                                                                                                                       | NOT RUN, BY DESIGN |

---

## Worktree paths

- Script: `/Users/jacksonmurphy/Dev/trading_machine-2/.claude/worktrees/agent-a6891c49be3f9c6a0/scripts/path_c_synthetic_compounder.py`
- Tests:  `/Users/jacksonmurphy/Dev/trading_machine-2/.claude/worktrees/agent-a6891c49be3f9c6a0/tests/test_path_c_real_fundamentals.py`
- Audit:  `/Users/jacksonmurphy/Dev/trading_machine-2/.claude/worktrees/agent-a6891c49be3f9c6a0/docs/Audit/path_c_real_fundamentals_wired_2026_05_05.md`
- Branch: `path-c-real-fundamentals`
