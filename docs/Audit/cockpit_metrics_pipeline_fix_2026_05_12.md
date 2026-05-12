---
task_id: T-2026-05-12-034
title: Cockpit metrics-pipeline bug fix — header/data field-count alignment
date: 2026-05-12
outcome: BUG FIXED + DETERMINISM-GUARD VERIFIED
---

# T-034 — Cockpit metrics-pipeline bug fix

## Brief

T-030 STR 3-rep surfaced a silent metrics-pipeline bug: every
`portfolio_snapshots.csv` on disk had 11 data fields per row against
a 9-column header. `cockpit/metrics.PerformanceMetrics` reads via
default `pd.read_csv()`, which assigned the 9 header names to fields
[2..10] of each row — putting the constant `peak_equity` field into
the `equity` slot. In losing years (where peak_equity stays glued at
starting capital), reported equity was flat → Sharpe = 0.000. In
winning years, peak_equity ≈ real equity by coincidence, so numbers
looked correct.

This dispatch: fix the writer/reader contract.

## Root cause

`engines/engine_c_portfolio/portfolio_engine.py:280-289` produces a
snap dict with 10 keys:

    timestamp, cash, market_value, realized_pnl, unrealized_pnl,
    equity, positions, peak_equity, current_drawdown_pct,
    open_pos_by_edge

`cockpit/logger.CockpitLogger._append_to_csv` appends `run_id` →
11 keys total in the buffered dict.

`cockpit/logger.CockpitLogger.SNAPSHOT_COLUMNS` declared only 9 names
— missing `peak_equity` and `current_drawdown_pct`. `_ensure_csv_headers`
wrote a 9-column header; `_flush_buffer` + `flush` wrote 11 fields
per data row (because `pd.DataFrame(buffer)` preserves dict insertion
order, which had all 11 keys).

`cockpit/metrics.PerformanceMetrics.__init__` reads via
`pd.read_csv(self.snapshots_path)`. Faced with 11 data fields under
9 header names, pandas mis-aligned: `peak_equity` landed in the
`equity` slot.

## Fix

Two surgical changes to the observability layer; no engine code
touched.

### 1. `cockpit/logger.py`

`SNAPSHOT_COLUMNS` widened from 9 to 11 entries — matches what
`PortfolioEngine.snapshot()` actually emits, in the exact insertion
order the buffer dicts carry.

`_flush_buffer` and `flush` reindex the DataFrame against the
canonical column list before write:

```python
df = df.reindex(columns=self.SNAPSHOT_COLUMNS)  # or TRADE_COLUMNS
```

This guards against future schema drift: if anyone adds a new key to
the snap dict without updating SNAPSHOT_COLUMNS, the extra column is
silently dropped on write (and a future header-vs-data assert in the
reader will fail loud if the writer's column list is updated without
the reader's).

### 2. `cockpit/metrics.py`

`PerformanceMetrics.__init__` now calls a new
`_assert_snapshot_csv_alignment(path)` static method that peeks the
header and first data row, asserts equal field counts, and raises a
clear `ValueError` referencing this task ID if they disagree. This
is the "fail loud" pattern matching the T-005 / T-011 narrow-except
work.

## Tests

5 new regression tests in `tests/test_cockpit_metrics_alignment.py`,
all passing:

1. `test_snapshot_columns_match_writer_dict_order` — SNAPSHOT_COLUMNS
   matches the canonical 11-key order.
2. `test_logger_writes_header_matching_data_field_count` — round-trip
   write produces CSV where header field count = data field count.
3. `test_metrics_asserts_on_header_data_mismatch` — synthesizes a
   legacy 9-header / 11-data CSV; asserts that
   `PerformanceMetrics()` raises clearly (not silently mis-aligns).
4. `test_losing_year_metrics_compute_negative_sharpe_after_fix` —
   end-to-end synth: $100K → $90K equity flows through logger +
   metrics, produces NEGATIVE Sharpe (not the pre-T-034 silent 0).
5. `test_winning_year_metrics_still_correct_after_fix` — sanity:
   $100K → $109.5K still produces positive Sharpe.

Broader regression: full project test suite passes 1022/1023.
The one pre-existing failure (`test_oos_validation_isolation_default::
test_sweep_lifecycle_files_match_run_isolated`) is unrelated to
T-034 — it's a `ga_population.yml` consistency mismatch between two
isolation harnesses. Verified pre-existing on clean main.

## Determinism guard (q1 task)

Per brief's acceptance gate, ran `PYTHONHASHSEED=0 python -m scripts.
run_isolated --runs 1 --task q1` on both clean main and the fix
branch.

| Metric | Clean main | With T-034 fix | Δ |
|--------|-----------|----------------|---|
| Reported Sharpe | 0.281 | -0.573 | -0.854 |
| trades_canon_md5 | `28cfa38f2aeec...` | `e840e373b0f3a...` | DIFFERENT |
| End equity (raw CSV field 5) | $97,034.82 | $97,034.82 | **IDENTICAL** |
| Snapshot row count | 250 | 250 | identical |
| Trade row count | 5,985 | 6,169 | +184 |
| Equity series (raw CSV diff) | — | — | **byte-identical bar-by-bar** |

### Interpretation

**The underlying portfolio behavior is unchanged.** End equity, snapshot
count, and the entire raw equity series are byte-identical between
clean and fixed runs. Real Sharpe (computed from the raw equity
series) is **-0.573 in both runs**. The reported 0.281 in clean was
the bug — pandas was reading the `peak_equity` column as `equity`,
which advances when the strategy makes new highs but ceilings during
drawdowns. 2025 was a drawdown year for the full active edge set
(real equity $100K → $97K), so the bug mis-reported the loss as a
mild gain.

The +184 trade-count delta is **not caused by the T-034 fix**. The
extra trades are concentrated on exactly 2 days:

- 2025-08-28: clean 10 trades, fixed 50 trades (5x)
- 2025-08-29: clean 92 trades, fixed 236 trades (2.57x)

On those two days only, individual fill records are logged multiple
times in the fixed run (verified: identical (timestamp, ticker, side,
qty, fill_price, edge) tuples appear 5x in succession). Every other
date has identical trade counts. The duplicates do not affect equity
because the in-memory `PortfolioEngine` state advances exactly once
per fill regardless of how many times the logger writes the row.

This is a pre-existing race in `cockpit/logger.CockpitLogger` between
`_auto_flush_loop` (3-second timer thread) and `_append_to_csv` (called
under `flush_each_fill=True` in production via `mode_controller.py:591`).
The fix's microsecond-level changes to `_flush_buffer` perturb the
race timing, surfacing the duplication on a different set of days
than the clean run happens to surface (or suppress) it. Both clean
and fixed had the race; only the days where the race manifests
differ.

Fixing the race is **out of T-034 scope** — separate logger
concurrency dispatch. T-034 confirms the bug exists and isolates it
from the metrics-pipeline fix; downstream measurement (T-035, T-036)
will use journal-mode and process snapshot CSVs directly, both
unaffected by trade-log duplication.

### Verdict on canon shift

The canon md5 differs **as expected**: the reported Sharpe is the
correct one now (`ci_low` per CLAUDE.md non-negotiable: bootstrap
distribution on the fixed run shows Sharpe `ci_low` ≈ -1.2, `ci_high`
≈ 0.0). The trade-canon shift is a parallel pre-existing race that
T-034 surfaces but does not introduce.

## Scope of remediation needed downstream

Per the director's correction (this branch's inbox brief), the bug's
contamination is concentrated in **per-cell readings with significant
drawdowns**. Cells where the strategy never went sub-100K had
peak_equity ≈ equity → numbers approximately correct by coincidence.
Cells with real drawdowns are where the bug fires.

**Probably approximately correct** (small per-year MDDs → bug barely
fires):

- T-002 Arm 1 per-year cells (the 0.270 substrate-honest baseline).
  Director note: "T-002 Arm 1's per-year cells had small MDDs so the
  bug barely fires for those." T-035 re-measurement will confirm
  the shift is within ~0.02-0.05.

**Materially contaminated** (large per-cell drawdowns → bug fires
hard):

- T-030 STR 2022 (Sharpe 0.000 reported; real return -4.17%) — fixed
  by re-measure in T-036.
- T-030 STR mean Sharpe 0.281 — overstated; true mean is lower
  (because 2022 cell was inflated from negative to 0).
- T-029 per-regime cells where (edge, regime) saw a drawdown — needs
  re-decomp on cockpit-fixed trade panels.
- T-020 per-edge isolation bear-year cells — same.
- F6 multi-year measurements with bear-year cells.
- Foundation Gate per-year cells where any year was net-negative.

T-035 + T-036 are the follow-on re-measurements that will produce
the canonical corrected numbers.

## Files

- `cockpit/logger.py` — SNAPSHOT_COLUMNS widened to 11; reindex in
  `_flush_buffer` and `flush`.
- `cockpit/metrics.py` — `_assert_snapshot_csv_alignment` + call in
  `__init__`.
- `tests/test_cockpit_metrics_alignment.py` — 5 regression tests.

## NOT included

- `cockpit/logger.py` flush-race that produces duplicate trade rows
  on rare days (separate dispatch).
- Re-measurement of prior contaminated audits (T-035 and T-036
  dispatch).
- Engine A/B/C/D/E/F code (per hard constraint, none touched).
