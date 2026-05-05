# Session Summary: 2026-04-24 (S&P 500 universe data foundation)

> Parallel session run alongside another instance mid-experiment on
> the freshly-expanded 109-ticker universe (which just regressed
> Sharpe). Hard scope constraints: no backtests, no edits to configs
> / governor data / edges / engine_f / mode_controller / edge_registry
> / `reset_base_edges.py` / `edges.yml` / `edge_weights.json`. This
> session was foundation-only data-manager work, mirroring the FRED
> and earnings session pattern from earlier the same day.

## What was worked on

- Built [engines/data_manager/universe.py](../../engines/data_manager/universe.py) — a self-contained Wikipedia scraper + parquet cache for the S&P 500's historical membership. Parses both the current constituents table and the change-history table, then assembles spells per ticker so consumers can ask "who was in the index on date X" without survivorship bias. Output: `data/universe/sp500_membership.parquet` with `[ticker, name, sector, included_from, included_until]` (one row per spell-of-membership).
- Built [scripts/fetch_universe.py](../../scripts/fetch_universe.py) — explicit user-driven CLI that takes a ticker source (`sp500_historical`, `sp500_current`, or `file`), checks `data/processed/parquet/` for what's already cached, and fetches missing tickers via the existing `DataManager.ensure_data` pipeline. Idempotent by default; supports `--dry-run`, `--max-tickers`, `--refresh`, `--rate-limit-s`.
- Wrote [tests/test_universe.py](../../tests/test_universe.py) — 40 offline tests (HTTP mocked, parser exercised against fixture HTML inline in the test file) plus one live integration test gated behind `UNIVERSE_LIVE_TEST=1`. **40 passed, 1 skipped.** FRED + earnings suites still passing (52 passed, 2 skipped) — no regression.
- Re-exported the public API at the package level in [engines/data_manager/__init__.py](../../engines/data_manager/__init__.py).
- Documented the module in [engines/data_manager/index.md](../../engines/data_manager/index.md) and added a `UNIVERSE MEMBERSHIP (S&P 500 historical)` section to [docs/Core/execution_manual.md](../Core/execution_manual.md) covering both the loader and the CLI.

## What was decided

- **No API key required** — Wikipedia is public. The loader sets a polite `User-Agent` (Wikipedia returns 403 to bare `requests` calls) and uses bs4 + lxml to parse. No new dependencies added (both already in `requirements.txt`).
- **Cache layout:** parquet at `data/universe/sp500_membership.parquet` plus a sidecar `_meta.json`. Mirrors the FRED / earnings pattern. `data/` is gitignored, so cache stays local.
- **Long refresh window (7 days default).** S&P 500 changes are rare (~25/year). Refreshing weekly catches every event the strategy could possibly need without thrashing Wikipedia.
- **Long-format schema, not wide.** One row per (ticker, spell). A ticker that's been added → removed → re-added gets two rows. This makes survivorship-bias-aware queries (`active_at(date)`) trivial and keeps re-entry semantics explicit instead of squashing them into a single row.
- **Graceful degradation everywhere.** Network down → return cached parquet with a warning. Bad HTML structure → raise `UniverseError`. No cache and no network → only then does anything raise. Same convention as FRED / earnings.
- **Pure-function parser (`parse_membership_html(html)`)** so tests can feed fixture HTML directly without mocking `requests`. The test file ships a small but structurally faithful Wikipedia-shaped HTML fixture covering: a current ticker with no change-log entry (AAPL), a current ticker that was added recently (NEW1), a removed-only ticker (OLD1 → closed spell), and an added-then-removed ticker (OLD2 → single closed spell with both ends populated).
- **Tickers in the current table with no addition event in the change log fall back to the current table's `Date added` column.** Many decades-old constituents (AAPL, JNJ, etc.) predate the change log, so their row would otherwise have NaT for `included_from`. The fallback gives consumers a usable bound. If even the current table's `Date added` is missing, `included_from` stays NaT — meaning "since before the change log started," which `active_at` interprets correctly.
- **Removal date is exclusive.** A ticker removed on `2020-06-01` is not active on `2020-06-01`. This matches the convention that exchange index changes take effect at market open on the announced date.
- **CLI is strictly idempotent and never auto-runs.** Per the brief, populating ~400 missing tickers is an explicit user action with API rate-limit and time considerations. The script is not imported by anything; the only way it executes is `python -m scripts.fetch_universe`. It also short-circuits with code 0 when the universe is already cached, so re-running it is safe.
- **CLI surfaces a credentials error before doing anything.** If Alpaca creds aren't in `.env` and there's actual fetching to do, the script exits with code 2 and a clear message rather than failing per-ticker downstream. Cached-only invocations (everything already on disk) do not need credentials and don't trigger the check.
- **Three sources, not one.** `sp500_historical` (full union of every ticker ever in the index — the survivorship-bias-aware default for backtests), `sp500_current` (today's constituents only), `file` (newline-separated ticker file — escape hatch for custom universes). The CLI does not bake a choice into the user; the strategic-pivot doc points at `sp500_historical` as the default for factor work but the others are useful for narrower experiments.
- **Deliberately did not wire into engines, did not change configs, did not run a backtest.** Per session brief, integration is the next-session handoff. New universe goes in a separate config for later opt-in once the data is bootstrapped.

## What was learned

- The Wikipedia change-history table has a two-row header (`Date | Added | Removed | Reason` over `| Ticker | Security | Ticker | Security |`). Parsing it positionally by column index is the most robust approach — header-row inference would over-couple the parser to one specific revision of the page. The parser skips any row whose first cell isn't a parseable date, which lets it survive both header formats and any future header changes.
- `pd.NaT` comparison via `is` is unreliable; always use `pd.isna()`. Mattered in `_build_membership` and `active_at`.
- Wikipedia rejects `requests` calls with no User-Agent (returns 403). The default UA in this loader identifies the project; without it a fresh user would get a confusing 403 error from `fetch_membership`.
- The "remove without prior add" case (a ticker that was in the index from before the change log started, then got removed mid-log) is a real shape — the parser handles it by emitting a spell with `included_from=NaT` and `included_until=removal_date`. `active_at` interprets NaT-from as "always-on up to until" so historical queries before the log starts still see the ticker as active.

## Pick up next time

- **Run the fetcher to populate the historical universe.** This is the explicit user action the session deferred:
  ```bash
  python -m scripts.fetch_universe --source sp500_historical --start 2018-01-01 --dry-run
  python -m scripts.fetch_universe --source sp500_historical --start 2018-01-01
  ```
  Expect ~400-500 missing tickers depending on what's already in `data/processed/parquet/`. Free-tier Alpaca will take 30-60 minutes including yfinance fallbacks for symbols Alpaca rejects.
- **Once data is on disk, build `config/backtest_settings.<universe>.json`** (or whatever the opt-in pattern ends up being) pointing at the broader universe. Don't overwrite `config/backtest_settings.json` while the active investigation is using the current 109-ticker universe.
- **Re-test `momentum_factor_v1`** (code retained at `engines/engine_a_alpha/edges/momentum_factor_edge.py`, currently `failed`/weight 0). The pivot doc identifies the universe size as the suspected cause of the falsification — testing it on a properly-built ~500-name universe is the moment-of-truth for cross-sectional factor work.
- **Membership integration into Engine D / Engine A** — once the fetcher has run, the next architectural step is letting consumers use `historical_constituents(as_of)` so a backtest at e.g. 2018-Q1 doesn't see tickers that joined the index in 2023.

## Files touched

```
engines/data_manager/universe.py         (new)
scripts/fetch_universe.py                (new)
tests/test_universe.py                   (new)
engines/data_manager/__init__.py         (re-export)
engines/data_manager/index.md            (added Universe membership pipeline section)
docs/Core/execution_manual.md            (added UNIVERSE MEMBERSHIP CLI section)
docs/Progress_Summaries/2026-04-24_session_universe_data.md  (new — this file)
```

## Subagents invoked

None. The work fit comfortably in a single session: scaffold a module + CLI mirroring the established FRED / earnings pattern, then a focused test file. Future integration work (wiring `historical_constituents` into the backtest controller, adding a universe-size slider in `cockpit/dashboard_v2`) should route through `quant-dev` and `ux-engineer` subagents respectively.
