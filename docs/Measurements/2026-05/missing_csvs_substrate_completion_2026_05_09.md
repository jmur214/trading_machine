# Missing CSVs — Substrate Completion Plan

**Status:** 2026-05-09 follow-on to the F6 COLLAPSES verdict. Identifies the exact set of S&P 500 names that were silently dropped from the universe-aware backtest (`use_historical_universe=true`) because their price CSVs are not on disk locally. The B1 verdict noted "26-54 missing names per year" — this doc enumerates them.

## Why this matters

The 2026-05-09 verdict measured mean Sharpe **0.5074** on the substrate-honest universe. Per the verdict report:

> "0.507 is an upper bound. 26-54 names per year were silently dropped because their CSV files don't exist locally — these are mostly delisted names (FRC, DISCA, ATVI confirmed). Delistings carry survivorship-bias signal in the OPPOSITE direction. The real substrate-honest Sharpe is < 0.507."

To resolve the upper bound, the missing names need to be backfilled. This doc enumerates what's missing and what's tractable to fix.

## Per-year missing-CSV counts (reconciles to verdict report's 26-54 range)

| Year | Hist union | CSV on disk | Missing | Of which: delisted |
|---:|---:|---:|---:|---:|
| 2021 | 525 | 471 | 54 | 38 |
| 2022 | 525 | 479 | 46 | 29 |
| 2023 | 523 | 489 | 34 | 17 |
| 2024 | 523 | 493 | 30 | 13 |
| 2025 | 524 | 498 | 26 | 9 |

Source: `pandas` against `data/universe/sp500_membership.parquet` filtered to `available_filter` against `data/processed/*_1d.csv`. Reproducible via the inline script in this commit.

## The 36 unique delisted names (the load-bearing fix)

Across the 2021-2025 union, there are 36 distinct tickers that:
- Were S&P 500 members during 2021-2025
- Had `included_until` set (i.e. left the index)
- Have no `_1d.csv` in `data/processed/`

These carry survivorship-bias signal — they are exactly the names a substrate-honest universe should include. Adding them would push the measured Sharpe down (delistings are typically losing trades).

| Ticker | Name | Delisted | Notable? |
|---|---|---|---|
| ABMD | Abiomed | 2022-12-22 | Acquired by J&J |
| ALXN | Alexion Pharmaceuticals | 2021-07-21 | Acquired by AstraZeneca |
| ANSS | Ansys | 2025-07-18 | Acquired by Synopsys |
| **ATVI** | **Activision Blizzard** | 2023-10-18 | Acquired by Microsoft (already in B1 verdict callout) |
| CERN | Cerner | 2022-06-08 | Acquired by Oracle |
| CMA | Comerica | 2024-06-24 | Bank merger |
| CTLT | Catalent | 2024-12-23 | Take-private |
| CTXS | Citrix Systems | 2022-10-03 | Take-private |
| CXO | Concho Resources | 2021-01-21 | Acquired by ConocoPhillips |
| DAY | Dayforce | 2026-02-09 | Take-private (post-window edge case) |
| DFS | Discover Financial | 2025-05-19 | Acquired by Capital One |
| **DISCA** | **Discovery, Inc.** | 2022-04-11 | Merged with Warner Media (already in B1 verdict callout) |
| DISCK | Discovery, Inc. | 2022-04-11 | Same merger as DISCA |
| DISH | Dish Network | 2023-06-20 | Merged with EchoStar |
| DRE | Duke Realty | 2022-10-03 | Acquired by Prologis |
| FBHS | Fortune Brands Home & Security | 2022-12-19 | Spinoff |
| FLIR | FLIR Systems | 2021-05-14 | Acquired by Teledyne |
| **FRC** | **First Republic Bank** | 2023-05-04 | **FAILURE — regional banking crisis** (already in B1 verdict callout) |
| GPS | Gap | 2022-02-03 | Removed (size) |
| HBI | Hanesbrands | 2021-12-20 | Removed (size) |
| HES | Hess Corporation | 2025-07-23 | Acquired by Chevron |
| HFC | HollyFrontier | 2021-06-04 | Merged into HF Sinclair |
| IPG | Interpublic Group | 2025-11-28 | Merger with Omnicom |
| JNPR | Juniper Networks | 2025-07-09 | Acquired by HPE |
| K | Kellanova | 2025-12-11 | Acquired by Mars |
| KSU | Kansas City Southern | 2021-12-14 | Acquired by Canadian Pacific |
| MRO | Marathon Oil | 2024-11-26 | Acquired by ConocoPhillips |
| NLSN | Nielsen Holdings | 2022-10-12 | Take-private |
| PBCT | People's United Financial | 2022-04-04 | Acquired by M&T |
| PXD | Pioneer Natural Resources | 2024-05-08 | Acquired by ExxonMobil |
| **SIVB** | **SVB Financial Group** | 2023-03-15 | **FAILURE — second-largest US bank failure** |
| TIF | Tiffany & Co | 2021-01-07 | Acquired by LVMH |
| **TWTR** | **Twitter** | 2022-11-01 | Take-private (Musk) |
| VAR | Varian Medical Systems | 2021-04-20 | Acquired by Siemens |
| WBA | Walgreens Boots Alliance | 2025-08-28 | Take-private |
| XLNX | Xilinx | 2022-02-15 | Acquired by AMD |

**Bold**: catastrophic / outlier-impact names where holding into the event would have been a meaningful loss. SIVB and FRC are the most consequential — both were failures in the 2023 regional banking crisis. If the strategy held them on a substrate-honest universe, those would have been outsized losing trades.

## The 17 still-active-no-CSV names (low-priority)

These are S&P 500 members per the membership table but have no CSV. Most are:
- Renamings / share-class variants the strategy doesn't trade (BF.B, BRK.B)
- Older entries / data-quality issues (CCR, CDAY, COG, DLPH, FLT, FSR, HRS, JEC, JOYG, KORS, LUK, RE, TSO, WLP, WLTW)

These are low-priority because they're not active-and-tradable in their current form. Skip unless the audit specifically needs them.

## Recommendation

After C-collapses-1 audit completes, run a targeted backfill:

```bash
.venv/bin/python scripts/fetch_universe.py \
  --tickers ABMD,ALXN,ANSS,ATVI,CERN,CMA,CTLT,CTXS,CXO,DFS,DISCA,DISCK,DISH,DRE,FBHS,FLIR,FRC,GPS,HBI,HES,HFC,IPG,JNPR,K,KSU,MRO,NLSN,PBCT,PXD,SIVB,TIF,TWTR,VAR,WBA,XLNX \
  --period max
```

(Verify the actual `--tickers` arg name supported by `scripts/fetch_universe.py` — this is a sketch.)

Then re-run multi-year measurement on substrate-honest universe with the now-complete CSV cache. Expected outcome: Sharpe drops further from 0.507 (delisted-stock holding losses materialize), confirming the upper-bound interpretation.

## Specific 2023 case to verify

The 2023 hold (-0.095 within noise band) is the load-bearing anomaly. Two names delisted IN 2023 are missing from the substrate:
- **FRC** (delisted 2023-05-04) — banking failure
- **SIVB** (delisted 2023-03-15) — banking failure

If the strategy was loading regional banks in early 2023 and would have held FRC/SIVB through the failures, the 2023 universe-aware Sharpe of 1.292 would also drop. The 2023 hold may not actually hold once these are filled in.

## Honest caveats

- 36 names sounds tractable but yfinance + delisted names is a known data-quality area. Some tickers may not be fetchable post-delist; need fallback (Stooq, polygon, etc.).
- The "DAY" entry (delisted 2026-02-09) is post-window for the 2025 measurement — exclude.
- Adding these names creates a substrate that's 539-561 names instead of 476-503 — a ~12% expansion. Wall-time per multi-year run scales with universe size, so the rerun will be ~85-115 min instead of 70-100 min.
- Honest about this measurement's status: it's an analysis pass, not a ship gate. The C-collapses-1 audit is the measurement that matters; this is a "complete the substrate" follow-on for whichever path the audit recommends.
