---
task_id: T-2026-05-11-030
title: short_term_reversal_v1 3-rep re-measurement — 2022 zero-Sharpe is a metrics bug, not regime kill
date: 2026-05-12
outcome: PIPELINE_BUG_SURFACED
---

# T-030 — short_term_reversal_v1 3-rep re-measurement

## Brief

T-029 classified STR as "uniformly noisy" using T-020 trade logs.
The threshold-calibration audit had earlier flagged STR as the
closest-miss to t > 2 (t = +1.76, α = +3.39% annualized) and noted
a suspicious 2022 zero-Sharpe cell. Brief: run 3 reps × 5 years
isolated to disambiguate whether the 2022 zero was a deterministic
result (consistent across reps), genuine regime-conditional kill,
or a noise artifact.

## Setup

- 3 reps × 5 years × 1 edge (`short_term_reversal_v1`)
- Substrate-honest historical S&P 500 universe, `status='active'`
  inside `isolated()` context (full weight, not 0.25× soft-pause)
- `exact_edge_ids=[short_term_reversal_v1]`, `journal_mode=True`,
  `apply_journal_at_end=True`, `discover=False`
- 15-cell grid wall time ≈ 110 min (~7 min/cell)

## Results

| Year | Rep 1 Sharpe | Rep 2 Sharpe | Rep 3 Sharpe | md5 prefix |
|------|--------------|--------------|--------------|------------|
| 2021 | 0.357 | 0.357 | 0.357 | 357f8817 |
| 2022 | **0.000** | **0.000** | **0.000** | 2d6793fa |
| 2023 | 0.365 | 0.365 | 0.365 | bd67e3c1 |
| 2024 | 0.382 | 0.382 | 0.382 | 88d48a32 |
| 2025 | 0.303 | 0.303 | 0.303 | bb7adbb3 |

**Determinism: PERFECT across all 15 cells.** Every year's 3 reps
emit bitwise-identical trade-canon md5s. Noise hypothesis falsified.

Mean reported Sharpe = (0.357 + 0 + 0.365 + 0.382 + 0.303) / 5 = 0.281.

## The 2022 zero-Sharpe is a metrics-pipeline bug

The 2022 zero is reproducible and not noise — but it's also not
a real regime kill. Cross-referencing `performance_summary.json`
against the raw `portfolio_snapshots.csv` and `trades.csv` for
2022 rep 1 (`run_id=95138815-...`):

| Source | Starting | Ending | Net P&L |
|--------|----------|--------|---------|
| `performance_summary.json` | $100,000 | $100,000 | $0 (reported) |
| `portfolio_snapshots.csv` field 5 (`equity`) | $100,000 | $95,828 | -$4,172 |
| `trades.csv` exit-row pnl sum | — | — | -$3,072 |

The strategy fired 3,413 trade rows (602 closes), realized
-$3,072 in PnL, and ended the year at -4.17% — but the summary
reports flat $100K → $100K, net $0, Sharpe 0.000.

### Mechanism

1. `cockpit/logger.py:54` declares `SNAPSHOT_COLUMNS` as 9 columns.
2. `_append_to_csv` (line 146) appends row dicts as-is. The snap
   dicts passed in carry **more than 9 keys** — when `flush()`
   converts the buffer to a DataFrame and `to_csv(... header=False)`
   appends, each row writes **11 fields**.
3. The CSV header (line 112) was written with only 9 column names.
4. Result: every `portfolio_snapshots.csv` on disk has 11 data
   fields per row but a 9-column header. Verified across all 5
   years of T-030.
5. `cockpit/metrics.py:131` calls `pd.read_csv()` on this file.
   pandas mis-aligns: the 9 header names get assigned to fields
   [2..10] of each row, putting a **constant high-water-mark
   field** into the `equity` column slot.
6. In years where the strategy makes new equity highs above
   $100K (2021/2023/2024/2025), that HWM column happens to track
   the real equity, so metrics look correct.
7. In losing years (2022, where equity never exceeded $100K),
   the HWM column stays glued at $100K, equity returns are 0,
   Sharpe = 0.

### Cross-year confirmation (rep 1 only)

| Year | CSV field 5 (`equity`) first→last | pandas-parsed `equity` first→last |
|------|-----------------------------------|------------------------------------|
| 2021 | $100,000 → $109,031 | $100,000 → $109,031 (correct by coincidence) |
| 2022 | $100,000 → $95,828  | $100,000 → $100,000 (**WRONG — HWM stuck**) |
| 2023 | $100,000 → $108,301 | $100,000 → $108,301 (correct by coincidence) |
| 2024 | $100,000 → $109,285 | $100,000 → $109,285 (correct by coincidence) |
| 2025 | $100,000 → $107,719 | $100,000 → $107,719 (correct by coincidence) |

The mis-parse silently produces correct numbers in winning years
(because HWM == equity when equity advances) and wrong numbers in
losing years (where HWM diverges from real equity).

## Implications

1. **STR is not regime-killed in 2022.** Real 2022 return is
   approximately -4.17% (or -3.07% after using trades.csv exits),
   which is bull-conditional loss behavior for a long-biased
   reversal edge. T-029's "uniformly noisy" classification was
   built on T-020's reported zero — which is the same bug.

2. **The 0.281 mean Sharpe headline is wrong.** With the real
   2022 number, mean Sharpe is lower than 0.281 (because the true
   2022 figure is negative, not 0). The full 5-year true Sharpe
   profile is unknown until the metric pipeline is fixed.

3. **Bug scope is system-wide.** Every backtest that ever ran
   through `cockpit/logger.CockpitLogger` + `cockpit/metrics.
   PerformanceMetrics` is affected. The mis-parse is silent and
   only manifests as wrong numbers in losing years (or losing
   sub-periods). This rules into question all prior Sharpe
   headlines on bear-conditional or net-losing edges, and the
   in-bear-year cells of the 5-year matrix decomps.

4. **Determinism is intact.** This isn't a non-determinism issue
   — the bug is a writer/reader contract mismatch, not a race.

## Files

- `scripts/run_short_term_reversal_3rep.py` — 15-cell harness
- `data/measurements/short_term_reversal_3rep_2026_05_11/results.json`
- 15 backtests under `data/trade_logs/<run_id>/`

## NOT included in this task

- **Fix.** `cockpit/logger.py` and `cockpit/metrics.py` are
  cross-engine, observability-layer modules. Fixing the writer
  schema or the reader's field count check is a separate
  dispatch. T-030 surfaces the bug; the fix and the re-run of
  all prior measurements affected are dispatched separately.
- **Re-classification of STR.** The new Sharpe headline requires
  the fix first, then a re-run of T-029's factor decomp on the
  corrected trade panel.
- **Other affected measurements.** The same bug-class likely
  contaminated T-020, T-029, T-002 Arm 2 (substrate-honest
  multi-edge 5-year), and any other doc that quoted a Sharpe
  containing a bear-year cell.

## Next-step recommendations (out of T-030 scope)

1. **Bug fix** — modify `cockpit/logger.py:_append_to_csv` /
   `flush()` to filter the snap dict to `SNAPSHOT_COLUMNS` before
   building the DataFrame, OR widen `SNAPSHOT_COLUMNS` to match
   what's actually written. The latter preserves observability
   of the extra fields (HWM + turnover ratio).
2. **Pipeline guard** — add a single assert in `cockpit/metrics.py:
   PerformanceMetrics.__init__`: after `pd.read_csv()`, check the
   header field count matches the first data row's field count,
   raise loudly otherwise.
3. **Re-measure** — once fixed, re-run T-002 Arm 2 5-year matrix
   and T-029 factor decomp on the corrected panel. The 0.270
   "engines-first baseline" Sharpe is suspect by exactly this
   bug-class.
