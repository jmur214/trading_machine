# Spec — T-2026-05-08-007: Diversified-Futures Trend Test

**Date drafted:** 2026-05-08
**Status:** SPEC for approval. Two-phase task — data acquisition then measurement.
**Will be executed by:** Agent A or B once the dispatch-able window opens (~6-10 hr including data acq).
**Output:** New universe data on disk + audit doc at `docs/Measurements/2026-05/diversified_futures_trend_verdict_2026_05_08.md`.

---

## Why now

R2's primary Moonshot-replacement recommendation: **trend-following on a diversified-futures basket**. Equity-trend was tested and falsified twice (115-ticker mega-cap and 722-ticker wider universe — both produced symmetric tails / negative skew). But equity-trend ≠ futures-trend. The academic literature (AQR / Hurst-Ooi / Moskowitz 2017 *"A Century of Evidence on Trend-Following Investing"*) reports robust positive Sharpe ~0.7-1.0 on diversified-futures trend over 100+ year samples, with low equity correlation AND positive skew (the upside-capture property the moonshot gauntlet rewards).

The trend-sleeve scaffolding (`engines/engine_c_portfolio/sleeves/trend_following_sleeve.py`) is already shipped. What's missing: the universe data + a test on it.

If diversified-futures trend produces the property equity-trend doesn't (positive skew + low equity correlation), it's deployable as a true Moonshot-style sleeve. If it doesn't, R2's recommendation is empirically refuted on this substrate too — that's a real finding either way.

---

## Universe (8-ETF basket)

R2's specific basket. Each ETF is a long-on-the-asset-class futures proxy:

| Ticker | Asset class | Currently on disk? |
|---|---|---|
| SPY | US large-cap equity | YES |
| TLT | 20+ year US Treasuries | YES |
| GLD | Gold | YES |
| USO | WTI crude oil futures | **MISSING** |
| UUP | US dollar index | **MISSING** |
| EEM | Emerging-market equity | **MISSING** |
| IEF | 7-10 year US Treasuries | **MISSING** |
| DBC | Diversified commodities | **MISSING** |

The 5 missing tickers must be acquired before measurement.

---

## Phase 1 — Data acquisition (~1-2 hr)

Use the recently-shipped Alpaca pipeline (`scripts/fetch_missing_delisted.py` from commit `d5af02e`) — the same one the other dev built for the missing-CSV closure. These ETFs are currently-listed (easier than delisted names), so primary-source fallback chain (Alpaca v2 → yfinance → Stooq) should work cleanly.

For each missing ticker, fetch 2020-04-09 through 2026-04-17 (matching the existing 1514-row cadence on disk for SPY/TLT/GLD). Validate:
- No zero closes
- No spurious gap days (>5 calendar-day gap = investigate)
- ATR + PrevClose columns populated
- File saved as `data/processed/<TICKER>_1d.csv`

Rejection criteria (any one fails → write `BLOCKED — data quality on <TICKER>` to outbox):
- Fewer than 1500 rows
- More than 5 zero-close days
- More than 10 NaN rows in close

---

## Phase 2 — Trend test on 8-ETF basket (~3-5 hr)

Use the existing `TrendFollowingSleeve` scaffolding. New harness script: `scripts/run_diversified_futures_trend.py` that:

1. Loads OHLCV for all 8 ETFs from `data/processed/`
2. Instantiates `TrendFollowingSleeve` with config:
   - `lookback_days=252` (12-month momentum, classical CTA)
   - `vol_window_days=63`
   - `top_n=4` (half the universe — trend is selecting the strongest 4 of 8 each rebalance)
   - `max_position_weight=0.30` (concentration cap; 4 names × 0.25 baseline gives room)
   - `rebalance_cadence="monthly"`
3. Runs the same `sleeve_phase0_verdict.run_trend_verdict` measurement-only harness already shipped (`scripts/sleeve_phase0_verdict.py`). Phantom allocation; no Engine B wire.
4. Reports per the existing sleeve gauntlet (Sortino + skewness + tail_ratio + upside_capture) PLUS:
   - **Correlation to SPY**: time-series correlation of trend-sleeve daily returns to SPY daily returns. The diversification thesis says this should be near zero.
   - **Per-asset-class contribution**: bonds, commodities, currencies, equities — break out which classes drove the result.

---

## Acceptance

1. **Phase 1 data:** all 5 missing CSVs present in `data/processed/` with quality validation passed; provenance metadata in `data/processed/_data_provenance_<ticker>.json`
2. **Phase 2 audit doc:** `docs/Measurements/2026-05/diversified_futures_trend_verdict_2026_05_08.md` containing:
   - Per-ETF data quality summary (Phase 1)
   - Sleeve gauntlet metrics (Sortino, skewness, tail_ratio, upside_capture, MDD)
   - Bootstrap 95% CI on Sortino (1000 iterations, block-bootstrap)
   - Correlation to SPY
   - Per-asset-class contribution breakdown
   - Verdict bucket (per the SleeveCriteria already coded; trend-specific thresholds: Sortino ≥1.2, skewness ≥0.0, tail-ratio ≥1.2, upside-capture ≥0.7)
3. **Branch:** `feature/diversified-futures-trend`. Push only; director merges.

### Verdict framing

- **Passes gauntlet (3+ of 4 criteria) AND correlation to SPY < 0.3**: diversified-futures trend is a viable sleeve. Recommendation: wire it into PortfolioEngine.allocate as opt-in Tier-3 work.
- **Passes Sortino + Sharpe but skewness ≤ 0 OR tail-ratio < 1.0**: positive Sharpe vehicle but not asymmetric upside. Same outcome as equity trend — reframe needed.
- **Sortino < 0.5 OR MDD > 35%**: hypothesis falsified. R2's recommendation doesn't survive on this substrate. Document the result; don't deploy.

---

## Hard constraints

- DO NOT modify Engine B (Risk) or `live_trader/`
- DO NOT modify the existing TrendFollowingSleeve code; use it as-is via the harness
- DO NOT touch other ticker CSVs in `data/processed/` (read-only on existing universe)
- Phase 1 data acquisition: Alpaca primary, yfinance fallback. Stooq is last resort (data quality variable).
- Branch: `feature/diversified-futures-trend`; do NOT merge to main
- Time budget: 6-10 hr total (1-2 hr Phase 1 + 3-5 hr Phase 2 + 1-2 hr audit doc + tests)

---

## Sequencing

- Substrate-independent. Can run in parallel with A's substrate measurement.
- B is on T-005 first; this is a candidate for B's NEXT task after T-005 (or T-006).
- The data-acquisition phase is the slow part. If feasibility check shows Alpaca lacks history for any of these (rare but possible), surface BLOCKED before committing to Phase 2.

---

## Open questions for the agent (to surface in audit doc, not block)

1. **Margin / leverage modeling for futures-ETFs.** The ETFs proxy futures, but they're not the futures themselves — leverage / roll-cost dynamics differ. The phantom-allocation harness skips this entirely; document as a Phase-1-of-Phase-1 caveat. Real deployment needs futures-specific cost modeling.
2. **2020-2026 sample is short for trend-following.** AQR's claim is "century of evidence." A 6-year window can show or hide regimes the strategy doesn't generalize across. Document this tightly; one bad year on a 6-year sample is meaningful.
3. **Long-only vs long/short.** TrendFollowingSleeve as written is long-only. The classical CTA is long/short on each name based on momentum sign. Long-only loses half the alpha thesis. Phase 1 of this measurement uses long-only (existing scaffold); flag long/short as a Phase-2-of-Phase-2 follow-up if Phase 1 results justify it.
