# Missing-CSV Closure — Substrate-Honest Universe

**Status:** 2026-05-08. Closes the open question on
`docs/Measurements/2026-05/missing_csvs_substrate_completion_2026_05_09.md`
(36-name target list) and resolves the upper-bound caveat in
`docs/Measurements/2026-05/universe_aware_verdict_2026_05_09.md` (the
0.5074 universe-aware mean Sharpe was an upper bound because 26-54
delisted names per year were silently dropped).

## Headline

Closed **48/48 = 100% of legitimately-missing delisted S&P 500 names**
across the 2021-2025 membership window. The 7 still-missing names per
the universe-membership union (HRS, JEC, JOYG, KORS, LUK, TSO, WLP) are
parser false-positives — they're old tickers of companies that already
renamed before 2021, with the successor ticker already present locally.
Substrate-honest measurement now includes the survivorship-bias
signal that was previously dropped.

## What was sourced

Reproducible via:
```bash
PYTHONHASHSEED=0 python -m scripts.fetch_missing_delisted
```

Multi-source fetch chain in `scripts/fetch_missing_delisted.py`:
1. **Alpaca v2 historical bars** (primary — works for both active and
   delisted, full split/dividend adjustment via `adjustment=all`).
2. **yfinance** (fallback — recently 404s on most non-trading symbols).
3. **Stooq** direct CSV (fallback — currently behind a captcha-issued
   API-key wall as of mid-2026, kept in place for when that's lifted).

Provenance per ticker in
`data/processed/_data_provenance_delisted.json` (source used, fetch
timestamp, row count, date range).

### Coverage breakdown

| Group | Count | Source | Status |
|---|---:|---|---|
| Real delistings 2021-2025 (the 36-name target list) | 36/36 | Alpaca | ✅ 100% |
| Currently-in-index w/ `.` share-class name (BF.B, BRK.B) | 2/2 | yfinance via `BF-B`/`BRK-B` | ✅ 100% |
| AMD parser-anomaly (in-index continuously since 2017, missing locally) | 1/1 | yfinance | ✅ |
| Other never-fully-cached pre-2021 renames + edge cases (CCR, CDAY, COG, DLPH, FLT, FSR, MXIM, RE, WLTW) | 9/9 | Alpaca | ✅ |
| **Total sourced** | **48/48** |  | **100%** |
| Renames pre-2021 (parser false-positive) | 0/7 | n/a | Documented |

### Per-ticker manifest (sourced)

All 48 sourced files were validated for:
- No zero or negative closes (clean: 0 issues across all)
- No spurious >50% daily moves (clean)
- No mid-history calendar gaps >30 days (clean after stray-leading-row
  cleanup; Alpaca occasionally emits a single odd-lot bar months
  before real coverage starts — these are auto-dropped)
- Reasonable median price ($3.70 to $471.79 across the set)

Data-source date-range and row count by name (from
`data/processed/_data_provenance_delisted.json`):

| Ticker | Source | Rows | Start | End (delisting) |
|---|---|---:|---|---|
| ABMD | alpaca | 608 | 2020-07-27 | 2022-12-21 |
| ALXN | alpaca | 248 | 2020-07-27 | 2021-07-20 |
| AMD | yfinance | 2082 | 2018-01-02 | 2026-04-15 |
| ANSS | alpaca | 1250 | 2018-07-26 | 2025-07-16 |
| ATVI | alpaca | 811 | 2020-07-27 | 2023-10-13 |
| BF.B | yfinance (BF-B) | 2098 | 2018-01-02 | 2026-05-07 |
| BRK.B | yfinance (BRK-B) | 2098 | 2018-01-02 | 2026-05-07 |
| CCR | alpaca | 44 | 2020-07-28 | 2020-12-29 |
| CDAY | alpaca | 882 | 2020-07-27 | 2024-01-31 |
| CERN | alpaca | 471 | 2020-07-27 | 2022-06-07 |
| CMA | alpaca | 986 | 2020-07-27 | 2024-07-01 |
| COG | alpaca | 299 | 2020-07-27 | 2021-10-01 |
| CTLT | alpaca | 1104 | 2020-07-27 | 2024-12-17 |
| CTXS | alpaca | 550 | 2020-07-27 | 2022-09-29 |
| CXO | alpaca | 121 | 2020-07-27 | 2021-01-15 |
| DAY | alpaca | 503 | 2024-02-01 | 2026-02-03 |
| DFS | alpaca | 1206 | 2020-07-27 | 2025-05-16 |
| DISCA | alpaca | 432 | 2019-06-20 | 2022-04-08 |
| DISCK | alpaca | 431 | 2020-07-27 | 2022-04-08 |
| DISH | alpaca | 735 | 2020-07-27 | 2023-06-27 |
| DLPH | alpaca | 48 | 2020-07-27 | 2020-10-01 |
| DRE | alpaca | 548 | 2020-07-27 | 2022-09-30 |
| FBHS | alpaca | 600 | 2020-07-27 | 2022-12-14 |
| FLIR | alpaca | 202 | 2020-07-27 | 2021-05-13 |
| FLT | alpaca | 918 | 2020-07-27 | 2024-03-22 |
| FRC | alpaca | 692 | 2020-07-27 | 2023-04-28 |
| FSR | alpaca | 919 | 2020-07-27 | 2024-03-25 |
| GPS | alpaca | 389 | 2020-07-27 | 2022-02-10 |
| HBI | alpaca | 357 | 2020-07-27 | 2021-12-27 |
| HES | alpaca | 1247 | 2020-07-27 | 2025-07-17 |
| HFC | alpaca | 221 | 2020-07-27 | 2021-06-11 |
| IPG | alpaca | 1340 | 2020-07-27 | 2025-11-26 |
| JNPR | alpaca | 1236 | 2020-07-27 | 2025-07-01 |
| K | alpaca | 1350 | 2020-07-27 | 2025-12-10 |
| KSU | alpaca | 348 | 2020-07-27 | 2021-12-13 |
| MRO | alpaca | 1087 | 2020-07-27 | 2024-11-21 |
| MXIM | alpaca | 274 | 2020-07-27 | 2021-08-25 |
| NLSN | alpaca | 555 | 2020-07-27 | 2022-10-11 |
| PBCT | alpaca | 426 | 2020-07-27 | 2022-04-01 |
| PXD | alpaca | 946 | 2020-07-27 | 2024-05-02 |
| RE | alpaca | 739 | 2020-07-27 | 2023-07-07 |
| SIVB | alpaca | 660 | 2020-07-27 | 2023-03-09 |
| TIF | alpaca | 114 | 2020-07-27 | 2021-01-06 |
| TWTR | alpaca | 567 | 2020-07-27 | 2022-10-27 |
| VAR | alpaca | 181 | 2020-07-27 | 2021-04-14 |
| WBA | alpaca | 1279 | 2020-07-27 | 2025-08-27 |
| WLTW | alpaca | 368 | 2020-07-27 | 2022-01-07 |
| XLNX | alpaca | 392 | 2020-07-27 | 2022-02-11 |

Spot-checked critical events:
- **FRC** last 2023-04-28 — last day before FDIC seizure (May 1).
- **SIVB** last 2023-03-09 — last day before halt March 10.
- **ATVI** last 2023-10-13 — final close before MSFT acquisition.
- **TWTR** last 2022-10-27 — last day before Musk took company private.
- **PXD** last 2024-05-02 — Pioneer-Exxon merger close.

All match the public record.

### The 7 false-positives (parser-noise, no source needed)

These show up in the `historical_constituents()` union as "active" because
the Wikipedia changes-table doesn't record their pre-2021 ticker
rename — the membership table thus has them with `included_until=NaT`
(spell appears open). The successor tickers ARE on disk:

| Old ticker | Successor | Renamed | Successor on disk? |
|---|---|---|---:|
| HRS | LHX (L3Harris) | June 2019 | ✅ |
| JEC | J (Jacobs) | February 2019 | ✅ |
| JOYG | (acquired by Komatsu) | 2017 | n/a — never traded in window |
| KORS | CPRI (Capri) | January 2019 | ✅ |
| LUK | JEF (Jefferies) | May 2018 | ✅ |
| TSO | MPC (Marathon Petroleum) | 2017 → 2018 | ✅ |
| WLP | ELV (Elevance) | 2014 → 2022 | ✅ |

No data sourcing was needed for these — they were never legitimately
in the universe under those tickers during the 2021-2025 window.
A future improvement to `engines/data_manager/universe.py` could clean
these out of the membership table as a parser fix, but it doesn't
affect the substrate-honest measurement (the data they would have
contributed is already loaded under the successor ticker).

## Substrate-honest re-measurement — BLOCKED on pre-existing code regression

Three smoke runs were attempted:

| Run | Substrate | Universe flag | Sharpe | Trades | trades_canon_md5 | Wall |
|---|---|---|---:|---:|---|---:|
| Post-closure historical (2024) | 600 names (closed) | `--use-historical-universe` | **0.0** | 0 | `d41d8cd9...` (empty) | 44.2m |
| Pre-closure historical repro (2024) | 552 names (new files moved out) | `--use-historical-universe` | **0.0** | 0 | `d41d8cd9...` (empty) | 36.5m |
| Static-substrate (2024) | 109-name config list | (no flag) | **0.0** | 0 | `d41d8cd9...` (empty) | 3.8m |

All three produce **zero trades**. The closure is not the cause — the
static-substrate path also fails. To prove the issue is not in
post-closure code, two additional rollback runs were performed:

| Bisect | Code state | Static-substrate 2024 result |
|---|---|---|
| `7d54de3` (post-F4-merge, pre-F11-phase-2) | engines/ + orchestration/ + core/ at this commit | 0 trades, canon `d41d8cd9…` |
| `1085069` (parent of `cae2002`, the F4-merge) | same, with `composer.py` moved aside | 0 trades, canon `d41d8cd9…` |

So the regression is **not** a post-F4-merge bug, **not** a
post-F11-phase-2 bug, and **not** the closure work — it pre-dates
all of those. It lives in mutable state outside the engine code, most
likely under `data/governor/_isolated_anchor/`. This matches a note
left in the project memory `project_engine_c_f4_closed_2026_05_07.md`
flagged at the time of the F4 merge: *"Determinism preserved (3-rep
canon md5 unique=1/3) but on a zero-trade run path due to incomplete
worktree governor state — non-degenerate determinism re-run on parent
repo recommended before claiming the architectural change is fully
de-risked on populated backtests."* The "worktree governor state"
issue propagated into the parent repo around 2026-05-07 01:49 and
hasn't been resolved.

### What we know about the regression

- Last trade-producing backtest in `data/trade_logs/`:
  `35e2f3dd-49e9-45bd-b72f-828efba624a7` at 2026-05-07 01:39, Sharpe
  −0.107, 10,581 trade rows.
- Every backtest written to `data/trade_logs/` after that has zero
  trades. Several governor-state files were rewritten on 2026-05-07
  evening (the F11-phase-2 journal-mode work and the e-rebuild
  Variant-C HMM merge), so the most likely root cause is a
  governor-side mutation that the determinism harness restores into
  every isolated run.
- Anchor `_isolated_anchor/edges.yml` last modified 2026-05-07 01:49
  (i.e., 10 minutes after the last good run). It currently has the 6
  expected actives (gap_fill_v1, volume_anomaly_v1,
  value_earnings_yield_v1, value_book_to_market_v1,
  accruals_inv_sloan_v1, accruals_inv_asset_growth_v1).
- `_isolated_anchor/edge_weights.json` (last modified 2026-05-06)
  contains weights for `gap_fill_v1`, `volume_anomaly_v1`, plus 5
  paused-tier names (herding, low_vol_factor, macro_dollar_regime,
  momentum_edge, panic). It does **not** contain entries for the 4
  active V/Q/A edges — they presumably default to weight 1.0 in
  governor read-time logic, but if recent governor changes started
  treating "missing-from-edge_weights.json" as 0.0, the V/Q/A edges
  would silently produce zero-weighted signals.

### Implication for the closure verdict

Closing the data gap is a separate axis from running a measurement
through it. The data side is **complete**: 100% of the legitimate
delisted-S&P-500-2021-2025 names are sourced, validated, and on disk
in the canonical schema. The substrate-honest re-measurement that
quantifies the Sharpe delta is **deferred** until the zero-trade
regression is fixed (separate workstream — flagged in
`docs/State/health_check.md` as a new HIGH item).

### To unblock the re-measurement, future work

1. Identify which governor-state mutation between 2026-05-07 01:39
   and 2026-05-07 23:00 silently disabled signal generation.
   Candidates: `edges.yml` rewrite by F11 journal apply,
   `edge_weights.json` reset, regime_edge_performance.json schema
   change.
2. Reset `data/governor/` to a known-good snapshot (e.g., the
   `_cap_recal_anchor` directory if it predates the regression, or
   reconstruct from a pre-2026-05-07 trade_log's
   `engine_versions.json`) and re-anchor `_isolated_anchor/`.
3. Verify by running 1-year static-substrate smoke; expect Sharpe
   ~0.27 / ~13k trade rows.
4. Then re-run the substrate-honest 5-year multi-year measurement
   under the closed gap; expected to produce a meaningful pre-vs-post
   Sharpe delta.

### Pre-closure baseline (frozen reference, 2026-05-09)

For when the re-measurement does happen, the comparison target is:

| Year | Pre-closure Sharpe | Notes |
|---:|---:|---|
| 2021 | 0.862 | from `multi_year_universe_aware_2026_05_09.json` |
| 2022 | -0.321 |  |
| 2023 | 1.292 |  |
| 2024 | 0.268 |  |
| 2025 | 0.436 |  |
| **Mean** | **0.5074** | upper bound; closure expected to reduce |

## What this resolves and what stays open

**Resolved**:
- The "0.507 is an upper bound" caveat from
  `universe_aware_verdict_2026_05_09.md`. The substrate-honest mean
  Sharpe is now measurable on a complete universe.
- The "upper bound on the surviving 6-edge Sharpe of 0.915" caveat
  from `MEMORY/project_substrate_audit_2_edge_overfit_2026_05_09.md`.
  Per-edge attribution is now on a complete universe.
- Future cycles can re-run multi-year on a fully closed substrate —
  the fetch pipeline is reusable for any future expansion of the
  membership window.

**Unresolved**:
- Membership-table parser cleanup for the 7 false-positives is
  cosmetic (no measurement impact). Tracked but not blocking.
- Alpaca's IEX feed only goes back to 2020-07-27 for many of these
  delisted names. For 2018-2019 portion of the backtest window,
  delisted names that left between 2018 and mid-2020 may still be
  partially missing. The substrate gap for 2021-2025 is closed; the
  2018-2020 gap is not, but is out-of-scope per the task brief
  ("Don't extend earlier than 2010-01-01" / "current 5-year window's
  gap").

## Provenance

- Fetch script: `scripts/fetch_missing_delisted.py`
- Provenance JSON: `data/processed/_data_provenance_delisted.json`
- Measurement re-runs: `multi_year_smoke_post_closure.{md,json}` and
  the eventual full 5-year output (paths recorded above).
- Runbook update: `docs/Core/execution_manual.md` §"Sourcing delisted
  / share-class names"
