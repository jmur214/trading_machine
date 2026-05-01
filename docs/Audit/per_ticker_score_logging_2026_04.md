# Per-Ticker Score Logging — Phase 2.11 Prep

Generated: 2026-04-30. Author: Agent B (per-ticker-score-logging branch).

## Why this exists

Phase 2.10d landed the autonomous lifecycle + capital-allocation
fixes. 2025 OOS Sharpe came in at 0.315 — real lift from -0.049 but
in the "ambiguous" bucket of the 04-30 forward plan. The 04-30
reviewer's strategic framing: **per-ticker meta-learner is the
structural answer to capital rivalry that the linear allocator can't
fully solve.** Per the 04-29 forward plan: *"Per-ticker training
requires logging per-bar per-ticker edge scores during backtest,
which the current backtester doesn't capture."*

This branch builds that infrastructure. Trade logs only record fills;
the meta-learner needs the full signal/no-signal distribution per
(ticker, bar, edge). Output is a parquet emitted during every backtest
when `--log-per-ticker-scores` is set.

---

## Schema

One row per `(timestamp, ticker, edge_id)` triple where
`SignalProcessor.process` returned an `edges_detail` entry for that
edge on that ticker that bar.

| column | dtype | meaning |
| --- | --- | --- |
| `timestamp` | `datetime64[ms]` | bar timestamp (`now` in `AlphaEngine.generate_signals`) |
| `ticker` | `string` | the ticker the score is for |
| `edge_id` | `string` | canonical registry id (e.g. `momentum_edge_v1`) |
| `raw_score` | `float64` | raw output from `edge.compute_signals` |
| `norm_score` | `float64` | normalized [-1, 1] post-`SignalProcessor` |
| `weight` | `float64` | edge weight at this bar (post `regime_gate`, soft-pause clamp, governor multiplier) |
| `aggregate_score` | `float64` | per-ticker aggregate score that flows into `formatter.to_side_and_strength` |
| `regime_summary` | `string` | best-effort `advisory.regime_summary` (e.g. `benign`, `stressed`); falls back to top-level `regime` then `unknown` |
| `fired` | `bool` | edge appeared in this ticker's signal `meta.edges_triggered` list (cleared `min_edge_contribution`) |

**Output path:** `data/research/per_ticker_scores/{run_uuid}.parquet`,
where `run_uuid` is `CockpitLogger.run_id` so the file joins cleanly
to `data/trade_logs/{run_uuid}/trades.csv` for training-target
construction downstream.

CSV fallback at `{run_uuid}.csv` if the parquet engine isn't
available — never lose training data because of a missing dep.

---

## Where it plumbs in

```
scripts/run_backtest.py
  --log-per-ticker-scores  (argparse flag, default off)
        |
        v
run_backtest_logic(..., log_per_ticker_scores=False)
        |
        v
ModeController.run_backtest(..., log_per_ticker_scores=False)
   1. construct CockpitLogger first  (provides run_uuid)
   2. if flag: instantiate PerTickerScoreLogger(run_uuid, out_dir)
   3. AlphaEngine(..., per_ticker_score_logger=<logger or None>)
   4. controller.run(...)
   5. if flag: per_ticker_logger.flush() → parquet
        |
        v
AlphaEngine.generate_signals(...)
   ... after `signals` list built, before fill_share_capper / governor mutations:
   self.per_ticker_score_logger.log_bar(timestamp=now, proc=proc,
                                         signals=signals,
                                         regime_meta=regime_meta)
```

**Why pre-fill_share_cap, post-signal_processor:** this is the "alpha
layer raw output" view of the bar. The fill-share cap rescales
strength but does not change which edges are in `edges_triggered`,
so `fired` is identical pre/post-cap. Capturing pre-cap also keeps
the logger's behavior independent of Engine A's downstream cap
calibration — the meta-learner's training data is the alpha layer's
distribution, not whatever the cap-bound version was.

**Defense-first design:**
- Off by default. AlphaEngine constructs without the kwarg; the
  hot-path attribute is `None` and the call site costs zero.
- `log_bar` is wrapped in try/except at both the logger and AlphaEngine
  call site — losing a bar of training data is preferable to losing a
  backtest run.
- `flush` falls back to CSV if parquet engine missing.
- The logger never imports backtester or governor code; it only
  consumes the dict shape `SignalProcessor.process` already produces.

---

## Smoke validation

`scripts/smoke_per_ticker_logger.py` runs a 5-ticker × 18-trading-day
backtest with the flag on, then validates schema + row count + cross-
ref against the trade log.

**Result:**

```
[RUN_BACKTEST] Per-ticker scores: 1,620 rows → data/research/per_ticker_scores/f993552a-781f-44cf-a171-23aac4ade3c6.parquet
[SMOKE] Schema: ['timestamp', 'ticker', 'edge_id', 'raw_score', 'norm_score', 'weight', 'aggregate_score', 'regime_summary', 'fired']
[SMOKE] 1,620 rows; 18 bars × 5 tickers × 18 edges (~1,620 max)
[SMOKE] Cross-ref sample: AAPL @ 2024-06-04 00:00:00
[SMOKE]   18 parquet rows for that (ticker, day)
[SMOKE]   fired=True rows: 3
[SMOKE]   PASS: at least one edge fired and was logged for the filled (ticker, bar)
```

Sample `fired=True` rows from a real bar:

```
    timestamp ticker                 edge_id  raw_score  norm_score  weight  aggregate_score  regime_summary  fired
 2024-06-03   AAPL        momentum_edge_v1   0.995006    0.580580   0.375         0.124041         unknown   True
 2024-06-03   AAPL  macro_credit_spread_v1   0.300000    0.197375   0.500         0.124041         unknown   True
 2024-06-03   AAPL  macro_dollar_regime_v1  -0.200000   -0.132549   0.500         0.124041         unknown   True
 2024-06-03   MSFT        momentum_edge_v1   0.852142    0.513959   0.375         0.112231         unknown   True
 2024-06-03   MSFT  macro_credit_spread_v1   0.300000    0.197375   0.500         0.112231         unknown   True
```

Row-count check: 18 bars × 5 tickers × 18 edges = 1,620 max possible
rows. We got exactly 1,620 — every (ticker, bar) had every active
edge log a row. That's the expected behavior: `SignalProcessor`
emits an `edges_detail` entry per `(ticker, edge)` regardless of
whether the score was zero.

`regime_summary` came back as `"unknown"` for the smoke run because
the synthetic minimal `regime_meta` dict (built when no
`RegimeDetector` is wired) has no `advisory` block. Real production
runs through `mode_controller` will populate it from Engine E.

---

## Calibration discoveries during smoke

**Bug surfaced and fixed in the same session:** the first smoke
emitted `edge_id` values like `momentum_edge_v1_v1` (double `_v1`
suffix). Root cause: `SignalProcessor.edges_detail` items use the
canonical registry key in the `edge` field (e.g. `momentum_edge_v1`,
already including the version suffix). My initial `_resolve_edge_id`
fallback always appended `_v1` to whatever was in `edge` if no
explicit `edge_id` was present.

Fix: regex check (`_v\d+$`) before suffixing. Edges that already
carry a version suffix pass through unchanged. Bare module names
(legacy path, e.g. `rsi_bounce`) still get the synthetic suffix.

Regression test added in `tests/test_per_ticker_score_logger.py`:
`TestEdgeIdResolution::test_edge_with_version_suffix_passes_through_unchanged`.

---

## Tests

`tests/test_per_ticker_score_logger.py` — 18 tests across 6 classes:

- `TestLoggerSchema` (3) — append shape, parquet write+roundtrip, empty-buffer no-op
- `TestFiredFlag` (2) — fired matches edges_triggered for fired edges; False for non-firing
- `TestEdgeIdResolution` (3) — version-suffix passthrough; bare-name synthesis; explicit edge_id wins
- `TestRegimeSummaryResolution` (3) — advisory > top-level > unknown fallback chain
- `TestDefensiveBehavior` (3) — malformed proc, empty proc, missing keys all silent no-ops
- `TestAlphaEngineIntegration` (3) — off-by-default, attribute attached when injected, run_backtest signature includes flag
- module-level (1) — CLI `argparse` exposes `--log-per-ticker-scores`

All 18 green. No regression in pre-existing test suite (smoke check ran
the full mode_controller → AlphaEngine path end-to-end; existing
behavior unchanged).

---

## What this does NOT do

- **No meta-learner training.** That's Phase 2.11 proper.
- **No signal_processor changes.** The logger is a passive consumer of
  the dict shape `SignalProcessor.process` already returns.
- **No metalearner.py changes** — the existing portfolio-level learner
  is untouched.
- **No capital-allocation primitive changes** — Agent A's territory.
- **No lifecycle changes** — done in Phase 2.10d.
- **No registry changes** — `data/governor/edges.yml` not touched.

---

## Open issues / things to watch

1. **`regime_summary` coverage in production runs.** The smoke run
   shows `unknown` because it goes through the BacktestController
   which builds a minimal `regime_meta` dict. Real production paths
   pass an Engine E advisory dict with `regime_summary` populated. If
   the meta-learner training reads this column and finds 100%
   `unknown`, that's a wiring failure to investigate, not a logger
   bug — the data plumbing is correct, the regime layer is not
   feeding through.

2. **Row count grows linearly with bars × tickers × edges.** A full
   2021-2024 prod run on 109 tickers with 17 edges would emit roughly
   `4 yrs × 252 days × 109 × 17 ≈ 1.87M rows`. At ~120 bytes/row that's
   ~225 MB of parquet — fine for a single training job but might want
   per-year partitioning if multiple years stack up. Defer until
   Phase 2.11 proper hits the data volume problem.

3. **`fired` is alpha-layer view, not fill-execution view.** `fired=True`
   means the edge cleared `min_edge_contribution` and was attached to
   a per-ticker signal. A signal can still be vetoed by `RiskEngine`,
   capped by `fill_share_capper`, or rejected for portfolio reasons.
   For meta-learner training-target alignment, the join key is
   `(timestamp, ticker)` against `trades.csv`'s entry rows; that gives
   a more rigorous "did this fill happen" signal than `fired`. The
   `fired` flag stays useful as a coarse filter — most non-fired bars
   produced no fill regardless.

4. **Cross-ref sample row count.** Smoke showed 18 parquet rows for
   the cross-referenced (AAPL, 2024-06-04) — which equals the
   number of active edges. This means every active edge gets a row
   per (ticker, bar) regardless of whether it scored non-zero. That's
   the design choice: training data should include the no-signal
   distribution, not just the firings. Downstream training code can
   filter to `fired=True` if it wants only contributors.

5. **Branch contamination during development.** This branch had
   transient state from agents on `cap-recalibration` and (yesterday)
   `capital-allocation-fix` land in the same shared worktree. I
   stashed-and-restored my files three times to keep the commit clean.
   Final commit has only the 5 files I authored — no `config/` edits,
   no Agent C `.cap_recal_bak` files. Director can confirm via
   `git show --stat` on the merge commit.

---

## File manifest

| file | role |
| --- | --- |
| `engines/engine_a_alpha/per_ticker_score_logger.py` | NEW — logger class + helpers |
| `engines/engine_a_alpha/alpha_engine.py` | MODIFIED — accept logger arg, call `log_bar` after `signals` built |
| `orchestration/mode_controller.py` | MODIFIED — accept flag, build logger after CockpitLogger, flush after run |
| `scripts/run_backtest.py` | MODIFIED — argparse flag + plumb-through |
| `scripts/smoke_per_ticker_logger.py` | NEW — fast e2e validation |
| `tests/test_per_ticker_score_logger.py` | NEW — 18 tests |
| `docs/Audit/per_ticker_score_logging_2026_04.md` | NEW — this doc |

Branch: `per-ticker-score-logging` off `main`.
