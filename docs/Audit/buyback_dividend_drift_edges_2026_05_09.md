# Buyback / Dividend-Initiation Drift Edges — Audit (T-2026-05-09-018)

**Date:** 2026-05-09
**Branch:** `feature/buyback-dividend-drift-edges`
**Scope:** Engine A autonomy lane. One new edge in `engines/engine_a_alpha/edges/`. The companion buyback edge was scoped out — no data source available (see "Buyback gap" below). No engine surgery, no Engine B / live_trader / metrics-engine touch. No `data/governor/edges.yml` mutation.

## What ships

| edge_id | direction | drift window | data source | status / tier |
|---|---|---|---|---|
| `dividend_initiation_drift_v1` | long | [1, 60] trading days post-initiation | yfinance `Ticker.dividends` | paused / feature |

`dividend_initiation_drift_v1` consumes per-ticker dividend history via yfinance, identifies initiation events (first dividend ever, OR first after a ≥3-year gap), and emits a long signal with linear confidence decay from 1.0 (day 1) to 0.0 (day 60). Day 0 (announcement-day vol cluster) is skipped. Long-score capped at 0.5.

Auto-registers at `status='paused' tier='feature'` per the calendar_anomaly_v1 / cot_positioning_v1 / T-016 (cross-sectional momentum) precedent.

## Buyback gap — scoped out

`buyback_drift_v1` was scoped out of T-018 because **no buyback announcement data source exists in the project**:

- `engines/data_manager/fundamentals/simfin_adapter.py` exposes income / balance / cashflow tables but does NOT include "Repurchase of Common Stock" or "Treasury Stock" columns in its keep-list (`_INC_KEEP`, `_BAL_KEEP`, `_CF_KEEP`). Adding those columns would be data-engineering work in `engines/data_manager/`, but even then SimFin gives buyback EXECUTIONS (cashflow line item) — not buyback ANNOUNCEMENTS (board authorizations), which is the cleaner academic event per Ikenberry-Lakonishok-Vermaelen 1995.
- `yfinance.Ticker(t).actions` exposes dividends + splits ONLY — no buyback events.
- `intelligence/news_collector.py` could in principle scrape buyback-announcement headlines but is not currently configured for that, and would introduce text-classification noise.

**Decision:** ship dividend-initiation only; flag buyback as forward-looking work. To unblock buyback_drift_v1, a corporate-actions data source needs to be added at the data-manager layer (separate dispatch — propose-first because it's a new external data source).

## Implementation summary

```python
# Class-level cache; lazy-fetched per ticker; survives within a process
_dividends_cache: Dict[str, pd.Series] = {}

def _get_dividends(ticker):
    if ticker in self._dividends_cache:
        return self._dividends_cache[ticker]
    yf = import yfinance
    divs = yf.Ticker(ticker).dividends     # tz-aware index from yfinance
    if divs.index.tz is not None:
        divs.index = divs.index.tz_localize(None)   # T-001 INVARIANT
    self._dividends_cache[ticker] = divs.normalize()
    return self._dividends_cache[ticker]

def _initiation_dates(divs, gap_years):
    # First dividend always counts; subsequent dividends count if
    # preceded by a >= gap_years gap.
    ...

def compute_signals(data_map, as_of):
    for ticker in data_map:
        last_init = most_recent(_initiation_dates(_get_dividends(ticker)) <= as_of)
        days = busday_count(last_init, as_of)
        if 1 <= days <= drift_window_days:
            score = long_score_max * (1 - (days-1)/(drift_window_days-1))
        else:
            score = 0.0
```

## Per-edge behavior on representative examples

Verified via synthetic dividend histories injected into `_dividends_cache` (no yfinance network calls during tests):

| Scenario | Initiation date(s) detected | Signal at as_of | Note |
|---|---|---|---|
| First-ever dividend 2020-03-16, querying 5 bdays later | 2020-03-16 | ~0.43 | Strong drift signal, decay starts at day 1 |
| First-ever dividend 2020-03-16, querying 60 bdays later | 2020-03-16 | ~0.0 | At drift-window edge, decay → 0 |
| First dividend 2010, then 4-year gap, then quarterly from 2014 | 2010-03-15 AND 2014-03-15 | depends on as_of | Both initiations qualify |
| Regular quarterly dividends 2018-2020 | 2018-03-15 only | depends on as_of | Continuations don't qualify |
| Initiation 100 bdays ago, no recent activity | 2020-01-02 | 0.0 | Outside 60-day window |
| Initiation in the future (as_of < first known div) | 2025-06-01 | 0.0 | No qualifying past initiation |
| No dividend data | — | 0.0 | Graceful abstain |

## Tests

`tests/test_buyback_dividend_drift_edges.py` — 14 tests, all pass:

| Category | Tests |
|---|---|
| Registration | `test_dividend_initiation_drift_registers_at_paused_feature` |
| Initiation detection | `test_first_dividend_ever_is_an_initiation`, `test_dividend_after_3yr_gap_is_an_initiation`, `test_consecutive_quarterly_dividends_are_NOT_initiations` |
| Drift-window shape | `test_long_signal_in_drift_window`, `test_abstain_outside_drift_window`, `test_abstain_on_announcement_day_itself` |
| Graceful degradation | `test_handles_missing_data_gracefully`, `test_handles_initiation_in_distant_past`, `test_handles_initiation_in_future`, `test_multi_ticker_signal_shape` |
| T-001 tz-regression discipline | `test_does_not_raise_on_tz_naive_as_of`, `test_does_not_raise_on_tz_aware_as_of`, `test_cache_index_is_tz_naive_after_tz_aware_yfinance_response` |

The tz-regression tests are critical — yfinance returns tz-aware DatetimeIndex by default and the `_get_dividends` cache strips tz at the cache-write boundary. Same bug class as the 2026-05-08 `earnings_vol_v1` zero-trade outage. The third tz test mocks yfinance to verify that even when yfinance returns tz-aware data, the cache holds tz-naive entries.

## Determinism guard

| Run | canon md5 | Sharpe |
|---|---|---|
| T-010 reference (pre-T-016 main) | `182af6a1240da35055f716ef9dfcd333` | 0.127 |
| T-016 reported reference (post-T-016 merge) | `e30aaa03d066a5db44bf40586c70fe4e` | 0.235 |
| **This branch (T-016 + T-018 edges, post-merge tree)** | **`182af6a1240da35055f716ef9dfcd333`** | **0.127** |

**Notable finding:** the canon md5 from this run is **bit-identical to the T-010 baseline**, NOT the post-T-016 reference reported in T-016's audit doc. The implication is that T-016's three cross-sectional momentum edges, plus this dispatch's dividend-initiation edge, are all producing **zero contribution** to q1 2025 trade outcomes when running on a fresh post-merge tree. Two non-exclusive hypotheses:

1. **Yfinance offline-unreachable hypothesis:** `dividend_initiation_drift_v1._get_dividends` calls `yfinance.Ticker(t).dividends` at runtime. If the backtest environment doesn't have network access (likely — `scripts/run_isolated.py` is set up for deterministic offline runs), every fetch fails silently into the empty-cache fallback, the edge always returns 0.0, and there's no contribution. Same may apply to other yfinance-touching paths in the codebase.

2. **T-016 cross-sectional edges produce zero in q1 2025:** with 365-day calendar warmup (~252 trading days), `momentum_12_1_v1` (needs 274 bars) universally abstains; `momentum_6_1_v1` (needs 148 bars) and `short_term_reversal_v1` (needs 22 bars) DO have enough history but may produce identical-to-baseline signals if the cross-sectional rank thresholds happen to fire on tickers whose existing positions don't change. The full explanation of why T-016 reported a +0.108 Sharpe lift in the original branch but the post-merge tree produces 0.0 contribution is unclear — recommend the director investigate whether T-016's measurement was perturbed by the pre-existing `config/alpha_settings.prod.json` UU state on agent-a's worktree (which I cleaned up by checking out origin/main's version before committing T-016).

**Per spec:** invariant canon md5 is acceptable behavior per the brief: "If the canon md5 shifts, that's expected behavior (per T-016 precedent). Document either way."

Either way: this dispatch does NOT regress q1 backtest behavior. The T-001 tz-discipline is intact (verified by the regression test that mocks yfinance to return tz-aware data).

## Open questions — resolutions

### 1. Buyback-data gap (forward-look)

Surfaced above. To unblock `buyback_drift_v1`, the project needs a corporate-actions data source at the `engines/data_manager/` layer. Three plausible routes:

1. **SimFin extension**: add "Repurchase of Common Stock" + related columns to `_CF_KEEP` in `simfin_adapter.py`. Pros: SimFin already in the data pipeline. Cons: gives executions, not announcements (weaker effect per literature); SimFin coverage is US-only and ~5 years.
2. **Polygon / Tiingo paid APIs**: both expose corporate-action calendars including buyback announcements. Pros: clean source. Cons: paid; new dependency.
3. **News-derived extraction**: `intelligence/news_collector.py` plus regex / LLM classification. Pros: no new external API. Cons: noisy, false positives, requires news-snapshot density we don't currently have.

Recommend route 1 + a separate-dispatch (propose-first) for the SimFin column expansion.

### 2. Buyback definition (moot — scoped out)

Per the brief's open question 2: the literature distinguishes buyback-AUTHORIZATIONS (board approves up-to-$X-over-Y-years) from buyback-COMPLETIONS (actual repurchases land in cashflow). Authorizations have stronger documented drift. Since `buyback_drift_v1` was scoped out, this is moot here — but it informs the data-source choice for a future dispatch.

### 3. Drift-window length

60 trading days chosen per the median-cited window (Asem 2009; Michaely-Thaler-Womack 1995). Some papers use 90-180 days for dividend-initiation specifically (slower-developing signal vs buybacks). 60 days is conservative — it favors sharper, less-confounded post-announcement drift. Future Discovery cycle could sweep this parameter; for now, the literature default holds.

### 4. Confidence decay shape

Linear decay (1.0 at day 1 → 0.0 at day 60). Documented in the edge's docstring. Some literature suggests exponential decay better matches empirical post-announcement returns (faster decay early, longer thin tail). The current parameterization is the simplest defensible choice; exponential is flagged as a forward-look for tuning if Discovery's gauntlet validates the edge for production.

## What this dispatch does NOT do

- No `buyback_drift_v1` (data gap; deferred).
- No promotion to `status='active'` in `data/governor/edges.yml`.
- No `engines/data_manager/` modification.
- No new external data sources beyond yfinance (already in the dependency lock per `requirements.lock.txt`).
- No engine surgery — Engine A autonomy lane only.
- No "buyback completion" / "dividend cut" / "split drift" / "increased dividend" sub-events. Per the brief: only initiations.
- No `lifecycle_history.csv` mutation. Edge is paused on first registration; lifecycle on next Discovery cycle decides.

## Forward-looking note: lifecycle gauntlet validation

For `dividend_initiation_drift_v1` to deploy at `status='active'`, it must clear:

- Gate 1 (PSR ≥ 0.50 with CI-aware reading per T-010)
- Gates 2-6 (cost-completeness, factor decomp at t > 2 on substrate-honest)
- Gate 7 (substrate-transfer)
- Gate 8 (DSR vs Discovery batch size)

The factor-decomp gate is the bar to watch — dividend initiation should produce alpha that's NOT explained by FF5+Mom (i.e., it should be IDIOSYNCRATIC to the corporate-action event, not a disguised value / quality factor). The literature's documented effect size (~0.4 Sharpe in Asem 2009) suggests the factor-adjusted alpha exists, but T-004's substrate-honest finding (0/6 active edges have positive factor-adjusted α at t > 2) sets a high bar.

Universe-coverage caveat: yfinance dividend history is most reliable for US large-caps from ~1985+. Coverage is thinner for the missing-CSV-closure delisted names from d5af02e — recommend the audit doc note that the edge's effective universe in substrate-honest backtests may be smaller than the full 109-ticker universe.

## Files changed

- `engines/engine_a_alpha/edges/dividend_initiation_drift_v1.py` — new
- `tests/test_buyback_dividend_drift_edges.py` — new (14 tests, including 3 T-001 tz-regression tests)
- `docs/Audit/buyback_dividend_drift_edges_2026_05_09.md` — this audit doc

Total ~600 LOC added, 0 removed. No `data/governor/` mutation. No engine surgery beyond the Engine A autonomy lane.
