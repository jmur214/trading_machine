# Schwab Developer API Integration — Scoping Brief

**Date:** 2026-05-06
**Status:** Draft for external dev review. Not yet scheduled for implementation.
**Audience:** A developer external to this project who has been asked to review whether Schwab API integration is worth pursuing here, and whether they have additional context to add before scoping.

---

## TL;DR for the reviewer

The user has a Schwab individual developer market-data API account that's currently unused by this project. Today's regime-detection validation work directly identified **IV skew + put-call ratios** as the next leading-indicator data we'd need to fix a structurally-broken regime classifier. Schwab provides those directly. This brief scopes what the integration would look like, what specifically we'd want to ingest, and where dev input is most valuable.

The brief is intentionally light on implementation specifics — the goal is alignment on **what data to pull and how to shape it**, not the actual code dispatch.

---

## Project context (in 60 seconds)

This is an autonomous algorithmic trading system organized around a 6-engine architecture (Alpha, Risk, Portfolio, Discovery, Regime, Governance). The recent measurement state:

- Foundation Gate baseline: 2021-2025 mean Sharpe ~1.30 deterministic, all 5 years positive
- Single-name OHLCV from yfinance (free, sometimes flaky), macro from FRED, fundamentals from SimFin FREE (5,000 US equities, mid-2020 to present, no banks)
- Live trading via Alpaca brokerage API (paper-trading state currently)

**Where Schwab fits:** the data layer above is missing options-derived signals. Today's regime-validation analysis (full audit at `docs/Measurements/2026-05/regime_signal_validation_2026_05_06.md`) showed our current regime classifier is **coincident not leading** because its input features (rolling SPY return, rolling SPY vol) describe the past by construction. Reviewer-specific: the validation found 2-of-3 cross-asset confirmation gate had **0% true-positive rate on -5% drawdowns over 1086 days** — a hard falsification.

The fix path requires leading inputs. Two specific feature families were named as the highest-priority candidates:

1. VIX term structure (we tried this — partial result, features themselves are coincident)
2. **IV skew + put-call ratios** ← Schwab provides these directly

---

## What we'd want from Schwab

Priority-ordered. The reviewer should weigh in on (a) feasibility, (b) better alternatives we may not have considered, (c) rate limit / cost concerns.

### Tier 1 — directly load-bearing on regime work

- **IV skew (25Δ put / 25Δ call ratio)** for SPY and major sector ETFs (XLF, XLK, XLE, etc.)
  - Daily snapshot is sufficient (intraday not needed initially)
  - Historical depth: 5+ years to match our Foundation Gate window (2021-2025)
- **Put-call ratio** (CBOE total or SPY-specific)
  - Daily snapshot
  - Historical, same depth
- **Implied volatility on individual options** for a defined chain
  - Front-month + 3-month near-the-money calls/puts
  - Used to compute term structure + skew per ticker

### Tier 2 — broader market-microstructure context

- **VIX9D, VIX, VIX3M, VIX6M term structure** — we currently pull VIX from yfinance/FRED but the term structure is harder. Schwab probably exposes this cleaner.
- **Bid/ask spreads** at end-of-day for the prod 109-ticker universe — feeds our `RealisticSlippageModel` cost model
- **Volume profile** — daily volume/turnover for ADV-bucketed slippage (currently estimated)

### Tier 3 — nice-to-have

- **Earnings surprise** (we use yfinance for this currently — Schwab may be more reliable)
- **Analyst revision dispersion** (forward-EPS std-dev across analysts — third-priority leading indicator candidate from regime validation)

### What we explicitly DO NOT need from Schwab

- Fundamentals — we have SimFin (~5K US tickers, quarterly statements). Schwab is broker-data not statements-data.
- Real-time streaming — we're a daily-bar backtest system; intraday is out of scope until live deployment
- Account positions / order entry — we use Alpaca for that path

---

## Integration shape (best guess; reviewer feedback welcome)

We have a "Foundry" data-source pattern at `core/feature_foundry/sources/` that already supports adding new data adapters. Existing adapters: `local_ohlcv.py` (CSV cache), `fred_macro.py` (FRED time series), `cftc_cot.py` (CFTC commitments), `earnings_calendar.py` (yfinance earnings). Adding Schwab would be a fifth adapter.

Each adapter's interface:

```python
class SchwabMarketData(DataSource):
    def fetch_iv_skew(self, ticker: str, dt: date) -> Optional[float]: ...
    def fetch_put_call_ratio(self, ticker: str, dt: date) -> Optional[float]: ...
    def fetch_vix_term_structure(self, dt: date) -> Optional[dict]: ...
    # etc.
```

Pulled values get cached to parquet under `data/<source>/` (gitignored), exposed to the Foundry's `@feature` decorator system, automatically picked up by adversarial-twin generation + ablation tests + the leakage detector.

Authentication: Schwab uses OAuth 2.0 with refresh tokens. We have a project pattern for credential storage at `.env` + `config/<provider>_keys.json` (gitignored). Token-refresh logic would live in the adapter.

**Open questions for the reviewer:**

1. Is Schwab's individual developer rate limit reasonable for nightly bulk pulls of 5+ years of options data on the 109-ticker universe? Or do we need to be more selective (SPY + sector ETFs only initially)?
2. Are there better paths than going through the options chain endpoint to get IV skew? Some platforms expose pre-computed skew metrics directly.
3. Does Schwab expose VIX term structure directly, or do we synthesize it from VIX option chains? (If yes to the latter, this may be more work than expected.)
4. Anything we're missing — e.g., does Schwab expose flow data (block trades, dark pool prints) we should consider?

---

## Why this is a particularly timely piece of work

Three converging facts:

1. **Today's regime validation falsified the existing HMM** — AUC 0.49 on 20d-fwd drawdowns is coin-flip. The architectural diagnosis pointed specifically at the input panel needing leading features.
2. **The user already has the Schwab account** — no procurement decision needed.
3. **The Foundry substrate is already set up** to absorb a new data source cleanly — we shipped that infrastructure last week.

Without Schwab (or an equivalent options-data source), the regime-rebuild work is blocked at "we can't acquire the leading features the validation said we need." The current alternative — slice 2 feature-selection from the existing panel — has a chance of finding hidden signal but is a smaller-leverage move.

With Schwab integrated, the regime work becomes empirically testable: pull IV skew + put-call → run them through `scripts/validate_regime_signals.py` (the AUC + coincident-vs-leading correlation test) → know within 2 hours whether they actually carry leading signal.

---

## Estimated effort (rough)

- **Adapter scaffolding + auth + token refresh:** 4-6 hr
- **Initial historical pull (5 years × 109 tickers × IV/PC/skew):** 1-2 hr if rate limits are friendly; longer if we have to throttle
- **Validation against `validate_regime_signals.py`:** 1-2 hr
- **HMM panel re-train with the new features:** 2-3 hr (slice 3 of the regime-rebuild work)

Total: probably a 1-2 day investment to the point where we know whether IV skew is actually predictive.

---

## What I'd want the reviewer to add or correct

- Anything about Schwab's API I have wrong (rate limits, data shape, gotchas)
- Better integration patterns they've seen in similar projects
- Whether IV skew is the right first slice or whether put-call should come first (or both together)
- Any data source they'd recommend instead of or alongside Schwab
- General sanity check: does this scoping match how they'd approach the same problem?

---

## What stays gated on this work

- Engine B propose-first integration of regime signals into risk-sizing
- Path C compounder sleeve resumption (currently deferred — see `docs/State/forward_plan.md` and memory `project_path_c_deferred_2026_05_06.md`)
- Any further regime-conditional features that depend on a leading regime classifier

The user is asking the reviewer to weigh in before we commit to the integration. Their input shapes the dispatch.
