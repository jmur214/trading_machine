# Lifecycle Gauntlet Investigation — Why Isn't `value_earnings_yield_v1` Being Caught?

**Date:** 2026-05-08
**Trigger:** Per-edge contribution analysis (`docs/Measurements/2026-05/per_edge_contribution_2026_05_08.md`) found `value_earnings_yield_v1` is a **−$1,192 net drag** on the 6-active ensemble (−37.2% share) over 2021-2025. Yet the edge is still status=`active` in `edges.yml`. This investigation explains why the autonomous lifecycle hasn't paused or retired it.

## TL;DR

The retirement gate WOULD fire on `value_earnings_yield_v1` in 3 of 5 yearly evaluation windows (2021, 2022, 2024). Per-year edge Sharpe is −3.99, −3.65, and −1.89 respectively — all far below `benchmark_sharpe − retirement_margin (0.3)`. Trade-count and days-active gates are met (1659 lifetime trades, 5+ years).

It hasn't fired because **`lifecycle_history.csv` has zero 2026 entries** — the lifecycle hasn't been evaluated in production since the V/Q/A edges shipped on 2026-05-06. The recent runs have all gone through `scripts/run_isolated.py`, which snapshots and restores `lifecycle_history.csv` (and `edges.yml`) at the harness boundary. Any lifecycle decision fired during these runs is wiped on context exit.

This is exactly the architectural problem F11 Phase 2 was designed to solve.

## Per-year retirement-gate analysis

For each yearly run's `value_earnings_yield_v1` slice, computed `_edge_sharpe_from_pnl(pnls)` and compared against approximate SPY benchmark Sharpe minus the configured 0.3 margin:

| year | n trades | win % | total pnl ($) | edge Sharpe | benchmark | threshold | gate fires? |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2021 | 247 | 36.84% | −396 | −3.995 | ≈+1.4 | 1.10 | **YES** |
| 2022 | 339 | 40.41% | −1,106 | −3.645 | ≈−0.9 | −1.20 | **YES** |
| 2023 | 413 | 52.06% | +683 | +2.158 | ≈+1.5 | 1.20 | NO |
| 2024 | 393 | 35.11% | −479 | −1.890 | ≈+1.6 | 1.30 | **YES** |
| 2025 | 267 | 45.32% | +108 | +0.497 | ≈+0.6 | 0.30 | NO |

The 3-of-5 fire rate is dispositive: if the lifecycle had been allowed to evaluate on these windows, the edge would have been paused or retired in the very first year (2021).

## Why the autonomous lifecycle hasn't fired

`engines/engine_f_governance/lifecycle_manager.py:587` writes decisions to `edges.yml` and appends to `lifecycle_history.csv`. The audit trail shows:

```
$ wc -l data/governor/lifecycle_history.csv
33

# Latest timestamp in the file:
2025-12-31 00:00:00+00:00
```

**Zero entries from 2026.** Since `value_earnings_yield_v1` shipped 2026-05-06, the lifecycle hasn't seen it in a non-snapshotted run.

Why? Two mechanisms:

1. **The determinism harness wipes lifecycle decisions.** `scripts/run_isolated.py:75` snapshots 4 files including `lifecycle_history.csv` on entry, and restores them on exit. Any decision fired inside the `isolated()` context — e.g., during the multi-year measurement runs that produced today's audit data — is silently discarded. This was the original F11 architectural complaint.

2. **The autonomous discovery cycle hasn't fired in production.** `governor.evaluate_lifecycle` is called from `mode_controller.run_backtest` after every governor-enabled run. Without `--discover` AND without the harness, that path mutates `edges.yml` in place and persists `lifecycle_history.csv`. But the recent runs have all been measurement runs through the harness — there hasn't been a non-harness `run_backtest` since the V/Q/A edges shipped.

## What F11 Phase 2 fixes

F11 Phase 2 (shipped 2026-05-07, commit `8518c1d`) added the `apply_journal_at_end: bool = False` flag to `mode_controller.run_backtest`. When True, lifecycle decisions append to `data/governor/lifecycle_journal.jsonl` instead of mutating `edges.yml` directly. The journal is NOT in the snapshot harness's scope by default — so decisions persist across harness reps.

The wire-up is in place. What's needed is:
- A real autonomous cycle run that fires lifecycle, OR
- A measurement run with `apply_journal_at_end=True` followed by a manual `journal_apply` step

## Recommendation (propose-first)

Per CLAUDE.md: **"Never manually edit `data/governor/edge_weights.json` or promote edges by hand. Engine F manages lifecycle autonomously. The discovery cycle (`--discover` flag) handles promotion."**

The right action is to run the autonomous discovery cycle in production (i.e., NOT inside `run_isolated`) once. That:

1. Reads the current `data/trade_logs/` (which has the 5-year V/Q/A trade evidence) into `governor.update_from_trade_log`
2. Calls `governor.evaluate_lifecycle` and `governor.evaluate_tiers`
3. Persists decisions to `edges.yml` + `lifecycle_history.csv`
4. The system autonomously decides whether to pause / retire `value_earnings_yield_v1`, `accruals_inv_asset_growth_v1`, or any other underperforming edge

This is a real state mutation. The user's call whether to fire it now or wait for the next scheduled cycle.

Alternative: re-run the multi-year backtest with `apply_journal_at_end=True`. Lifecycle decisions land in the journal; user reviews via `python -m scripts.journal_apply --dry-run` and then commits via `python -m scripts.journal_apply`. This is the F11-Phase-2-blessed path and is what the original F11 design intends.

## What this finding tells us about the system

1. **The lifecycle gauntlet works.** When given evidence it would fire correctly (3 of 5 fire-events on a clearly-underperforming edge).
2. **The harness is the bottleneck.** The 4-file snapshot scope (specifically `edges.yml` + `lifecycle_history.csv`) defeats the lifecycle mechanism for any run that goes through `run_isolated`.
3. **F11 Phase 2 is exactly the right architectural fix.** The journal pattern decouples measurement runs from lifecycle decisions, so the harness can preserve reproducibility WITHOUT throwing away the decisions.
4. **The audit-trail gap is the diagnostic.** When `lifecycle_history.csv` has no 2026 entries despite a year of edge activity, that's the signal something is wrong — not that the lifecycle is broken, but that nothing has actually run it in production.

## Caveats

- The benchmark Sharpe values used in the table above are approximate SPY annual Sharpes. The real lifecycle gate uses the actual `benchmark_sharpe` computed by `core.benchmark.compute_benchmark_metrics` over the same window — slightly different numbers but the directional conclusion (gate would fire) is robust.
- The per-year edge Sharpe is computed over PnL series, not return series. This matches what `_edge_sharpe_from_pnl` does — annualized via √252 — but is technically a per-trade-pnl Sharpe, not a per-day return Sharpe. Magnitudes are comparable across edges; absolute interpretation differs from a portfolio-level Sharpe.
- The ~$200 per-trade typical PnL means even small win/loss fraction differences move the Sharpe a lot. The 36-40% win rates in losing years are far below the ~50% break-even, hence the strongly negative Sharpes.
