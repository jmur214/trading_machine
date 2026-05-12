# Spec — T-2026-05-12-040: Trade-log storage migration (CSV → Parquet) + retention policy

**Date drafted:** 2026-05-12 (director-side, ~45 min)
**Status:** SPEC for approval. **Touches backtest_controller writer path (3+ engine callers via Engine A/D/F) → requires explicit user propose-first sign-off per CLAUDE.md before dispatch.**
**Will be executed by:** Agent A or B once approved (~6-8 hr).
**Sequencing:** sits AFTER A's current chain (T-034/T-035/T-036) lands. Do not interleave with measurement work — the writer migration shifts canon md5s.
**Output:** Parquet writer + retention manifest enforcement + DuckDB query helper + tests + audit doc + canon rebaseline.

---

## Why now

Three disk-fill crises in 48 hr (2026-05-10, 2026-05-11, 2026-05-12). Phase 1 surgical recovery on 2026-05-12 freed 4.5 GB (2.6 GB duplicates to Trash + 1.9 GB gzip-compression) — but did NOT change the underlying write rate. Each substrate-arm measurement still writes ~5.6 GB of CSVs across 3 worktrees. Another 48 hr of measurements = another crisis.

Three structural pathologies in the current trade-log writer:

1. **CSV format is wrong for this workload.** Trades CSV is ~18 MB per run × 250+ runs = 5+ GB. Parquet on same data: ~720 KB per run after gzip; ~1.5-2 MB native Parquet without gzip. **5-10× smaller** with column-typed schema, faster scan, support for predicate pushdown.

2. **Per-run directory structure makes aggregate queries expensive.** A simple "mean Sharpe by year across all reps" has to crawl 300+ directories. Parquet partitioning (`arc/year/rep`) collapses this to a single DuckDB scan.

3. **Defensive duplicate write path is dead code.** `backtester/backtest_controller.py:929-944` writes `trades_<uuid>.csv` alongside `trades.csv` "for metrics safety" — empirically a no-op (filter-by-run_id doesn't remove anything because each run already has its own dir). Phase 1 audit confirmed 147 of 308 runs had byte-identical duplicate pairs. The bug is the existence of the write, not the contents.

The cockpit metrics-pipeline bug (T-030 → T-034) just landed on main with a header/data-field-count assert. That's a defensive fix, not a structural one. T-040 is the structural fix — eliminate the write-path bug AND the storage-format bug in one cohesive migration.

---

## What

Four file/code changes plus a one-time canon-rebaseline event.

### 1. Writer migration (CSV → Parquet)

`cockpit/logger.py` (will be `core/observability/portfolio_snapshot_logger.py` post-T-039, but T-040 sequences AFTER T-039 so writes are in the new location):

- `_flush_buffer`: write Parquet instead of CSV. `pd.DataFrame.to_parquet(path, engine='pyarrow', compression='zstd')`. Append-mode for Parquet uses `pyarrow.parquet.ParquetWriter` with row-group flushing.
- Schema: explicit `pyarrow.schema` definition for SNAPSHOT_COLUMNS and TRADE_COLUMNS (timestamp as `pa.timestamp('us')`, equity/cash as `pa.float64`, etc.). Replaces the implicit dtype inference that caused the T-030 mis-alignment bug class.
- File paths: `trades.parquet` and `portfolio_snapshots.parquet` instead of `trades.csv` and `portfolio_snapshots.csv`.

### 2. Defensive duplicate write removal

`backtester/backtest_controller.py:929-944` — the `df_snap.to_csv(snapshots_path_for_metrics, ...)` + `df_tr.to_csv(trades_path_for_metrics, ...)` block. Delete it entirely. Audit at `docs/Audit/cockpit_metrics_pipeline_fix_2026_05_12.md` (just landed) already documents that this block is dead defensive code. Deletion is pure cleanup.

### 3. Retention manifest enforcement

The Phase 1 cleanup wrote `data/trade_logs/_retain_uncompressed.txt` (181 pinned audit-cited run_ids). T-040 promotes this to a first-class concept:

- Rename to `data/trade_logs/_pinned_runs.txt` (clearer naming).
- New helper at `core/observability/retention.py`:
  - `is_pinned(run_id: str) -> bool` — checks the manifest
  - `apply_retention_policy(trade_logs_dir: str, days: int = 7) -> RetentionReport` — for runs > N days old AND not pinned, compress trades.parquet (already small, but compressing for archive tier) and emit a report
- Scheduled retention pass (manual for now, cron in future): `python -m scripts.apply_retention_policy --days 7 --dry-run`

### 4. DuckDB query helper

New file `core/observability/query.py`:

```python
def query_trade_logs(
    sql: str,
    trade_logs_dir: str = "data/trade_logs",
    pattern: str = "**/trades.parquet",
) -> pd.DataFrame:
    """Run a SQL query across all trade_logs Parquet files as one virtual table.

    Example: query_trade_logs("SELECT run_id, AVG(pnl) FROM trades GROUP BY run_id")
    """
    import duckdb
    conn = duckdb.connect()
    conn.execute(f"CREATE VIEW trades AS SELECT * FROM read_parquet('{trade_logs_dir}/{pattern}')")
    return conn.execute(sql).df()
```

Pairs with snapshots; same shape, different view.

### 5. Backward-readability

Existing 56 uncompressed `trades.csv` + 253 `trades.csv.gz` files stay readable forever. `PerformanceMetrics.__init__` already reads both via `pd.read_csv` (gzip auto-detected by extension). Add a `_open_trades_file()` helper that handles both `.parquet` and `.csv[.gz]`:

```python
def _load_trades(path: str) -> pd.DataFrame:
    if path.endswith(".parquet"):
        return pd.read_parquet(path)
    elif path.endswith(".csv.gz") or path.endswith(".csv"):
        return pd.read_csv(path)
    else:
        raise ValueError(f"unknown trade-log format: {path}")
```

PerformanceMetrics dispatches to this. **Historical reads continue to work; no archive migration required.**

### 6. requirements.txt addition

Add `duckdb>=0.10.0` and confirm `pyarrow` is present (it is, via pandas Parquet dependency).

---

## Why Parquet specifically, not SQLite or another database

Decision rationale, documented for the audit doc:

- **Postgres/MySQL**: wrong shape. Trade logs are write-once-read-many immutable artifacts. Adding an RDBMS adds an ops surface (postgres process, schema migrations, backup ops) for a workload that doesn't need transactional writes.
- **SQLite**: closer fit, but each backtest writing to a SQLite file requires write-lock coordination across the (cockpit_logger, run multiple in parallel) case. Worktree-isolated runs would each need their own SQLite, which is exactly the per-file structure we already have. Parquet wins on size + speed without the locking nuance.
- **Parquet + DuckDB**: write per-run as immutable Parquet; query as virtual table at read time. Workload-perfect: write rate is bounded (one file per run), read rate is aggregate (DuckDB scans 300+ files faster than pandas can scan 1 CSV).

---

## Acceptance

1. **Writer migration:**
   - `cockpit/logger.py` (or post-T-039 location) writes `.parquet` not `.csv` for `trades` and `portfolio_snapshots`.
   - Schema explicitly typed via `pyarrow.schema`; no dtype inference.
   - Existing `_assert_snapshot_csv_alignment` is REPLACED by Parquet schema enforcement (Parquet writers enforce schema; mismatched fields fail loud at write time, not silent on read).

2. **Defensive duplicate write removed:**
   - `backtester/backtest_controller.py:929-944` block deleted.
   - One-line audit-doc note explaining why (Phase 1 finding).

3. **Retention manifest:**
   - `_retain_uncompressed.txt` → `_pinned_runs.txt`.
   - `core/observability/retention.py` exists with `is_pinned()` + `apply_retention_policy()`.
   - `scripts/apply_retention_policy.py` CLI wrapper, `--dry-run` default.

4. **DuckDB query helper:**
   - `core/observability/query.py` exists with `query_trade_logs()`.
   - Returns identical Sharpe/Sortino to `PerformanceMetrics` on a known run (regression test).

5. **Backward read:**
   - `PerformanceMetrics` reads both `.parquet` and `.csv[.gz]` via `_load_trades()`.
   - All existing 56 + 253 historical files load correctly post-migration.

6. **Disk write rate:**
   - New run's `trades.parquet` ≤ 1/5th of the equivalent CSV. (~18 MB CSV → ≤ 4 MB Parquet at zstd compression.)
   - Documented in audit doc with a measured comparison on one canonical run.

7. **Determinism canon rebaseline:**
   - `python -m scripts.run_isolated --runs 3 --task q1` post-migration produces 3 bitwise-identical Sharpes (determinism preserved within new format).
   - Canon md5 will SHIFT (Parquet bytes ≠ CSV bytes). Document the shift in audit doc with explicit note: "T-040 is a substrate-lock event; all canon md5s after this point are Parquet-format canon. Pre-T-040 md5s remain valid for historical comparison."
   - Update `forward_plan.md` + `health_check.md` with the new canon entry.

8. **Tests** in `tests/test_storage_parquet.py`:
   - `test_writer_emits_parquet_schema` — new run produces .parquet, not .csv
   - `test_parquet_round_trip_preserves_sharpe` — PerformanceMetrics on .parquet returns same Sharpe as on equivalent .csv (within float epsilon)
   - `test_backward_read_csv_gz` — historical gzipped .csv still loadable
   - `test_duckdb_query_parity` — DuckDB SELECT mean Sharpe matches per-run PerformanceMetrics mean
   - `test_retention_pinned_skip` — apply_retention_policy skips manifest entries
   - `test_retention_dry_run_no_writes` — --dry-run does not modify any files

9. **Audit doc** at `docs/Audit/storage_parquet_migration_2026_05_12.md`:
   - Pre/post disk-rate comparison (one run measured)
   - Canon md5 shift documented (substrate-lock event)
   - DuckDB query examples (3-4 useful aggregate queries)
   - Backward-read evidence (one historical .csv + one historical .csv.gz both loaded)
   - Forward-look: T-040b candidate to compress aged Parquets to zstd-22 (max compression) after 30 days

10. **CLAUDE.md update** under non-negotiable rules:
    > **Trade-log storage is Parquet, not CSV.** Per-run `trades.parquet` + `portfolio_snapshots.parquet` are immutable artifacts. Use `core/observability/query.py:query_trade_logs()` for aggregate queries (DuckDB SQL across all runs). Manual CSV writes to `data/trade_logs/` are forbidden — they break the canon contract. Historical CSV/gzip files stay readable forever via `PerformanceMetrics`.

11. **Branch:** `feature/storage-parquet-migration`. Push only; director merges + pushes after review.

---

## Hard constraints

- DO NOT modify engine code (Engine A/B/C/D/E/F). Pure observability/storage refactor.
- DO NOT delete any historical CSV or gzip files. Backward-read forever.
- DO NOT bundle this with T-039 (observability relocation). T-039 lands first; T-040 picks up the moved files at the new path.
- DO NOT change SNAPSHOT_COLUMNS or TRADE_COLUMNS schema (field sets stay identical; only serialization changes).
- Per CLAUDE.md: 3+ engine refactor (writer is called from backtest_controller, mode_controller, wfo, train_signal_gate, run_benchmark) — **propose-first applies**. Director must have explicit user approval before dispatching this brief to an agent.
- Canon-rebaseline is a one-time event. Document it loudly in audit doc + forward_plan.md.

---

## Time budget

6-8 hr total: ~2 hr writer migration + schema typing, ~30 min defensive dup removal, ~1 hr DuckDB helper + retention helper, ~30 min CLAUDE.md update, ~2 hr tests, ~1 hr canon rebaseline + audit doc, plus debugging buffer.

---

## Open questions for the implementing agent (surface in audit doc, not block)

1. **Compression level: zstd-3 (default) or zstd-9 (slower write, smaller files)?** Recommend zstd-3 for hot writes, T-040b follow-up for zstd-22 archive pass on aged Parquets (>30 days). Document.

2. **Should `trades.parquet` be partitioned within-file (one partition per ticker)?** Probably not — within-run partitioning adds write overhead for runs with few trades. Single-file-per-run is the right granularity. Document.

3. **Snapshot frequency: per-bar OR per-event?** Currently per-bar. Parquet is efficient either way, but per-event (only on position changes) would shrink snapshots by ~95% for typical runs. RECOMMEND NO CHANGE — per-bar is needed for equity-curve continuity and the test base expects it. Note for T-040b if dimensionality becomes a bottleneck.

4. **DuckDB lazy install or eager require?** Add `duckdb>=0.10.0` to requirements.txt eagerly; if user doesn't want it, they don't import `core.observability.query`. Cleaner than try/except dispatch.

5. **Should `apply_retention_policy.py` move aged Parquets to a sub-directory (`data/trade_logs/_archive/`) or stay in-place?** RECOMMEND in-place + a `.archived` marker file. Easier rollback. Sub-directory adds path-rewriting complexity. Document.

---

## Forward-look (T-040b + T-040c candidates)

After T-040 lands:

- **T-040b**: aged-Parquet zstd-22 compression pass (~2 hr). Runs daily via cron, archives Parquets > 30 days old. Expected additional ~3× compression on already-zstd-3 files.
- **T-040c**: BLAS-portable Parquet canon (~4 hr). Ensures cross-machine determinism for cloud-substrate work. Defers; only needed when cloud measurement campaigns spin up.

---

## Director note

This spec is **propose-first per CLAUDE.md** because the writer migration touches files called from 5+ caller sites across Engine A's mode_controller, Engine D's wfo.py, the backtester, scripts, and dashboard_v2. Plus the canon-rebaseline event affects every future measurement. Per the same CLAUDE.md non-negotiable, "changes spanning 3+ engines" requires explicit user approval before dispatch.

Recommended sequencing:
1. T-034 + T-035 + T-036 + T-038 (current chains) land.
2. T-039 observability relocation lands (moves cockpit/logger.py → core/observability/portfolio_snapshot_logger.py).
3. T-040 picks up files at the new path; spec is at canonical location.

If T-040 is dispatched before T-039, agent edits the files at cockpit/ instead — works but creates merge-conflict surface with T-039.
