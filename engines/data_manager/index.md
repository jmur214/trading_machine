# Data Manager Engine
**Purpose:** Single point of truth for fetching, caching, and serving financial data to the entire system.
**Architectural Role:** Abstracts Alpaca, YFinance, and FRED APIs. Caches aggressively to speed up backtests.

**Known Issues & Quirks:**
- *The Monolith Problem:* `DataManager.py` is an intertwined 700+ line class. It manually scrapes fundamentals, normalizes them, computes trailing-twelve-month (TTM) figures, and handles generic OHLCV storage simultaneously.
- *Duplication:* Dual-writes everything to both `.csv` and `.parquet`.

## Modules

| File | Purpose |
|------|---------|
| `data_manager.py` | OHLCV + fundamentals fetch/cache (Alpaca primary, yfinance fallback). |
| `macro_data.py` | FRED macro series fetch/cache. Cache at `data/macro/<SERIES_ID>.parquet`. Env: `FRED_API_KEY`. See "Macro data pipeline" below. |
| `earnings_data.py` | Finnhub earnings calendar + EPS/revenue surprise fetch/cache. Cache at `data/earnings/<SYMBOL>_calendar.parquet`. Env: `FINNHUB_API_KEY`. See "Earnings data pipeline" below. |
| `universe.py` | Survivorship-bias-aware S&P 500 historical membership loader (Wikipedia scrape). Cache at `data/universe/sp500_membership.parquet`. No API key required. See "Universe membership pipeline" below. |
| `universe_resolver.py` | Backtest-time universe resolution. Bridges the membership loader and the orchestration layer's static-list contract via `resolve_universe(...)`. Cache-only, never hits the network. |
| `fundamentals/loader.py` | Fundamentals loader helpers. |

## Macro data pipeline (`macro_data.py`)

Self-contained FRED ingestion layer. **Not yet wired into any engine** —
this is plumbing for upcoming work on macro features, regime
classification, and yield-curve / credit-spread edges (see
`docs/Sessions/2026-04-24_strategic_pivot.md` item #4).

**Public API:**
- `MacroDataManager(api_key=None, cache_dir="data/macro")` — pulls
  `FRED_API_KEY` from `.env` if `api_key` is None. With no key the
  manager runs in cache-only mode.
- `mgr.fetch_series(series_id, start=..., end=..., force=False, max_age_hours=24)`
  → `DataFrame[date → value]`. Cache-first: returns parquet cache if
  fresher than `max_age_hours`. On network failure falls back to
  cache; raises `MacroDataError` only when there is no cache to fall
  back to.
- `mgr.fetch_panel(series_ids=None, ffill=True)` → wide DataFrame
  joining all curated series, forward-filled to a daily index by
  default.
- `mgr.cache_status()` → DataFrame describing the on-disk cache.

**Curated registry** (`MACRO_SERIES`): 18 series across yield curve,
credit, policy, inflation, labor, growth, FX, vol, and liquidity. See
the docstring in `macro_data.py` for the full list and rationale.

**Derived features:** `yoy_change`, `credit_quality_slope` (HY-IG OAS),
`real_fed_funds` (DFF − T10YIE). More-bespoke transforms belong in
the consuming edge / regime detector, not here.

**Tests:** `tests/test_macro_data.py` — 23 offline tests (HTTP layer
mocked) plus one live integration test gated behind `FRED_API_KEY`.

## Earnings data pipeline (`earnings_data.py`)

Self-contained Finnhub ingestion layer for earnings calendar +
surprise data. **Not yet wired into any engine** — this is plumbing
for the upcoming PEAD (post-earnings announcement drift) edge work
called out in `docs/Sessions/2026-04-24_strategic_pivot.md`
as the strongest single-factor alpha in the academic literature.

**Public API:**
- `EarningsDataManager(api_key=None, cache_dir="data/earnings", rate_limit_s=1.1)`
  — pulls `FINNHUB_API_KEY` from `.env` if `api_key` is None. With
  no key the manager runs in cache-only mode. The 1.1s default
  rate-limit keeps us under Finnhub's 60 req/min free-tier ceiling;
  set to 0 in tests.
- `mgr.fetch_calendar(symbol, start="2020-01-01", end=None, force=False, max_age_hours=24)`
  → `DataFrame[announcement_date → event row]`. Cache-first:
  returns the parquet cache if fresher than `max_age_hours`. On
  network failure falls back to cache; raises `EarningsDataError`
  only when there is no cache to fall back to.
- `mgr.fetch_universe(symbols, ...)` → long-form events DataFrame
  concatenating all symbols, sorted by announcement date. Per-symbol
  failures are skipped with a warning; the run only raises if every
  symbol fails.
- `mgr.cache_status()` → DataFrame describing every parquet on disk
  (universe is open-ended, so this walks the cache dir rather than
  iterating a registry like the FRED variant).

**Schema** (`EVENT_COLUMNS`): index `announcement_date`, columns
`symbol`, `eps_actual`, `eps_estimate`, `eps_surprise`,
`eps_surprise_pct`, `revenue_actual`, `revenue_estimate`,
`revenue_surprise`, `revenue_surprise_pct`, `hour` (`bmo`/`amc`),
`quarter` (`Int64`), `year` (`Int64`). Surprise percentages use
`(actual − estimate) / |estimate|` so misses on negative-consensus
loss companies get the right sign. NaN whenever estimate is zero
or either side is missing.

**Helpers:** `surprise_pct(actual, estimate)` exposed for ad-hoc
use. More-bespoke transforms (rolling z-scores, drift windows,
event-aligned price panels) belong in the consuming edge, not here.

**Tests:** `tests/test_earnings_data.py` — 29 offline tests (HTTP
layer mocked) plus one live integration test gated behind
`FINNHUB_API_KEY`.

## Universe membership pipeline (`universe.py`)

Self-contained Wikipedia scraper for S&P 500 historical membership.
**Wired into ModeController via `universe_resolver.resolve_universe`
(2026-05-09).** The wiring is opt-in: default behavior remains the
legacy static ticker list in `config/backtest_settings.json`. Setting
`use_historical_universe: true` in that config (or passing
`--use-historical-universe` to `scripts/run_multi_year`) swaps in the
survivorship-aware annual-anchor union of constituents over the backtest
window. No API key required.

**Public API:**
- `SP500MembershipLoader(cache_dir="data/universe")` — fetch + cache
  the membership table.
- `loader.fetch_membership(force=False, max_age_hours=168)` →
  long-format `DataFrame[ticker, name, sector, included_from,
  included_until]`. Cache-first: returns the parquet cache if fresher
  than `max_age_hours` (default 7 days; membership changes are rare,
  no need to thrash Wikipedia). On network failure falls back to
  cache; raises `UniverseError` only when there is no cache to fall
  back to.
- `loader.current_constituents()` → tickers whose `included_until` is
  NaT (the open spell).
- `loader.historical_constituents(as_of)` → survivorship-bias-aware
  snapshot of which tickers were in the index on a given date.
- `loader.cache_status()` → dict describing the on-disk cache.

**Pure helpers** (no I/O — useful in tests or for consumers that want
to manipulate membership frames):
- `parse_membership_html(html)` — Wikipedia HTML → membership frame.
- `current_tickers(df)` / `active_at(df, as_of)` — query a frame
  directly.
- `normalize_ticker(t)` — strip footnotes, uppercase, etc.

**Schema** (`MEMBERSHIP_COLUMNS`): `ticker` (str), `name` (object),
`sector` (object), `included_from` (datetime64, NaT if pre-changelog),
`included_until` (datetime64, NaT if currently active). One row per
(ticker, spell-of-membership); a ticker that's been added and removed
multiple times has multiple rows.

**Limitations:** the Wikipedia "changes" table only goes back ~30
years and is volunteer-maintained. For tickers currently in the index
with no entry in the change log, `included_from` falls back to the
"Date added" column of the current table; if that's also missing, it's
NaT.

**CLI companion:** `scripts/fetch_universe.py` — explicit
user-driven tool that uses the membership list to populate
`data/processed/` via the existing `DataManager` pipeline. See
`docs/Core/execution_manual.md` for usage.

**Tests:** `tests/test_universe.py` — 40 offline tests (HTTP layer
mocked, parser exercised against fixture HTML) plus one live
integration test gated behind `UNIVERSE_LIVE_TEST=1`.

<!-- AUTO-GENERATED: DO NOT EDIT BELOW -->

## Auto-Generated Code Reference

*This section is automatically built by `scripts/sync_docs.py`. Do not edit manually.*

### `data_manager.py`
- **Class `DataManager`**: No docstring
  - `def __init__()`
  - `def prefetch_fundamentals()`: Batch-fetch and cache fundamentals for all tickers. Call during data loading.
  - `def fetch_historical_fundamentals()`: Reconstructs DEEP historical fundamental time-series.
  - `def fetch_fundamentals()`: Fetch fundamental data (P/E, EPS, etc.) for a ticker.
  - `def cache_path()`
  - `def parquet_cache_path()`
  - `def load_cached()`
  - `def save_cache()`
  - `def load_or_fetch()`: Try to load from Parquet cache, then CSV, then use fetch_func if provided.
  - `def ensure_data()`
- **Function `is_info_enabled()`**: No docstring

### `earnings_data.py`
**Module Docstring:** yfinance-backed earnings calendar + surprise data pipeline.
- **Class `EarningsDataError`**: Raised for non-recoverable failures in the earnings pipeline.
- **Class `EarningsEvent`**: Lightweight value type for a single earnings announcement.
- **Class `EarningsDataManager`**: Fetch + cache yfinance earnings calendar entries per ticker.
  - `def __init__()`
  - `def load_cached()`: Read a cached calendar without touching the network.
  - `def fetch_calendar()`: Fetch one ticker's earnings calendar, with cache.
  - `def fetch_universe()`: Fetch a list of tickers and concatenate into a long events frame.
  - `def cache_status()`: Return a DataFrame describing the on-disk cache state.
- **Function `surprise_pct()`**: Standard surprise-magnitude transform.

### `insider_data.py`
**Module Docstring:** OpenInsider Form 4 scraping pipeline.
- **Class `InsiderDataError`**: Raised for non-recoverable failures in the insider data pipeline.
- **Class `InsiderTxn`**: Lightweight value type for a single insider transaction.
- **Class `InsiderDataManager`**: Fetch + cache OpenInsider Form 4 transactions per ticker.
  - `def __init__()`
  - `def load_cached()`: Read a cached transactions frame without touching the network.
  - `def fetch_filings()`: Fetch one ticker's insider transactions, with cache.
  - `def fetch_universe()`: Fetch a list of tickers and concatenate into one long frame.
  - `def cache_status()`: Return a DataFrame describing the on-disk cache state.
- **Function `parse_insider_table()`**: Parse an OpenInsider screener HTML response.

### `macro_data.py`
**Module Docstring:** FRED macro data pipeline.
- **Class `MacroDataError`**: Raised for non-recoverable failures in the macro pipeline.
- **Class `MacroSeries`**: Metadata describing a single FRED series we care about.
- **Class `MacroDataManager`**: Fetch + cache FRED macro series.
  - `def __init__()`
  - `def load_cached()`: Read a cached series without touching the network.
  - `def fetch_series()`: Fetch a single FRED series, with cache.
  - `def fetch_panel()`: Fetch a wide panel of macro series.
  - `def cache_status()`: Return a DataFrame describing the on-disk cache state.
- **Function `list_series()`**: Return the curated series registry, optionally filtered by category.
- **Function `yoy_change()`**: Year-over-year change (default monthly cadence: 12 periods).
- **Function `credit_quality_slope()`**: HY OAS minus IG OAS — widens before risk-off events.
- **Function `real_fed_funds()`**: DFF minus 10y breakeven inflation. Rough real-policy-rate proxy.

### `universe.py`
**Module Docstring:** Survivorship-bias-aware S&P 500 historical membership pipeline.
- **Class `UniverseError`**: Raised for non-recoverable failures in the universe pipeline.
- **Class `SP500MembershipLoader`**: Fetch + cache the Wikipedia S&P 500 membership history.
  - `def __init__()`
  - `def load_cached()`: Read the cached membership parquet without touching the network.
  - `def fetch_membership()`: Fetch the S&P 500 membership history, with cache.
  - `def current_constituents()`: Return the list of tickers currently in the index.
  - `def historical_constituents()`: Tickers active on a given date — the survivorship-bias-aware view.
  - `def cache_status()`: Return a dict describing the on-disk cache state.
- **Function `parse_membership_html()`**: Convert raw Wikipedia HTML into the canonical membership frame.
- **Function `current_tickers()`**: Tickers whose most recent spell is still open (included_until NaT).
- **Function `active_at()`**: Tickers active on ``as_of``.
- **Function `normalize_ticker()`**: Trim, uppercase, and strip Wikipedia footnote markers like '[1]'.
