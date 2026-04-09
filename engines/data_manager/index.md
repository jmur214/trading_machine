# Data Manager Engine
**Purpose:** Single point of truth for fetching, caching, and serving financial data to the entire system.
**Architectural Role:** Abstracts Alpaca and YFinance APIs. Caches aggressively to speed up backtests.

**Known Issues & Quirks:**
- *The Monolith Problem:* `DataManager.py` is an intertwined 700+ line class. It manually scrapes fundamentals, normalizes them, computes trailing-twelve-month (TTM) figures, and handles generic OHLCV storage simultaneously.
- *Duplication:* Dual-writes everything to both `.csv` and `.parquet`.

<!-- AUTO-GENERATED: DO NOT EDIT BELOW -->

## Auto-Generated Code Reference

*This section is automatically built by `scripts/sync_docs.py`. Do not edit manually.*

### `data_manager.py`
- **Class `DataManager`**: No docstring
  - `def __init__()`
  - `def fetch_historical_fundamentals()`: Reconstructs DEEP historical fundamental time-series.
  - `def fetch_fundamentals()`: Fetch fundamental data (P/E, EPS, etc.) for a ticker.
  - `def cache_path()`
  - `def parquet_cache_path()`
  - `def load_cached()`
  - `def save_cache()`
  - `def load_or_fetch()`: Try to load from Parquet cache, then CSV, then use fetch_func if provided.
  - `def ensure_data()`
- **Function `is_info_enabled()`**: No docstring
