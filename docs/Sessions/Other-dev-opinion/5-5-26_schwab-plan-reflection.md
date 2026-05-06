# Review of Schwab Integration Scoping Brief

The brief is solid overall — correct architectural fit (Foundry DataSource), correct identification that today's regime falsification points at IV skew + put-call as the next inputs, correct discipline on what's out of scope (no streaming, no execution migration). Three substantive issues to address before scoping further, plus reorderings and clarifications.

## Issue 1 (most important): Historical options data is the gotcha

The brief assumes Schwab provides 5+ years of historical IV skew on 109 tickers. **This is the single thing the dev should verify before writing any adapter code.** Most retail broker market-data APIs (Schwab inherited TD Ameritrade's, which is no exception) expose **current options chains** but not historical ones. Real-time and recent EOD chains, yes. Five years back, usually no.

If that holds:

- **Tier-1 historical IV skew is unobtainable from Schwab.** The dev would need either (a) accept forward-collection and defer IV-skew validation 6-12 months, (b) source historical chains elsewhere (OptionsDX, IVolatility, HistoricalOptionData, CBOE DataShop — these are paid, $200-2000), or (c) use a partial proxy (computed IV from end-of-day prices, less accurate).
- **The 1-2 day validation timeline collapses.** Without historical chains, IV skew is a forward-only signal that needs accumulation before HMM training has enough samples.

**Action for the dev:** before writing anything, spend 30 minutes verifying via Schwab API docs whether `/marketdata/v1/chains` (or equivalent) accepts a date parameter for historical chains. If no historical, the integration plan reorders below.

## Issue 2: The dev's adapter shape is too feature-coupled

The proposed adapter has `fetch_iv_skew`, `fetch_put_call_ratio`, `fetch_vix_term_structure` etc. **This bakes derived computations into the data layer**, which violates the Foundry's separation between sources (raw data) and features (derived values).

**Suggested cleaner shape:**

```python
class SchwabMarketData(DataSource):
    def fetch_quote(self, ticker: str, dt: date) -> dict:
        """Raw quote: bid, ask, last, volume."""
        ...
    def fetch_options_chain(self, ticker: str, dt: date) -> dict:
        """Full chain: all strikes, all expiries, with Greeks/IV."""
        ...
    def fetch_movers(self, scan_type: str, dt: date) -> list:
        """Top movers / volume leaders / 52w breakouts."""
        ...

# Features compute derived values from the raw data:
@feature(source='schwab')
def iv_skew_25d_put_call(ticker, date) -> float:
    chain = SchwabMarketData().fetch_options_chain(ticker, date)
    return _compute_25d_skew(chain)
```

**Why this matters:** the Foundry's discipline (adversarial twins, auto-ablation, lineage) operates on features, not on adapter methods. If the dev couples derivations into the adapter, every new derived feature (term-structure slope at different tenors, skew at different deltas, butterfly spreads, etc.) requires a new adapter method. Growing-by-method scales badly. **Adapters should be raw-data thin; features should be derivation thin and isolated.**

The existing adapters in `core/feature_foundry/sources/` (CFTC, FRED, earnings calendar) follow this pattern correctly. The Schwab adapter should match.

## Issue 3: Reorder the priorities — start with what's cheapest to validate

The brief's Tier-1 is correct in *what* but the order is suboptimal given Issue 1 (historical-data gap). I'd push the dev to validate cheap-and-fast first:

### Revised priority order

**Phase 1A — VIX term structure (highest ROI, no historical-data risk)**
- Pull ^VIX, ^VIX9D, ^VIX3M, ^VIX6M as quotes (Schwab has these as direct index quotes, not synthesized from option chains — verify but should work)
- Compute slope features: `vix_term_slope_9_3m`, `vix_term_slope_3_6m`
- Run through `scripts/validate_regime_signals.py` for AUC + coincident-vs-leading test
- **Total: 3-4 hours. Yes/no within a day on whether term structure is leading.**

**Phase 1B — Put-call ratio (don't go to Schwab for historical)**
- CBOE publishes total daily P/C ratio for free historically (going back decades) at `cdn.cboe.com/api/global/us_indices/...`
- **Don't burn Schwab time on P/C historical**. Pull CBOE free historical, validate. If P/C is leading, Schwab can later provide ticker-specific P/C as an enhancement.
- **Total: 2-3 hours. Yes/no on P/C leading-ness within a day.**

**Phase 1C — IV skew (deferred or partial)**
- Conditional on Phase 1A/1B results AND historical-data availability
- If Schwab has historical chains: build the chain-pull + skew computation, ~4-8 hours
- If not: collect forward, validation deferred 6-12 months, optionally source historical from a paid provider if regime work justifies the spend

**This reordering gets you "is the regime panel rebuild going to work?" within 1-2 days for the cheapest signals, without committing to the historical-options unknown.**

## Issue 4: Missing things the brief should consider

### A. Movers / scanner endpoints — bigger value than the brief suggests
Schwab exposes:
- Top gainers / losers
- Most-active by volume
- Breakout scanners (52-week highs)
- Sector rotation views

**These are directly useful for the Moonshot Sleeve universe selection** (Workstream H in the forward plan) — a separate workstream from regime work but worth integrating once the adapter exists. Should be added to Tier 2.

### B. Free index quotes for cross-asset confirmation
Schwab quotes most major indices (^DJI, ^IXIC, ^RUT, ^TNX, ^TYX, ^FVX, etc.) as well as ETF underlyings. The cross-asset confirmation work in WS-C (HYG/LQD spread, DXY changes) could pull these from Schwab instead of FRED. Marginal value-add, but worth noting.

### C. Data-license footnote (for monetization context)
**Schwab data is personal-use licensed.** The brief should add: "If/when this project pursues newsletter / SMA / RIA monetization, options data must transition to a commercially-licensed provider (Tradier, Massive/Polygon, IVolatility). Engineering implication: keep the Foundry DataSource interface generic enough to swap providers without refactoring features." Without this footnote, future-you may quietly violate ToS during scaling.

### D. Caching strategy specifics
The brief says "parquet under `data/<source>/`" but for options data this is more nuanced. Recommend:
- Quotes: per-ticker parquet, partitioned by year (small files)
- Options chains: per-ticker per-month parquet (chains are large)
- Compressed Snappy, schema-versioned in `_meta.json`
- Sidecar manifest with `last_pulled_at`, `coverage_window`, `record_count`

This matters because options chains can hit hundreds of MB per ticker per year, and naive single-parquet-per-ticker layout becomes painful to query.

### E. Adversarial twin coupling
The brief says features get "automatically picked up by adversarial-twin generation + ablation tests + the leakage detector." Verify this in implementation. Schwab features should run through the same `@feature` decorator path as everything else, with no special handling. **If the dev cuts corners on this for "infrastructure" features, the discipline lapses propagate.**

## What I disagree with in the brief

### "We currently pull VIX from yfinance/FRED but the term structure is harder. Schwab probably exposes this cleaner."
**Verify before assuming.** yfinance gives ^VIX, ^VIX9D, ^VIX3M, ^VIX6M directly. FRED gives ^VIX. **Term structure is computable from these existing free sources today.** Schwab probably doesn't add value here — it's already free elsewhere. Worth validating before building Schwab as the term-structure source. **The HMM panel rebuild for VIX term structure could probably ship without Schwab at all.**

If that's right, **Phase 1A doesn't even need Schwab integration**. You can validate VIX term structure as a leading indicator using existing yfinance data this afternoon, before any Schwab work begins. **That's a sub-1-hour test that could collapse the regime-rebuild blocker without a single line of Schwab code.**

### "1-2 day investment to the point where we know whether IV skew is actually predictive"
Optimistic. With the historical-data gap unverified, IV skew validation could be deferred 6-12 months. The dev should be honest about this. **Realistic estimate: 1-2 days for VIX term + P/C; IV skew is a known unknown.**

### Engineering effort total
The dev's effort estimate is roughly right for what they scoped, but doesn't reflect the historical-data risk. **Add a 1-2 hour pre-implementation verification step for "does Schwab API accept a historical date for options chains?"** That single answer determines whether the IV skew portion is 8 hours or 3+ months of forward collection.

## What I'd tell the dev to do

```
1. STOP. Before writing adapter code:
   a. Verify Schwab API supports historical options chains (date parameter).
      ~30 min in their API docs.
   b. Check whether VIX term structure (^VIX9D / ^VIX / ^VIX3M / ^VIX6M)
      is already accessible via yfinance/FRED at sufficient quality.
      ~30 min spot check.

2. Run the cheapest validation BEFORE Schwab integration:
   - Pull VIX9D/VIX/VIX3M/VIX6M from yfinance for 2021-2025
   - Compute term-structure slope features
   - Run validate_regime_signals.py
   - Total: 1-2 hours
   - Outcome: empirical answer on whether term structure is leading,
     achieved without writing any Schwab code

3. If validation passes for VIX term: HMM panel rebuild can proceed
   without Schwab. Ship the VIX term features through Foundry directly.

4. If validation fails for VIX term:
   - Pull CBOE historical P/C ratio (free), repeat validation
   - If P/C leading: HMM panel rebuild with P/C, Schwab still optional
   - If P/C not leading: now Schwab IV skew becomes the priority,
     and historical-data availability determines whether it's a
     1-day project or 6-month forward-collection

5. Schwab integration becomes worthwhile when:
   - VIX term + P/C alone don't fix the regime panel, AND
   - Schwab provides historical options chains (else need paid provider)

   At that point: build the adapter (raw data, generic methods),
   features (decorated, derivations isolated), full Foundry discipline.
```

## Recommended changes to the brief before scoping

1. Add the historical-options-data verification as a pre-step
2. Reorder Tier 1: VIX term structure → P/C ratio → IV skew (cheapest-first)
3. Note that VIX term structure may be obtainable from yfinance/FRED without Schwab
4. Note that P/C ratio is freely available historically from CBOE
5. Restructure the adapter design to separate raw-data methods from feature derivations
6. Add data-license footnote for monetization context
7. Specify partitioned parquet caching strategy
8. Add the "movers / scanner" endpoints to Tier 2
9. Update effort estimate to reflect historical-data unknown

## Single-paragraph TL;DR for your dev

The brief is well-scoped on architecture but should verify two things first: (1) does Schwab API expose historical options chains (probably not — most retail broker APIs don't), (2) is VIX term structure already computable from existing yfinance/FRED data (probably yes). If (1) is no and (2) is yes, much of the regime-rebuild work can ship before any Schwab code is written. The dev should run the cheap VIX term + CBOE P/C validations first (free, no Schwab), then decide whether Schwab integration is the bottleneck for IV skew specifically. The adapter shape should be raw-data-only with derived features computed in `@feature` modules, not coupled into the adapter. Add the personal-use license footnote for monetization context. **Bottom line: the work is real, the timing is real, the priorities should reorder.**

That's the review. The dev's instincts are right; the execution sequence and a few architectural details benefit from the changes above.