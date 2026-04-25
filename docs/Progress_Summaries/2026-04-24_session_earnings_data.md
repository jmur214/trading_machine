# Session Summary: 2026-04-24 (Finnhub earnings data scaffold)

> Parallel session run alongside another instance working in the same
> repo. Hard scope constraints: no backtests, no edits to configs /
> governor data / edges / engine_f / mode_controller / edge_registry.
> This session was foundation-only data-manager work, mirroring the
> FRED scaffold that landed earlier the same day.

## What was worked on

- Built [engines/data_manager/earnings_data.py](../../engines/data_manager/earnings_data.py) — a self-contained Finnhub ingestion module with parquet cache, rate-limited fetches, graceful network/key fallback, and a canonical 12-column event schema covering EPS actual/estimate/surprise, revenue actual/estimate/surprise, hour, quarter, and year per announcement.
- Wrote [tests/test_earnings_data.py](../../tests/test_earnings_data.py) — 29 offline tests (HTTP layer mocked) plus one live integration test gated behind `FINNHUB_API_KEY`. **29 passed, 1 skipped.** FRED suite still passes (23 passed, 1 skipped) — no regression.
- Documented the new module in [engines/data_manager/index.md](../../engines/data_manager/index.md), added an `EARNINGS DATA (FINNHUB)` block to [docs/Core/execution_manual.md](../Core/execution_manual.md), and re-exported the public API at the package level in [engines/data_manager/__init__.py](../../engines/data_manager/__init__.py).

## What was decided

- **Cache layout:** parquet per symbol at `data/earnings/<SYMBOL>_calendar.parquet` plus a sidecar `_meta.json`. Mirrors the FRED `<SERIES_ID>.parquet` pattern verbatim. `data/` is gitignored, so cache stays local.
- **Cache-first reads with 24h default freshness window.** Earnings are quarterly events; intraday refresh adds nothing, daily refresh catches new prints without thrashing the API.
- **Graceful degradation over hard failure.** Network down → return cache with a warning. No cache and no key → only then raise `EarningsDataError`. Edges should never crash because Finnhub is offline.
- **Cache-only mode when `FINNHUB_API_KEY` is missing.** Same convention as FRED — module is importable in CI / fresh clones without secrets, and one session can populate the cache for another to consume.
- **Compute surprise locally, don't trust Finnhub's `surprisePercent` field.** The calendar endpoint doesn't return it anyway, only `epsActual` and `epsEstimate`. Computing `(a − e) / |e|` in-module makes the formula auditable, applies the same convention to revenue surprise (which Finnhub also doesn't pre-compute), and uses `|estimate|` so misses on negative-consensus loss companies get the right sign — a common bug in naive implementations.
- **Per-call rate limit (1.1s default).** Finnhub free tier ceiling is 60 req/min. Sleeping 1.1s between calls keeps us safely under that without wasting time. Configurable; tests pass `rate_limit_s=0`.
- **No curated registry.** Unlike FRED's 18 hand-picked macro series, the earnings universe is open-ended (every ticker the strategy trades). `cache_status()` therefore walks the cache directory rather than iterating a registry.
- **`fetch_universe` skips per-symbol failures rather than aborting.** Important once we run this against an S&P 500 universe — one delisted ticker shouldn't kill a 500-symbol bootstrap run.
- **Deliberately did not wire into engines.** Per session brief, integration is the next-session handoff. Module is foundation only.
- **Re-exported public API at the package level** so consumers can `from engines.data_manager import EarningsDataManager`. Existing FRED + DataManager imports still work — verified with `tests/test_macro_data.py` and a manual `from engines.data_manager.data_manager import DataManager` smoke check.

## What was learned

- **Finnhub's `earningsCalendar` field can come back as `null`** for symbols with no events in the queried window (vs. an empty list, which would also be valid). The parser treats null as "no events, write an empty cache" rather than raising — an empty cache is still progress because the next call will short-circuit instead of re-asking the API.
- **The free-tier per-symbol calendar query does not appear to be limited to 365 days** despite the documented `from`/`to` constraint that applies to symbol-less queries. A 2020-01-01 → today range returns the full 5+ years for AAPL. Did not verify exhaustively across all symbols; the live integration test asserts only on a 2023 window to stay deterministic.
- **`pd.read_parquet` round-trips `Int64` and `Object` dtypes cleanly**, so the cached frames preserve the canonical schema. No need for an explicit dtype-restoration step on cache load.
- **Plan mode activating mid-task is graceful** — code that was already written and tested before activation persists; only further edits get gated. Wrote a snapshot plan covering "what's done, what's pending" rather than re-deriving everything from scratch.

## Pick up next time

The natural next handoff is a **PEAD edge** in `engines/engine_a_alpha/edges/pead_edge.py` reading from `EarningsDataManager.fetch_universe()`. Sketch:

1. On each bar, for each open universe ticker, look up the most recent event in the cached events frame.
2. If the event is within the drift window (~60 trading days post-announcement) and `eps_surprise_pct` exceeds a magnitude threshold (e.g., |z| > 1 of trailing 8-quarter z-score), emit a position in the surprise direction.
3. Walk-forward A/B against the post-autonomy baseline (canon `d3799688ad14921a3e27e70231013d70`, Sharpe 0.979). The strategic pivot doc projects standalone Sharpe 1.0+ for PEAD; a +0.3 Sharpe lift on the combined stack would mark the system competitive with SPY OOS.

Prerequisite for the edge work: someone needs to register a free Finnhub key (`FINNHUB_API_KEY` in `.env`) and run the universe bootstrap snippet from `execution_manual.md` to populate `data/earnings/`. Without that the edge has nothing to read.

## Files touched

```
engines/data_manager/earnings_data.py        (new)
engines/data_manager/__init__.py             (added earnings re-exports)
engines/data_manager/index.md                (added Earnings data pipeline section)
tests/test_earnings_data.py                  (new, 29 + 1 gated)
docs/Core/execution_manual.md                (added EARNINGS DATA (FINNHUB) section)
docs/Progress_Summaries/2026-04-24_session_earnings_data.md  (new — this file)
```

## Subagents invoked

None this session. Future PEAD edge work should route through `edge-analyst` and `quant-dev` per `.claude/agents/`.
