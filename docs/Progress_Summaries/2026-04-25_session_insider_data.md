# Session Summary: 2026-04-25 — Insider Transactions Data Foundation

> Parallel session, scoped to the data layer only. The user explicitly
> deferred edge construction to a separate handoff. Confirmed in flight:
> a separate session has already shipped `insider_cluster_edge.py` that
> consumes the schema this module produces.

## What was worked on

- New `engines/data_manager/insider_data.py` — `InsiderDataManager`
  class plus public `parse_insider_table` helper. Mirrors the
  established scaffold pattern from `earnings_data.py` and
  `macro_data.py`: HTTP-fetch → parquet cache, cache-first reads with
  24h freshness, graceful network-failure degradation, configurable
  rate limiting, `_meta.json` sidecar.
- Source: OpenInsider (`http://openinsider.com/screener?s=...`),
  unauthenticated, scraped via `requests` + `BeautifulSoup`. Single-
  page fetch (cnt=1000), filing-date-range filter back to 2020.
- New `tests/test_insider_data.py` — 35 offline tests + 1 gated live
  integration. All offline tests mock
  `engines.data_manager.insider_data.requests.get`. Coverage groups:
  cell-level helpers (8), parser (8), fetch+cache (6), graceful
  degradation (7), universe (4), cache status (2). 35 passed,
  1 skipped (live), runtime 2.54s.
- Re-exports added to `engines/data_manager/__init__.py`:
  `INSIDER_TXN_COLUMNS`, `InsiderDataError`, `InsiderDataManager`,
  `InsiderTxn`, `parse_insider_table`. All in `__all__`.
- New `### INSIDER TRANSACTIONS (OPENINSIDER)` block in
  `docs/Core/execution_manual.md` between the EARNINGS DATA and
  UNIVERSE MEMBERSHIP sections.

## What was decided

- **Schema is wider than the user's stated minimum.** The user named
  7 required columns (transaction_date, ticker, insider_name,
  transaction_type P/S, shares, dollar_value, holdings_after). I
  added `filing_date`, `insider_title`, `transaction_subtype`,
  `price`, `delta_holdings_pct` because they come free from the same
  scrape and are routinely useful for edge design (filing-date-lag
  effects, executive-rank weighting, S-vs-S+OE filtering, per-share
  vs total-value normalization). Trim is a 5-minute revert if the
  lean spec was a hard requirement.
- **`transaction_type` is the single normalized char (P or S),
  `transaction_subtype` preserves the full OpenInsider label.**
  This way a downstream edge can do the simple `df["transaction_type"]
  == "P"` filter (which the parallel insider_cluster_edge already
  does) while still being able to drop sale-on-option-exercise
  ("S - Sale+OE") if it wants to.
- **`shares` and `value` are signed.** Sales come back as negative
  qty and negative dollar value. Mirrors what OpenInsider actually
  shows ("-30,002" for Qty, "-$7,660,875" for Value). Edges can
  always use `.abs()` if they need magnitude — keeping the sign is
  information-preserving.
- **`delta_holdings_pct` is fractional, not percent.** -18% in the
  HTML becomes -0.18 in the cached frame. Consistent with how every
  other "_pct" column in the project works (e.g. `eps_surprise_pct`).
  The "New" sentinel — used when an insider's first reported holding
  is the transaction itself — becomes NaN.
- **Rate limit defaults to 1.5s/call.** OpenInsider is operated by a
  small team. The user explicitly asked for 1+ second; 1.5 leaves
  headroom while still letting a 109-ticker universe refresh in
  under three minutes. Configurable to 0 in tests.
- **No pagination in v1.** Single-page fetch with cnt=1000. For the
  current 109-ticker universe none of the names exceed 1000 rows
  back to 2020 (large-cap insiders trade frequently but not THAT
  frequently). A `_log` warning fires if a ticker hits the cap so
  we'll know when pagination becomes necessary.
- **No API-key path.** Unlike `earnings_data.py` and `macro_data.py`,
  there's no `api_key` parameter and no `cache_only=True` flag.
  Cache-only behavior emerges naturally from cache-first reads +
  network-failure fallback. Keeps the surface area minimal.
- **Empty-table responses still write a zero-row parquet.** Same
  convention as the earnings module: tickers with no Form 4 activity
  in the window get a zero-row cache so they don't re-hit the
  network on every call.

## What was learned

- **OpenInsider's table structure is stable and clean.** Verified
  live before writing the parser — 16 columns, predictable order,
  `<table class="tinytable">` is the canonical selector. Headers
  contain `&nbsp;` (encoded as `\xa0` in BeautifulSoup output) which
  the parser strips via `.replace("\xa0", " ")`. Trade-type cells use
  `" - "` as a separator: "P - Purchase", "S - Sale", "S - Sale+OE".
  First character is the canonical action code.
- **Parallel-session compatibility was confirmed before re-export.**
  Another instance had already shipped
  `engines/engine_a_alpha/edges/insider_cluster_edge.py` that imports
  `InsiderDataManager` and reads `transaction_type == "P"`,
  `insider_name`, `value` (using `.abs()`), and `transaction_date`
  as the index. All schema choices align — no rework needed in
  either direction.
- **Empty `<tbody>` returning an empty frame (not raising) is a
  forced behavior, not just a nicety.** Half the universe will have
  no Form 4 filings in any given quarter; raising would force every
  caller to wrap in try/except. The `EMPTY_TABLE_HTML` test ensures
  the manager writes a zero-row parquet so the next call short-
  circuits the network.

## Pick up next time

This session shipped the data foundation only. The natural next
step is **populating the cache for the 109-ticker universe** with a
single bootstrap run:

```bash
python -c "import json; from engines.data_manager.insider_data import InsiderDataManager; \
cfg = json.load(open('config/backtest_settings.json')); \
mgr = InsiderDataManager(); \
df = mgr.fetch_universe(cfg.get('tickers') or cfg.get('universe')); \
print(mgr.cache_status().to_string())"
```

Expected runtime: ~3 minutes at the 1.5s rate limit. After that,
`insider_cluster_edge.py` (already shipped by parallel session)
should stop abstaining and start firing on real cluster events.
A walk-forward A/B against the post-autonomy baseline canon
(`d3799688ad14921a3e27e70231013d70`) is the moment-of-truth
test for whether insider-cluster signal adds OOS Sharpe.

If `RUN_OPENINSIDER_INTEGRATION=1` is set, the gated live test in
`tests/test_insider_data.py::test_live_openinsider_aapl_fetch`
exercises a single network round-trip with the configured rate
limit — useful as a smoke test before the bootstrap run.

## Files touched

```
engines/data_manager/insider_data.py        (new, 354 lines)
engines/data_manager/__init__.py            (re-exports added)
tests/test_insider_data.py                  (new, 36 tests)
docs/Core/execution_manual.md               (INSIDER TRANSACTIONS section added)
docs/Progress_Summaries/2026-04-25_session_insider_data.md  (new — this file)
```

No engine, no config, no governor, no edge, no orchestration files
were modified. Per the user's hard constraints, no backtest was run.

## Subagents invoked

None. The user explicitly told this session to stay in the main
conversation; the canonical pattern in `earnings_data.py` and
`macro_data.py` was prescriptive enough that delegation to
`quant-dev` would have been overhead.
