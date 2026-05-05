# Per-Ticker Meta-Learner Training & 2025 OOS Validation

**Date**: 2026-04-30
**Branch**: `per-ticker-metalearner-training`
**Question**: Does per-ticker training beat the portfolio-level meta-learner
on 2025 OOS?
**Headline**: **No — per-ticker underperforms portfolio (0.516 vs 1.064 Sharpe)**.
The per-ticker forward-return target doesn't capture the integration-level
effects (capital rivalry, soft-pause leak suppression) that the portfolio's
profile-aware fitness target does. Honest result. Methodology in this audit.

## What we built

Three things, sequential, each gated by the previous:

1. **Training corpus generation (B1)** — backtest on the 2021-2024 in-sample
   window with `--log-per-ticker-scores` ON. Produced
   `data/research/per_ticker_scores/695b0b21-18f0-4493-b593-e62abf091519.parquet`.
   - **1,848,937 rows** (~1.85M, matches 04-29 forecast of ~1.87M)
   - **109 tickers × 17 edges**
   - **Date range: 2021-01-04 → 2024-12-30**
   - **Leakage check: PASS** (no rows ≥ 2025-01-01; trainer asserts on this)
   - 7.4% `fired=True`, the rest are no-fire score rows

2. **Per-ticker trainer (B2)** — `scripts/train_per_ticker_metalearner.py`
   reads the parquet, pivots per ticker to (date × edge_id) using `raw_score`,
   builds a per-ticker forward 5-day return target from
   `data/processed/{ticker}_1d.csv`, and runs walk-forward folds (252-day
   train, 5-day forward, 5-day step) per ticker. Final model fit on all
   aligned rows and saved to
   `data/governor/per_ticker_metalearners/{ticker}.pkl`.
   - **109/109 trained, 0 skipped**
   - **Mean OOS corr: +0.175** (median +0.171)
   - **97.2% of tickers** have positive mean OOS corr
   - Mean train R² 0.513
   - Best: TJX (+0.350), ELV (+0.346), INTC (+0.338)
   - Worst: COIN (-0.024), ADBE (-0.013), AVGO (-0.003), TSLA (+0.001)

3. **SignalProcessor wiring (B3)** — `MetaLearnerSettings.per_ticker: bool`
   (default False). When True, `_metalearner_contribution(edge_map, ticker=)`
   loads `data/governor/per_ticker_metalearners/{ticker}.pkl` and falls
   back to the portfolio model on miss. Lazy-loaded + cached per ticker per
   SignalProcessor lifetime. 5 new tests in
   `tests/test_signal_processor_per_ticker.py` (all pass alongside the
   existing 11 metalearner regression tests).

## Training corpus stats + leakage check

```
Source parquet : data/research/per_ticker_scores/695b0b21-18f0-4493-b593-e62abf091519.parquet
n_rows         : 1,848,937
n_tickers      : 109
n_edges        : 17
date range     : 2021-01-04 → 2024-12-30
leakage cutoff : 2025-01-01 — PASS (max_timestamp 2024-12-30 < cutoff)
in-sample run  : ML off, --reset-governor, --no-governor, realistic costs
in-sample Sharpe: 0.733 (3.86% CAGR, -7.32% MDD)
```

The trainer's `assert_no_leakage()` raises `ValueError` on any row with
timestamp ≥ 2025-01-01. The OOS validation that follows is therefore a
strict held-out test.

## Per-ticker model design + fold structure

- **One model per ticker, no clustering.** With ~1,000 daily observations
  per ticker × 17 edges, each model has ~1,000 samples × 17 features.
  That's small but workable for a depth-3 GBR (DEFAULT_HYPERPARAMS:
  300 trees, 0.05 LR, depth 3, subsample 0.8). Cluster fallback was
  not used; cold-start fallback to the portfolio model handles edge
  cases.
- **Target: per-ticker forward 5-day return** (`Close[t+5]/Close[t] - 1`)
  from `data/processed/{ticker}_1d.csv`. Pure ticker-future signal.
- **Walk-forward**: 252-day train / 5-day forward / 5-day step. ~150
  folds per ticker.
- **Per-ticker model file**:
  `data/governor/per_ticker_metalearners/{ticker}.pkl` — same payload
  shape as `metalearner_balanced.pkl` plus a `ticker` field for
  provenance.
- **Cold-start fallback**: when per-ticker file is missing for a ticker,
  SignalProcessor uses the portfolio model. Tested explicitly in
  `tests/test_signal_processor_per_ticker.py::test_per_ticker_falls_back_to_portfolio_for_missing_ticker`.

## Validation table — 2025 OOS

Same window / universe / cost-model as Agent C's `eb0f8270-6f61-46ca-9174-3919da5d0ef6`.

| Metric | ML off (Task C) | **Portfolio ML (Agent C)** | **Per-Ticker ML (this run)** | Δ vs Portfolio |
|---|---:|---:|---:|---:|
| Sharpe Ratio | 0.315 | **1.064** | **0.516** | **−0.548** |
| CAGR (%) | 1.41 | 4.80 | 2.91 | −1.89 pp |
| Max Drawdown (%) | -2.68 | -3.33 | -4.12 | −0.79 pp |
| Volatility (%) | 4.86 | 4.53 | 5.94 | +1.41 pp |
| Win Rate (%) | 39.77 | 48.68 | 47.61 | -1.07 pp |
| Net Profit ($) | +1,406 | +4,770 | +2,897 | -1,873 |
| Run UUID | `d7ae1ca3-...` | `eb0f8270-...` | `192fb115-26bf-4ea9-8cea-5fd6148d44ea` | — |

**Benchmarks (2025)**: SPY Sharpe 0.955, QQQ 0.933, 60/40 0.997. Per-ticker at
0.516 trails all three; portfolio at 1.064 beats all three (at much lower vol).

## Honest verdict — does per-ticker beat portfolio?

**No, by a wide margin (-0.55 Sharpe, -1.9 pp CAGR, +1.4 pp vol).**

The walk-forward in-sample evidence was strong: mean OOS corr +0.175 vs
the portfolio model's +0.056 (3× lift) on a per-ticker forward-return
target. Per-ticker training DOES learn ticker-specific edge weighting;
the in-sample diagnostic confirms that. But the 2025 production-OOS
Sharpe is dramatically worse than portfolio.

### Mechanism — what changed in the trade mix

Edge fill counts in 2025, side-by-side:

| Edge | Portfolio (anchor) | Per-Ticker (this run) | Δ |
|---|---:|---:|---:|
| `momentum_edge_v1` | 3,232 | 2,664 | -568 |
| **`low_vol_factor_v1`** | **85** | **1,394** | **+1,309** |
| **`macro_credit_spread_v1`** | **667** | **0** | **-667** |
| `volume_anomaly_v1` | 108 | 138 | +30 |
| **`macro_dollar_regime_v1`** | **34** | **0** | **-34** |
| `growth_sales_v1` | 93 | 79 | -14 |
| `gap_fill_v1` | 68 | 73 | +5 |
| `value_trap_v1` | 37 | 32 | -5 |
| `herding_v1` | 33 | 26 | -7 |
| `pead_predrift_v1` | 12 | 37 | +25 |
| `panic_v1` | 5 | 2 | -3 |
| `pead_v1` | 4 | 19 | +15 |
| `value_deep_v1` | 2 | 7 | +5 |
| `pead_short_v1` | 0 | 1 | +1 |
| `atr_breakout_v1` | 0 | 0 | 0 |

Two large changes drive the Sharpe drop:

1. **`low_vol_factor_v1` fired 1,394× under per-ticker, vs 85× under
   portfolio.** This is the soft-pause-leak edge from Phase 2.10c
   (paused but `regime_gate{stressed:1.0,crisis:1.0}` re-amplifies it).
   The portfolio model — trained against profile-aware fitness over the
   integration's equity curve — learned to suppress it. The per-ticker
   models — each trained against THEIR ticker's forward 5-day return —
   tend to weight low_vol_factor positively, because low-vol stocks DO
   have a small positive forward drift on most individual names. The
   per-ticker model can't see the GROUP-level damage from running 1,000+
   correlated low-vol fills in 2025.

2. **`macro_credit_spread_v1` was suppressed to zero (667→0)** — but
   that's a KEEP edge per `pruning_proposal_2026_04.md` (a stable
   diversifier, never-negative across 2021-2024). The per-ticker model
   for many tickers learned to under-weight it because per-ticker
   forward-return correlation with a slowly-moving credit-spread signal
   is weak; the model dropped it in favor of higher-correlation edges
   like low_vol_factor.

The per-ticker training target is **wrong for this architecture**:
the portfolio's profile-aware fitness captures cross-ticker integration
effects (rivalry, capital concentration, regime-correlated drawdown);
per-ticker forward return doesn't.

### Caveats matching Agent C's

- **N=1, single window**. 2025 OOS is one realization. Robustness across
  multiple windows would require splitting 2021-2024 into walk-forward
  validation slabs the way Agent C did for the portfolio model. The
  in-sample walk-forward folds look strong (97.2% of tickers positive),
  so the failure is specifically about deploying per-ticker decisions
  into the integrated pipeline, not about the model's per-ticker
  predictive ability.
- **Weak point-prediction.** Per-ticker mean OOS corr +0.175 is
  meaningful but not large; the model's confidence on any single
  bar's call is low.
- **Per-ticker model trained on raw_score, target is forward return.**
  The portfolio model trained on raw_score, target is profile-aware
  fitness over portfolio equity. The TARGET DIFFERS — so the comparison
  isn't pure model-architecture-A vs model-architecture-B, it's
  also targets-A vs targets-B. Per-ticker forward return loses the
  integration-level information.
- **Default OFF**. `metalearner.per_ticker` stays False on main. This
  branch only flipped it for the validation run (then restored).

## Tickers with the largest per-ticker lift vs nothing

Top 10 by walk-forward mean OOS corr (in-sample diagnostic):

| Ticker | Mean OOS corr | Train R² | n_train |
|---|---:|---:|---:|
| TJX | +0.350 | 0.523 | 1,004 |
| ELV | +0.346 | 0.505 | 1,004 |
| INTC | +0.338 | 0.538 | 1,004 |
| CI | +0.297 | 0.486 | 1,004 |
| DKNG | +0.297 | 0.554 | 1,004 |
| TMUS | +0.295 | 0.596 | 1,004 |
| WFC | +0.287 | 0.509 | 1,004 |
| AMAT | +0.285 | 0.556 | 1,004 |
| BDX | +0.282 | 0.519 | 1,004 |
| RTX | +0.275 | 0.542 | 1,004 |

Bottom 10:

| Ticker | Mean OOS corr | Train R² | n_train |
|---|---:|---:|---:|
| COIN | -0.024 | 0.414 | 897 |
| ADBE | -0.013 | 0.410 | 1,004 |
| AVGO | -0.003 | 0.451 | 908 |
| TSLA | +0.001 | 0.563 | 1,004 |
| HON | +0.014 | 0.399 | 1,004 |
| ADP | +0.021 | 0.475 | 1,004 |
| ABBV | +0.052 | 0.404 | 1,004 |
| LIN | +0.056 | 0.519 | 1,004 |
| COP | +0.065 | 0.405 | 1,004 |
| VZ | +0.072 | 0.416 | 1,004 |

**Surprises:**
- TJX (consumer discretionary) shows the cleanest signal. ELV (health),
  INTC (semis), CI (health) round out the top.
- The bottom is dominated by **high-vol/event-driven names**: COIN
  (crypto-correlated), TSLA (event/news driven), AVGO (acquisition story),
  ADBE (margin compression). These tickers' 5-day forward returns are
  dominated by news/macro shocks the per-edge scores can't predict.
- **Mega-caps with idiosyncratic drivers (TSLA, AVGO, ADBE)** all near
  zero — the per-ticker model can't beat the noise floor on names whose
  short-term moves are dominated by single-name catalysts.
- **No tickers were skipped for sparse data.** All 109 had ≥287 aligned
  training rows, so cold-start fallback is technically unused for the
  trained universe — but the fallback path stays load-bearing for any
  future expansion of the universe.

## What this implies for Phase 2.11 strategy

The per-ticker forward-return target is wrong for this architecture.
Three potential next-step framings if the director wants to pursue
per-ticker further:

1. **Per-ticker on profile-fitness target, not raw forward return.** The
   target would be each ticker's CONTRIBUTION to portfolio profile-aware
   fitness over the forward window. Couples per-ticker learning back to
   the integration. Might solve the rivalry-blindness, but adds training
   complexity and breaks the clean "ticker-future signal" framing.

2. **Sector / cluster meta-learners.** Instead of 109 per-ticker models
   or 1 portfolio model, train ~10 per-sector models. Cross-section
   gives more samples per model AND captures within-sector patterns
   without per-ticker overfitting noise.

3. **Hybrid: portfolio model + per-ticker bias term.** Keep the portfolio
   model as the primary, add a per-ticker correction that's bounded so
   it can't dominate. Best-of-both-worlds in principle but adds tuning.

For Phase 2.11 specifically, the simplest honest conclusion is: the
current implementation should stay default OFF, and per-ticker as a
direct replacement of the portfolio model is **not justified by this
single-window evidence**. Multi-window robustness check (rotating 4
in-sample windows + 4 OOS windows) would be the next falsifier.

## Run artifacts

- Training corpus: `data/research/per_ticker_scores/695b0b21-18f0-4493-b593-e62abf091519.parquet`
- Per-ticker models: `data/governor/per_ticker_metalearners/*.pkl` (109 files)
- Per-ticker training summary CSV: `data/research/per_ticker_metalearner_summary.csv`
- OOS Q1 result: `data/research/oos_validation_q1.json` (run_id `192fb115-26bf-4ea9-8cea-5fd6148d44ea`)
- OOS Q1 trades: `data/trade_logs/192fb115-26bf-4ea9-8cea-5fd6148d44ea/trades.csv`
- Driver scripts: `scripts/train_per_ticker_metalearner.py`, `scripts/run_per_ticker_oos.py`
- Tests: `tests/test_signal_processor_per_ticker.py` (5 new), all green alongside
  pre-existing `tests/test_signal_processor_metalearner.py` (11 tests).

Branch: `per-ticker-metalearner-training` off `main` (with
`per-ticker-score-logging` merged in for the logger code).
`metalearner.per_ticker = false` on main; flipped True only for this
validation run, restored after.
