# Engine E HMM Variant C enable — A/B verdict (2026-05-09)

**Task:** T-2026-05-09-015
**Generated:** 2026-05-09

## Setup

- Cell A — HMM OFF, 6 edges (T-002 ARM1_EDGES)
- Cell B — HMM ON Variant C (minimal_c, hmm_minimal_C_v1.pkl), 6 edges (same)
- Edges (same in both cells): `gap_fill_v1, volume_anomaly_v1, value_earnings_yield_v1, value_book_to_market_v1, accruals_inv_sloan_v1, accruals_inv_asset_growth_v1`
- Window: 2021-2025 calendar years, 1 rep × 5 years per cell.
- Universe: F6 historical S&P 500 (substrate-honest).
- Determinism: T-002 record was 30/30 deterministic; we verify per-year.

## Verdict

**WASH**

> |ΔSharpe|=0.0010 < 0.05 — HMM is a wash on Sharpe axis; keep flag OFF. Sortino delta N/A (harness doesn't capture) (Sortino capture is a deferred follow-up; harness's `summary['Sortino Ratio']` returns None on this code path).

| metric | value |
|---|---:|
| Δ Sharpe (point, harness per-trade Sharpe) | -0.0010 |
| Δ Sharpe ci_low (5-year cross-year bootstrap) | -0.0022 |
| Δ Sharpe ci_high | +0.0000 |
| Δ Sortino | N/A (harness doesn't capture) |
| Δ MDD pct (B - A) | +0.00% |

Per CLAUDE.md 6th non-negotiable: verdict bucket reads `ci_low`, not point Δ.

## Cell A — HMM OFF (baseline)

| Year | Sharpe (per-trade) | MDD pct | Win Rate pct | Snapshot Sharpe (per-bar, diagnostic) | Determinism |
|---:|---:|---:|---:|---:|---|
| 2021 | +0.4130 | -7.74% | 56.92% | +3.997 | PASS |
| 2022 | +0.1160 | -2.18% | 43.00% | +2.789 | PASS |
| 2023 | +0.2610 | -6.19% | 55.95% | +3.812 | PASS |
| 2024 | +0.2360 | -1.83% | 41.13% | +2.965 | PASS |
| 2025 | +0.3250 | -2.56% | 50.22% | +3.078 | PASS |

**Cross-year mean (per-trade Sharpe):** +0.2700  (95% CI [+0.1870, +0.3600])

**Sortino:** N/A — `mc.run_backtest`'s summary dict does not populate `Sortino Ratio` on this code path; would require a separate post-process from per-trade PnL. Flagged in caveats.

**Cross-year MDD:** -4.10%  |  **Win Rate (per-trade):** 49.44%  |  **n_years:** 5

## Cell B — HMM ON Variant C

| Year | Sharpe (per-trade) | MDD pct | Win Rate pct | Snapshot Sharpe (per-bar, diagnostic) | Determinism |
|---:|---:|---:|---:|---:|---|
| 2021 | +0.4130 | -7.74% | 56.92% | +3.997 | PASS |
| 2022 | +0.1160 | -2.18% | 43.00% | +2.789 | PASS |
| 2023 | +0.2610 | -6.19% | 55.95% | +3.813 | PASS |
| 2024 | +0.2340 | -1.83% | 41.51% | +2.965 | PASS |
| 2025 | +0.3220 | -2.56% | 49.83% | +3.078 | PASS |

**Cross-year mean (per-trade Sharpe):** +0.2690  (95% CI [+0.1860, +0.3590])

**Sortino:** N/A — `mc.run_backtest`'s summary dict does not populate `Sortino Ratio` on this code path; would require a separate post-process from per-trade PnL. Flagged in caveats.

**Cross-year MDD:** -4.10%  |  **Win Rate (per-trade):** 49.44%  |  **n_years:** 5

## Per-year delta (Cell B − Cell A)

| Year | Δ Sharpe | Δ MDD pct | Trade-streams match? | Cell A canon md5 | Cell B canon md5 |
|---:|---:|---:|---|---|---|
| 2021 | +0.0000 | +0.00% | **identical** | `bd9ca4e47a7a9505` | `bd9ca4e47a7a9505` |
| 2022 | +0.0000 | +0.00% | differ | `77e6aa5cab579ce8` | `f2e7f6d4862ff9c1` |
| 2023 | +0.0000 | +0.00% | differ | `b799c65219bb0de1` | `f49c2dadd05f26a1` |
| 2024 | -0.0020 | +0.00% | differ | `cfc02811b20bf4da` | `cb215e5e1fb2b700` |
| 2025 | -0.0030 | +0.00% | differ | `f566269b78d297cc` | `69417f0986d7e5b0` |

Years where trade streams are bitwise-identical (e.g., 2021 here) indicate HMM did not modulate ANY trade decision that year — the regime stayed in a confidence range that left the risk_scaler at 1.0× throughout. Years where streams differ but Sharpe deltas are tiny indicate HMM did modulate timing but the cumulative effect on per-trade PnL washed out at the aggregate level.

## Determinism check

- Cell A: PASS (5/5 years deterministic)
- Cell B: PASS (5/5 years deterministic)

Each year's `trades_canon_md5_unique=1` confirms reps within a year produced bitwise-identical trade outputs. With 1 rep per year, this is a single-md5 sanity (full-determinism gate would need ≥2 reps; T-002's 30/30 record is the established baseline).

## Open questions / caveats

1. **HMM model-load determinism.** The HMM model file (.pkl) is loaded fresh from disk at RegimeDetector init each run. T-002's 30/30 determinism record is strong evidence the load path is reproducible, but we did not insert a model-file-mtime audit in this run. If a future regression appears, that's the first place to look.

2. **Per-regime stratification.** The HMM emits a regime label per bar via `RegimeDetector.detect_regime(...)['hmm_regime']` but that field is NOT persisted in `portfolio_snapshots.csv`. Computing a per-regime Sharpe stratification ("in crisis days...") would require either re-running with a logging hook OR replaying the saved HMM model offline against the price series. Deferred — flagged as Phase-2 follow-up if downstream wants to test whether the Sortino delta concentrates in particular regime states.

3. **Same-edges-set contract held.** Both cells use the identical 6-edge set (T-002 ARM1_EDGES). The HMM flag is the ONLY inter-cell variable. T-002's Arm 2 also pruned 2 edges; bundling that pruning with HMM-on conflated the +0.024 Sharpe / +0.16 Sortino delta. T-015 isolates HMM as the lone variable — cleaner attribution.

4. **Cross-year bootstrap n=5 is small.** With 1 rep × 5 years per cell, the cross-year bootstrap on the delta sees a 5-element series. CI widths are correspondingly wide. If a borderline-bucket verdict emerges, running an additional rep (rep=2) per year would tighten the CI without doubling wall-time — most of the cost is data prep, not solver. Document any narrow-margin verdict as such.

5. **Cells run sequentially, ~13-15 min each.** Total wall-time ~2 hr local. Cloud parallel-launcher (`scripts/submit_substrate_run.py`) can do this in ~15 min wall but adds container overhead and requires the AWS Batch infra (T-014 directorial work). Local was sufficient at this scale.

6. **Production flag default UNCHANGED.** This A/B does NOT change `config/regime_settings.json`'s `hmm.hmm_enabled` from `false` to `true`. The harness patches the file mid-run and restores in finally; on-disk default stays OFF. Any deployment flip is a separate director-approved follow-up (T-016 propose-first per CLAUDE.md governor-settings rule).
