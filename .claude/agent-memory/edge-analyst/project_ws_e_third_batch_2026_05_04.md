---
name: ws-e-third-batch-data-realities-2026-05-04
description: Project memory — calendar/event/pairs feature batch 3 substrate findings. Logs which spec'd features required substitution, where the data actually lives, and overfitting risks specific to the new feature shapes.
type: project
---

WS-E third batch (5 features): days_to_quarter_end, month_of_year_dummy,
pair_zscore_60d, earnings_proximity_5d, vix_change_5d. Built on branch
`ws-e-third-batch` in worktree `agent-abe8ed7a3b8f0db5a`.

**Why:** Substrate validation past the 10-feature target — confirms the
Foundry can absorb non-OHLCV features (earnings, FRED, calendar) at
constant marginal cost. Batches 1+2 were mostly technical-momentum;
this batch fills the calendar / event / pairs gap.

**How to apply:**

Data realities for next-batch authors:
- VIX9D and VIX3M are NOT in `data/macro/`; only VIXCLS exists. Any
  feature spec invoking VIX term-structure must substitute (I used
  velocity instead) OR add a FRED fetcher for those series first.
- Earnings parquets at `data/earnings/<TICKER>_calendar.parquet` use
  `announcement_date` as DatetimeIndex with cols including
  eps_actual / eps_estimate / eps_surprise_pct. yfinance backend
  (per `project_finnhub_free_tier_no_historical_2026_04_25` memory).
- FRED parquets at `data/macro/<SERIES_ID>.parquet` have
  DatetimeIndex named `date` with single `value` column. Same pattern
  for every series (VIXCLS, T10Y2Y, DGS10, etc.).
- `data/processed/<TICKER>_1d.csv` for OHLCV (existing close_series).

Substrate patterns confirmed reusable:
- `close_series`-style cached-per-ticker accessor pattern works for
  any per-ticker parquet — replicated cleanly for earnings_calendar
  (`announcement_dates`) and fred_macro (`series`).
- New DataSource subclasses self-register at import time via decorator
  side-effect, identical to LocalOHLCV / CFTCCommitmentsOfTraders.
- Adversarial twin generator handles ticker-independent features
  (calendar, VIX) without modification — stable_seed keys on
  (feature_id, ticker) so twin is per-ticker even when real isn't.

Statistical traps in batch 3:
- Three of five features (`days_to_quarter_end`, `month_of_year_dummy`,
  `vix_change_5d`) are ticker-independent. Standalone they contribute
  near-zero panel information; their value is interaction terms with
  per-ticker features (beta, size). Standalone ablation Sharpe will
  understate them. Meta-learner with cross-feature interactions
  (GBM, random forest) is the right consumer; linear models will
  miss the interaction lift.
- `month_of_year_dummy` is float-encoded but semantically categorical.
  Linear meta-learners will infer spurious monotonicity. Document
  this clearly in the model card so consumers know.
- `pair_zscore_60d` has 90%+ missing-value rate by design (only 10/109
  tickers mapped). Coverage is the bigger constraint than precision —
  expansion to cointegration-discovered pairs is a Discovery follow-up.
- `earnings_proximity_5d` correlated with `days_to_quarter_end` for
  tech mega-caps that cluster on the same 4 announcement weeks. Joint
  ablation must be checked when both are active to avoid double-counting.
- All 5 features are unverified against real backtest. Synthetic
  ablation in tests uses prior contributions (0.02-0.08), NOT measured
  Sharpe. Real lift requires production-pipeline integration which is
  the substrate's deferred follow-on (per `core/feature_foundry/index.md`).

LOC budget:
- 4 of 5 features at ≤ 50 LOC. `pair_zscore_60d` is 74 LOC due to
  the 9-line pair map; existing `cot_commercial_net_long.py` is 73
  LOC for similar reasons (mapping table). 50-LOC target is soft.

Test pattern: tests use synthetic data fixtures rooted at `tmp_path`
to avoid touching real `data/`, identical to batches 1+2. Module-level
import-cache interaction with `test_feature_foundry.py`'s
autouse-clear-registry fixture causes cross-file failures when ALL
foundry tests run in one session — this is a pre-existing infrastructure
issue affecting batches 1+2 the same way. In-isolation, each batch
file passes 100%.
