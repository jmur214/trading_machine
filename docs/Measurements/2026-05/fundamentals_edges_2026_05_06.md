# Fundamentals V/Q/A edges — 6-edge integration into Engine A

**Date:** 2026-05-06
**Branch:** `worktree-agent-ae9a84ea103bc8b7c` (worktree replaces dispatch's `fundamentals-edges-vqa`)
**Driver:** Engine A integration of the SimFin V/Q/A factor primitives previously
locked inside the deferred Path C compounder. Separates factor signal from
sleeve packaging — these edges contribute per-ticker, per-day to the active
ensemble at default weight 1.0.

## What shipped

Six new long-only edges in `engines/engine_a_alpha/edges/` plus a shared
helper module:

| File | EDGE_ID | Factor type | Score function |
|---|---|---|---|
| `value_earnings_yield_edge.py` | `value_earnings_yield_v1` | Value | `TTM_NetIncome / market_cap` |
| `value_book_to_market_edge.py` | `value_book_to_market_v1` | Value | `total_equity / market_cap` (negative-equity dropped) |
| `quality_roic_edge.py` | `quality_roic_v1` | Quality | `NOPAT / (equity + LT_debt)`, NOPAT = `TTM_OpInc * (1 - 0.21)` |
| `quality_gross_profitability_edge.py` | `quality_gross_profitability_v1` | Quality | `TTM_GrossProfit / total_assets` (Novy-Marx) |
| `accruals_inv_sloan_edge.py` | `accruals_inv_sloan_v1` | Accruals | `-sloan_accruals` |
| `accruals_inv_asset_growth_edge.py` | `accruals_inv_asset_growth_v1` | Investment | `-asset_growth` |
| `_fundamentals_helpers.py` | (helper) | n/a | Cached panel access + cross-sectional top-quintile selection |

Each edge fires LONG when its score is in the **top quintile** of the
present-data subset of the active universe; everyone else gets 0. PIT
correctness enforced via `simfin_adapter.publish_date <= as_of`. TTM-flow
items require ≥4 published quarters; missing-data tickers are dropped from
the cross-section.

## Universe coverage stats (109-ticker prod universe)

```
Year  Total   In SimFin   with-data   top quintile  min_universe=30 fires?
--------------------------------------------------------------------------
2021  109     84          80          16            YES
2022  109     84          81          16            YES
2023  109     84          81          16            YES
2024  109     84          81          16            YES
2025  109     84          81          16            YES
```

- 25/109 tickers excluded by SimFin FREE coverage. Mostly financials
  (BAC, C, GS, JPM, MS, PG, SCHW, WFC, AXP) + a handful of others
  (GOOGL→GOOG ambiguity, IBM, HON, INTU, MO, VZ, AMT, SPY/QQQ benchmarks,
  RIOT, COP, CI, ELV, PGR, SO, VRTX).
- Top quintile = 16 names per edge per as_of. Some overlap between edges
  (especially within Quality and within Value pairs); orthogonality test
  in `tests/test_fundamentals_edges.py` ensures no two edges produce
  bitwise-identical selections.
- `min_universe=30` is the abstention floor. Coverage is well above it
  in all 5 years, so edges fire across the full 2021-2025 sweep — no
  start-of-window blackout.

## 2024 smoke run

**Setup:** `PYTHONHASHSEED=0 python -m scripts.run_multi_year --years 2024 --runs 1`

The isolated anchor was updated (`cp data/governor/edges.yml
data/governor/_isolated_anchor/edges.yml`) so the new edges survive
the snapshot/restore cycle.

| Metric | Value |
|---|---|
| Sharpe | **1.91** |
| CAGR | 8.13% |
| Max Drawdown | -2.75% |
| Win Rate | 53.9% |
| Wall time | 9.2 minutes |
| Canon md5 | `4ae83833f6d5a35ab941c979f167075b` |
| Run ID | `042d40db-52e2-4fdb-8fa2-c322725f126b` |

**Open-position contribution at 2024-12-31** (40 positions total across 9 edges):

| Edge | Open positions |
|---|---:|
| `value_earnings_yield_v1` | 11 |
| `quality_roic_v1` | 9 |
| `herding_v1` | 5 |
| `value_book_to_market_v1` | 4 |
| `quality_gross_profitability_v1` | 3 |
| `accruals_inv_asset_growth_v1` | 3 |
| `momentum_edge_v1` | 3 |
| `accruals_inv_sloan_v1` | 1 |
| `volume_anomaly_v1` | 1 |

**All 6 new edges contributed live capital.** None crashed; none silently
returned empty signals.

## Edge-by-edge expected behavior

- **`value_earnings_yield_v1`** — fires for low-P/E names with strong TTM
  earnings. 2024 picks skewed toward defensive cash-cows (e.g. consumer
  staples + healthcare with high earnings yield post-rate-rise).
- **`value_book_to_market_v1`** — favors companies with high book equity
  relative to market cap. Excludes negative-equity firms. Tends to
  overlap with `value_earnings_yield_v1` on classic value names but
  diverges on asset-light vs asset-heavy distinction.
- **`quality_roic_v1`** — favors capital-efficient compounders (high
  NOPAT / invested capital). Mega-caps with light balance sheets dominate
  (AAPL-class firms with high TTM operating income / modest debt).
- **`quality_gross_profitability_v1`** — Novy-Marx; favors high gross
  margin × asset turnover. Software, payments, and other asset-light
  high-margin businesses cluster here. Should be partially anti-correlated
  with `value_book_to_market_v1` (Novy-Marx's whole point — quality picks
  the OTHER side of value).
- **`accruals_inv_sloan_v1`** — favors firms whose net income closely
  tracks operating cash flow (low accruals = honest earnings). Mature
  cash-generative businesses cluster here.
- **`accruals_inv_asset_growth_v1`** — favors firms that grew assets
  least over the trailing year. Conservative-investment leg of FF5 CMA;
  mature firms in non-expanding industries dominate.

## Honest caveats — DO NOT extrapolate from this smoke run

1. **2024 was a single year, in a strong bull regime.** The 1.91 Sharpe
   includes regime tailwind. The active engine's 2025-OOS Sharpe with
   only 3 active edges is in the 0.4-1.0 range. A multi-year measurement
   campaign (separate dispatch) is required before drawing any conclusion
   about whether these 6 edges add multi-year alpha.

2. **The universe-too-small failure mode IS still applicable.**
   `project_factor_edge_first_alpha_2026_04_24.md` documents
   `momentum_factor_v1`'s in-sample +0.13 Sharpe collapsing to -0.62 OOS
   on a 39-ticker universe (top quintile = 8 names). At 80 with-data /
   16 per quintile, we are above the 39-ticker disaster threshold but
   below the ≥200 universe size that the academic factor literature
   conventionally requires. Regime-conditional alpha or concentration
   risk are both live possibilities. Walk-forward verification on
   2021/2022/2023/2024/2025 splits MUST happen before treating these as
   validated.

3. **Restatement bias on accruals.** SimFin's `publish_date` filter
   gives PIT correctness on the join key, but the underlying figures
   are "latest restated" per SimFin docs. This injects a small but
   real PIT bias on the two accruals edges
   (`accruals_inv_sloan_v1`, `accruals_inv_asset_growth_v1`). Documented
   in `docs/Core/Ideas_Pipeline/ws_f_fundamentals_data_scoping.md`.

4. **Long-only this round.** The Cooper-Gulen-Schill asset-growth result
   is partly driven by the SHORT leg (high-growth firms underperform);
   we deploy only the long leg here to avoid borrow-cost modeling.
   The Sloan accruals SHORT side is also stronger historically. Both
   are follow-on items pending borrow-model.

5. **Smoke-run signals can mask leakage that's invisible in 1-year
   data.** Multi-year deterministic verification (the canonical
   Foundation Gate measurement) is the post-merge step; this dispatch
   intentionally stops at smoke.

## Tests added

`tests/test_fundamentals_edges.py` — 35 tests, all pass.

Coverage:
- Each of 6 edges registers cleanly + `compute_signals` returns a dict
- PIT correctness verified at the helper level
  (`fh.ttm_sum`/`fh.latest_value` differ by as_of date for AAPL across
  2021/2024 publishes; no future-data leakage)
- Universe handling: unknown tickers don't crash, get 0 score
- Below-min-universe abstention behavior
- Missing-panel abstention (SIMFIN_API_KEY unavailable case)
- Hand-computed AAPL earnings-yield matches the live edge
- Cross-edge orthogonality smoke: no two edges return identical selection sets
- Custom params (`long_score`, `top_quantile`) honored

## edges.yml deltas

Six new entries with `status: active`, `category: fundamental`,
`tier: feature` (default), `combination_role: input` (default). No
existing edges modified.

## Next-step recommendations

In priority order — for the validation analyst (Engine F doctrine: this
team produces candidates, F promotes):

1. **Multi-year deterministic measurement** across 2021-2025 with 3 reps/year
   on the new 9-edge ensemble. This is the standard `run_multi_year` campaign.
   Compares against the prior 3-edge baseline.
2. **Per-edge OOS walk-forward** for each of the 6 new edges in isolation
   (the prior `low_vol_factor_v1` / `momentum_factor_v1` shape) to detect
   the regime-conditional vs always-on case before relying on them in
   ensemble.
3. **Coverage extension** — wire BAC/JPM/GS etc. via a financial-friendly
   fundamentals adapter. SimFin FREE excluding 70 financials is a known
   gap; until it closes, the 109-ticker universe really is an 84-name
   universe for these edges.

If any of the 6 edges fails OOS walk-forward, mark it `failed` with
`failure_reason='regime_conditional'` or `'universe_too_small'` per the
graveyard convention. Do not iterate parameters to make the test pass —
that's overfitting.
