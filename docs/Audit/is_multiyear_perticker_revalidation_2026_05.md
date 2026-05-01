# IS Multi-Year + Per-Ticker Meta-Learner Revalidation Under Harness

**Date:** 2026-05-01
**Branch:** `is-multiyear-perticker-revalidation`
**Worktree:** `trading_machine-ismulti`
**Anchor:** `data/governor/_isolated_anchor` (post-lifecycle-pruning state, 17-edge ensemble: 3 active + 14 paused + 0 retired/archived loaded)

Two measurement gaps from the 2026-05-01 ship-state assessment, closed under the deterministic harness:

1. **Task A** — 2021-2024 IS prod-109 with production-equivalent ensemble.
   Drifted readings: 1.063 / 1.113 (governor-state contaminated).
2. **Task B** — Per-ticker meta-learner on 2025 OOS prod-109.
   Earlier reading: 0.516 (governor-drifted, prior to harness).

Both ran 3 replicates under `scripts.run_isolated.isolated()` to verify within-cell variance = 0.000.

---

## Methodology

- Isolation: `scripts/run_isolated.py` snapshots/restores `data/governor/{edges.yml, edge_weights.json, regime_edge_performance.json, lifecycle_history.csv}` around each backtest. `PYTHONHASHSEED=0` enforced.
- Universe: `prod-109` (109 tickers from `config/backtest_settings.json`, no filtering).
- Ensemble: production-equivalent — `ModeController.run_backtest` loads all 17 edges with `PAUSED_WEIGHT_MULTIPLIER=0.25` applied automatically to soft-paused edges. **No `status='active'` filtering** in the driver.
- Costs: realistic Almgren-Chriss slippage + ADV-bucketed half-spread (default in `config/backtest_settings.json`).
- Reset governor: `--reset-governor` true on every run.

### Task A — q3 task added to `run_oos_validation.py`

New task `q3` mirrors `q1` but with `override_start="2021-01-01"`, `override_end="2024-12-31"`. Output goes to `data/research/oos_validation_q3.json`.

### Task B — per-ticker training + OOS

- **Training:** `scripts/train_per_ticker_metalearner.py` consumed the existing 1.85M-row 2021-01-04 → 2024-12-30 per-ticker scores parquet (109 tickers × 17 edges, leakage check PASS — max ts < 2025-01-01).
- **109/109 models trained**, 0 skipped. Aggregate stats:
  - Mean OOS walk-forward corr: **+0.1750** (median +0.1714)
  - Fraction with mean_oos_corr > 0: **97.2%**
  - Mean train R²: 0.513
  - Top tickers: TJX (+0.350), ELV (+0.346), INTC (+0.338), CI (+0.297), DKNG (+0.297)
  - Bottom tickers: COIN (-0.024), ADBE (-0.013), AVGO (-0.003), TSLA (+0.001)
- **OOS run:** `scripts.run_per_ticker_oos --mode per_ticker` flips `metalearner.enabled=true` AND `per_ticker=true` in `config/alpha_settings.prod.json` for the run, then restores afterward. Per-ticker model dir: `data/governor/per_ticker_metalearners/`.

Bug fix: `run_per_ticker_oos.py` only works when invoked as `python -m scripts.run_per_ticker_oos`; running it as a script raises `ModuleNotFoundError: No module named 'scripts'`. Documented for future use.

---

## Task A Results — IS multi-year (2021-2024) prod-109

| Run | Sharpe | CAGR (%) | MDD (%) | Vol (%) | Win Rate (%) | run_id (head) | trades_canon_md5 |
|---|---|---|---|---|---|---|---|
| 1 | 0.905 | 4.67 | -8.03 | 5.20 | 50.05 | b60d01c2 | 2f0488dada30808553b42eb7b4b85b08 |
| 2 | 0.905 | 4.67 | -8.03 | 5.20 | 50.05 | d6faefe0 | 2f0488dada30808553b42eb7b4b85b08 |
| 3 | 0.905 | 4.67 | -8.03 | 5.20 | 50.05 | 0168af38 | 2f0488dada30808553b42eb7b4b85b08 |

**Within-cell Sharpe range:** 0.000. **Unique canon md5: 1/3.** Harness invariant verified.

### Comparison to drifted readings

| Source | Sharpe | Delta vs harness |
|---|---|---|
| Drifted #1 (round-1 ship measurement) | 1.063 | +0.158 |
| Drifted #2 (round-2 measurement) | 1.113 | +0.208 |
| **Harness deterministic** | **0.905** | — |

The drifted readings overstated IS multi-year Sharpe by **+0.16 to +0.21** — same magnitude class as the 04-30 governor-drift artifacts. Bracket *shape* (positive Sharpe, light vol, modest CAGR) survives; magnitudes do not.

### Comparison to benchmarks (2021-01-01 → 2024-12-31)

| Metric | System | SPY | QQQ | 60/40 |
|---|---|---|---|---|
| Sharpe | **0.905** | 0.875 | 0.702 | 0.361 |
| CAGR (%) | 4.67 | 13.94 | 14.15 | 3.75 |
| MDD (%) | -8.03 | -24.50 | -35.12 | -27.24 |
| Vol (%) | 5.20 | 16.48 | 22.45 | 12.29 |

**System beats SPY on risk-adjusted return by +0.030 Sharpe**, beats QQQ by +0.203, beats 60/40 by +0.544. Absolute return is **1/3 of SPY** — system trades very light (5.2% vol vs SPY 16.5%); it's an under-deployed-capital regime, not a "matches SPY in dollars" regime.

### IS vs OOS gap (deterministic readings)

| Window | Sharpe | Source |
|---|---|---|
| 2021-2024 IS prod-109 | 0.905 | This work |
| 2025 OOS prod-109 (cap=0.20, ML off, floors on) | 0.984 | Agent A path1-revalidation |

OOS Sharpe **exceeds** IS Sharpe by +0.079. No IS overfit signal. The active edge set is regime-stable across the IS→OOS transition rather than 2025-favorable.

---

## Task B Results — Per-ticker ML on 2025 OOS prod-109

| Run | Sharpe | CAGR (%) | MDD (%) | Vol (%) | Win Rate (%) | run_id (head) | trades_canon_md5 |
|---|---|---|---|---|---|---|---|
| 1 | 0.442 | 2.03 | -3.21 | 4.83 | 46.36 | 67718134 | 8783f8858001521ea2cf02e81249e107 |
| 2 | 0.442 | 2.03 | -3.21 | 4.83 | 46.36 | 1ad86c8e | 8783f8858001521ea2cf02e81249e107 |
| 3 | 0.442 | 2.03 | -3.21 | 4.83 | 46.36 | 322fa7a1 | 8783f8858001521ea2cf02e81249e107 |

**Within-cell Sharpe range:** 0.000. **Unique canon md5: 1/3.** Harness invariant verified.

### Side-by-side ML configurations on 2025 OOS prod-109

| Config | Sharpe | Delta vs ML-off | Source |
|---|---|---|---|
| ML off (cap=0.20, floors on) | **0.984** | (baseline) | Agent A path1-revalidation |
| Portfolio ML on (cap=0.20) | 0.406 | **-0.578** | Agent A path1-revalidation |
| **Per-ticker ML on (cap=0.20)** | **0.442** | **-0.542** | This work |

### Verdict on per-ticker direction

Per-ticker meta-learner:
- **Marginally beats portfolio meta-learner** by +0.036 Sharpe on 2025 OOS prod-109 — the per-ticker hypothesis (idiosyncratic edge × ticker interactions) shows a small real signal.
- **Falls catastrophically short of ML-off baseline** by -0.542 Sharpe — same magnitude class as the portfolio meta-learner's drag.
- The +0.175 mean walk-forward OOS correlation does NOT translate into ensemble lift. Predictive ranking ability of the model > 0 in walk-forward CV, yet downstream signal-processor + portfolio-construction interaction destroys the ensemble Sharpe.

The per-ticker direction is **falsified at the deployment level** under harness, even though the model-level walk-forward signal is genuinely positive. The previous 0.516 reading (pre-harness) overstated by +0.074, consistent with governor-drift magnitude.

The portfolio meta-learner FALSIFICATION memory (`project_metalearner_drift_falsified_2026_05_01.md`) extends: **per-ticker is also falsified.** Both `metalearner.enabled` AND `metalearner.per_ticker` should stay `false` on main.

What's still possible with meta-learners (not falsified by this work):
- Different feature engineering (currently only `tier=feature` raw scores; could include regime, vol, breadth state).
- Different objective (currently fits per-ticker forward H-day return; could fit per-edge-firing conditional return).
- Different architecture (currently lasso-style linear; could try gradient boosting or shrinkage estimators).

But each of these requires fresh evidence that walk-forward signal translates to ensemble lift — and this work is the second consecutive failure of that translation. The reasonable conclusion is that the meta-learner's gradient on Sharpe is approximately zero or negative across reasonable architectures, and the next moonshot edge or universe-expansion move dominates this direction.

---

## Combined Headline

**Both measurements confirm the current ship-state assessment.**

1. **IS multi-year deterministic Sharpe = 0.905**, 0.16–0.21 below the drifted readings, but still beats SPY 0.875 by +0.030 and shows OOS-IS lift (no overfitting). The 0.984 OOS reading from Agent A's path1 work stands as the deployable headline. The system is genuinely producing modest risk-adjusted alpha on the design universe across both windows.

2. **Per-ticker meta-learner deterministic Sharpe = 0.442**, marginally better than portfolio ML (0.406) but a -0.54 drag vs ML-off (0.984). The walk-forward training showed +0.175 mean OOS corr (97.2% positive), yet that signal does not survive end-to-end deployment. Per-ticker stays `false`; meta-learner direction is now falsified at both the portfolio and per-ticker levels.

3. **Deployment-state confidence is unchanged.** Ship state remains `cap=0.20 + ML off + floors on`. No new alpha unlocked by this work; no existing claims overturned. The "IS overstated by ~0.2 Sharpe" finding is consistent with the broader governor-drift class — bracket shape is durable, magnitudes are not.

4. **What this changes for the forward plan.** Tier 1 #2 ("IS multi-year verification") and Tier 4 #10 ("per-ticker meta-learner re-validation") both close. The forward plan's remaining moves — Reform Gate 1 baseline fix, Statistical Moonshot Sleeve, Discovery gene-vocabulary widening, universe expansion, alt-data ingestion — gain priority since the ML branches are now both empirically capped.

---

## Files produced

- `scripts/run_oos_validation.py` — added `q3` task for IS multi-year prod-109.
- `data/research/oos_validation_q3.json` — Task A run #3 summary (last write wins; runs 1+2 are bitwise-identical).
- `data/research/oos_validation_q1.json` — Task B run #3 summary (last write; PT mode).
- `data/governor/per_ticker_metalearners/*.pkl` — 109 trained per-ticker models, in this worktree's per-agent governor copy only.
- `data/research/per_ticker_metalearner_summary_ismulti.csv` — training summary.
- `docs/Audit/is_multiyear_perticker_revalidation_2026_05.md` — this document.

## Audit-trail run_ids

| Task | Run | run_id |
|---|---|---|
| q3 | 1 | b60d01c2-dfc8-4c5a-b9ad-49a53ebc6f0b |
| q3 | 2 | d6faefe0-598d-4ce5-ba69-0af6cac4d8cc |
| q3 | 3 | 0168af38-7d4a-4a83-a035-876e2cb9792c |
| pt-OOS | 1 | 67718134-da4a-4e86-85b0-889e2e72a941 |
| pt-OOS | 2 | 1ad86c8e-353c-4781-9aca-a25426385160 |
| pt-OOS | 3 | 322fa7a1-788d-4095-bbc3-171e525c11b9 |
