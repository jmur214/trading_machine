# Spec — T-2026-05-12-053: Fresh per-ticker score capture on current 6 actives + Phase 0 re-run

**Date drafted:** 2026-05-12 (director-side, ~15 min)
**Status:** SPEC for queue. Engine-A-touch only (read-only); minimal risk. Autonomous-improvement category per CLAUDE.md.
**Will be executed by:** Director or Agent A/B when one frees up (~2-3 hr).
**Sequencing:** can run any time after T-035-style infrastructure is on main. No dependencies; standalone.
**Output:** fresh per-ticker score parquet + re-run of Phase 0 pairwise correlation diagnostic + audit doc.

---

## Why

The 2026-05-12 Phase 0 pairwise correlation diagnostic (`docs/Audit/pairwise_signal_correlation_phase0_2026_05_12.md`) confirmed the signal-diversity gate fires on the available 10-edge older snapshot. But that snapshot is from 2026-04-30 and contains only 2 of the current 6 active edges (`gap_fill_v1`, `volume_anomaly_v1`).

The other 4 actives (`value_earnings_yield_v1`, `value_book_to_market_v1`, `accruals_inv_sloan_v1`, `accruals_inv_asset_growth_v1`) are all SimFin-fundamentals-derived. **Strong prior: they cluster at ρ > 0.7 among themselves by construction.** T-036's UNIFORMLY NEGATIVE α verdict on all 4 supports this prior.

This task confirms the prior with direct measurement on the current edge set.

---

## What

1. Run a substrate-honest backtest on the current 6 actives with `--log-per-ticker-scores` enabled. Single rep, single year (2024) is sufficient — we don't need the full 15-cell grid; the correlation matrix is a per-bar per-edge measurement.

2. Output: `data/research/per_ticker_scores/<run_uuid>.parquet` with raw_score per (timestamp, ticker, edge_id) for the 6 actives.

3. Re-run the Phase 0 pairwise correlation diagnostic (Python code in the existing Phase 0 audit) on the fresh capture. Report:
   - Pairwise Spearman matrix (full 6x6 + including the 5 paused edges that fire if any)
   - Per-day cross-sectional mean approach
   - Per-(ticker, date) panel approach
   - Decision tree result: max ρ + avg ρ vs gate thresholds

4. Update Phase 0 audit doc with the fresh-data verdict alongside the older-snapshot verdict.

---

## Acceptance

1. **Fresh per-ticker score parquet** at `data/research/per_ticker_scores/<run_uuid>.parquet`. ≥ 200K rows expected (109 tickers × 6 actives × 252 days × 1 year ≈ 165K bars).
2. **Re-computed Phase 0 diagnostic** on the fresh data. Report max ρ + avg ρ for both aggregation approaches.
3. **Updated Phase 0 audit doc** at `docs/Audit/pairwise_signal_correlation_phase0_2026_05_12.md` with a new "Phase 0b — Fresh capture on current 6 actives" section. Include:
   - Per-pair correlation matrix
   - Specific verdict on whether the 4 V/Q/A edges cluster at the predicted ρ > 0.7
   - Pruning recommendation: which (if any) of the 4 V/Q/A edges is the redundancy candidate
4. **No new tests required** — pure director-side analysis on output of existing harness.
5. **No commits to engines/**, no production-state changes. Pure data capture + analysis.
6. **Branch:** `feature/fresh-per-ticker-capture-phase0b` (off origin/main). Push only; director merges.

---

## Hard constraints

- DO NOT modify Engine A code. Pure logger-enabled re-run + analysis.
- DO NOT modify any governor files. The active edge set as-is.
- Use `scripts.run_backtest --log-per-ticker-scores` with substrate-honest config:
  ```bash
  PYTHONHASHSEED=0 python -m scripts.run_backtest \
      --start-date 2024-01-01 --end-date 2024-12-31 \
      --log-per-ticker-scores \
      --apply-journal-at-end \
      --reset-governor
  ```
- Per CLAUDE.md: no Sharpe headlines from this run (it's a logger capture, not a measurement). Determinism-canon notes are still valuable.

---

## Time budget

- Backtest run: ~14 min (1 year, single rep, substrate-honest universe)
- Analysis: ~30 min (pairwise correlation matrix on ~165K rows is fast)
- Audit doc update: ~30 min
- **Total: ~75 min** (1.25 hr)

---

## Director note

This is a quick smoke confirmation, NOT a major dispatch. Either of:
- Director runs locally when laptop is free
- Add to next agent free-slot brief as a 1.5-hr appendix

Most natural fit: Agent A or B picks it up after their current chain completes. Brief is small enough to include as a chain extension rather than a fresh dispatch.

## Forward-look

If the fresh capture confirms the prior (4 V/Q/A edges cluster ρ > 0.7), then T-043's pruning recommendation gets sharper: retire 3 of the 4 V/Q/A edges (keep one as the value+quality bucket representative), opening 3 edge slots for genuinely diverse signal sources (T-052 regime features land first, then event-driven sleeves).

If the fresh capture surprises (V/Q/A edges genuinely diverse), then T-043's framing changes — the signal-diversity gap is purely in the 2 technical pairs identified in Phase 0a, and aggregator iteration on the cleaned set may have more chance than the dive predicted.

Either outcome is informative and worth the 1.25 hr.
